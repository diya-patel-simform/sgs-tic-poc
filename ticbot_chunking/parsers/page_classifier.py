"""Lightweight, local, no-OCR per-page classifier for mixed text/scanned
PDFs: does THIS page (not the whole document) have a usable text layer?

Used by `parsers/page_router.py` to decide, page by page, whether a page
goes to the local parser (`local_pdf.parse_pdf_local_pages`) or to Document
Intelligence (`azure_docintel.parse_pdf_pages`) — see that module's
docstring for the full pipeline.

Deliberately not just `text_length == 0`: a page can have a text layer that
is short-but-real (a mostly-blank cover page), or present but garbled
(a bad OCR text layer baked into an otherwise-scanned PDF, or a font with a
broken encoding), or covered by a full-page image with only a caption's
worth of real text. Six independent signals are combined instead:

- character count and word count (near zero => nothing to extract locally)
- text density (chars per unit page area — catches a page that's mostly a
  full-bleed image with a small text caption, which can still have enough
  raw chars/words to look "text-based" by count alone)
- image coverage (fraction of the page's area covered by embedded images)
- extraction quality (fraction of extracted characters that are ordinary
  alphanumeric/punctuation/whitespace — catches a garbled/mis-encoded text
  layer that has plenty of characters but isn't usable prose)
- multi-column layout (a persistent vertical gutter with text lines on
  both sides across many lines — the local parser's reading-order logic
  (`local_pdf.py`) has no column awareness and reads such a page's lines
  left-to-right across both columns, corrupting reading order; Document
  Intelligence's layout model handles this correctly, so such a page is
  routed there instead of trusted locally even though it has real text)
- table density (a ruled table covering a non-trivial fraction of the
  page — the local parser flattens table cells into plain paragraph text
  with no cell structure; Document Intelligence returns real table cells)

A page is TEXT only if it clears every "confidently usable" threshold at
once AND has neither of the two layout-complexity signals set. A page is
SCANNED if it's essentially empty of usable text or is dominated by a
full-page image. Everything in between — enough of a signal to not be
nothing, not enough to be confident, or simply too layout-complex for the
local parser to trust — is AMBIGUOUS, and (per the page router) treated
the same as SCANNED: sent to Document Intelligence rather than guessed at
or misread locally.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pdfplumber

PAGE_TEXT = "text"
PAGE_SCANNED = "scanned"
PAGE_AMBIGUOUS = "ambiguous"

# A page must clear ALL of these to be classified TEXT.
MIN_TEXT_CHARS = 120
MIN_TEXT_WORDS = 20
MIN_TEXT_DENSITY = 0.0006  # non-whitespace chars per square point of page area
MIN_EXTRACTION_QUALITY = 0.85  # fraction of chars that are alnum/space/ordinary punctuation
MAX_TEXT_PAGE_IMAGE_COVERAGE = 0.6  # a page this covered by images isn't "text" even with some real text

# A page with at most this many characters, or one that's overwhelmingly
# covered by a single image, is SCANNED outright regardless of anything
# else — there's nothing usable to extract locally either way.
MAX_SCANNED_CHARS = 10
SCANNED_IMAGE_COVERAGE = 0.85

_ORDINARY_CHARS_RE = re.compile(r"[^\w\s.,;:!?()\[\]{}'\"/\\%&+\-*=@#$]")

# Multi-column detection: word x-midpoints are bucketed into this many bins
# across the page width, and a persistent internal zero-density "gutter"
# spanning at least this fraction of the page width is treated as a column
# boundary — but only when a meaningful number of text lines sit entirely
# to one side of it or the other (not merely one figure/caption creating an
# incidental empty band).
COLUMN_GAP_BINS = 30
MIN_COLUMN_GUTTER_FRACTION = 0.05
MIN_LINES_PER_COLUMN = 5
_LINE_Y_TOLERANCE = 3.0

# Table-density detection: a ruled-table candidate (pdfplumber's default
# ruling-line strategy — the same one local_pdf.py's own table extraction
# uses) at least this large, covering at least this fraction of the page
# area, means the local parser would flatten real table cells into plain
# paragraph text. Deliberately does not attempt to also detect *unruled*
# (whitespace-aligned) tables here — local_pdf.py already documents that as
# a known, separate limitation, and a reliable generic heuristic for it
# would be far more failure-prone than this ruled-table check.
MIN_TABLE_ROWS = 3
MIN_TABLE_COLS = 2
MIN_TABLE_PAGE_COVERAGE = 0.15


@dataclass
class PageSignal:
    page_number: int  # 1-based, original PDF page number
    char_count: int
    word_count: int
    text_density: float
    image_coverage: float  # 0.0-1.0, fraction of page area covered by embedded images
    extraction_quality: float  # 0.0-1.0, fraction of extracted chars that look like real text
    layout_multi_column: bool  # a persistent column gutter with lines on both sides
    layout_table_dense: bool  # a ruled table covering a non-trivial fraction of the page
    classification: str  # PAGE_TEXT | PAGE_SCANNED | PAGE_AMBIGUOUS


def _extraction_quality(text: str) -> float:
    stripped = text.strip()
    if not stripped:
        return 0.0
    bad = len(_ORDINARY_CHARS_RE.findall(stripped))
    return 1.0 - (bad / len(stripped))


def _image_coverage(page) -> float:
    page_area = (page.width or 0.0) * (page.height or 0.0)
    if page_area <= 0:
        return 0.0
    covered = 0.0
    for img in page.images:
        width = max(0.0, img.get("x1", 0.0) - img.get("x0", 0.0))
        height = max(0.0, img.get("bottom", 0.0) - img.get("top", 0.0))
        covered += width * height
    return min(covered / page_area, 1.0)


def _group_words_into_lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        for line in lines:
            if abs(line[0]["top"] - w["top"]) <= _LINE_Y_TOLERANCE:
                line.append(w)
                break
        else:
            lines.append([w])
    return lines


def _detect_multi_column(page, words: list[dict]) -> bool:
    """A persistent internal vertical gutter with a meaningful number of
    lines sitting entirely to its left and entirely to its right — the
    local parser (`local_pdf.py`) has no concept of columns at all and
    would read such a page's lines across both columns in one pass.

    Known limitation, empirically confirmed during development: a
    page-wide gutter search like this reliably catches a page that is
    columnar *throughout*, but a page mixing a genuinely 2-column text
    block with an unrelated single-column block elsewhere (e.g. a product
    list) can wash out the gutter when aggregated over the whole page —
    several row-local alternatives (checking for an anomalously large gap
    within same-row word groups, with or without a gap-position-consistency
    check) were also tried and rejected, because they fire just as
    strongly on a genuine single-column page containing a wide two-cell
    *unruled* table (exactly the FSSAI regulation's own limit table shape)
    as they do on real column-merged prose — no purely geometric signal
    tried distinguished the two reliably enough to risk the FSSAI
    regulation's classification. This function is deliberately kept
    conservative (page-wide gutter only) so it cannot regress that
    document; it will still miss some real multi-column pages whose
    columns don't span most of the page (see KNOWN_ISSUES.md)."""
    page_width = page.width or 0.0
    if not words or page_width <= 0:
        return False

    lines = _group_words_into_lines(words)
    if len(lines) < MIN_LINES_PER_COLUMN * 2:
        return False

    bin_width = page_width / COLUMN_GAP_BINS
    counts = [0] * COLUMN_GAP_BINS
    for w in words:
        mid = (w["x0"] + w["x1"]) / 2
        idx = min(max(int(mid / bin_width), 0), COLUMN_GAP_BINS - 1)
        counts[idx] += 1

    nonzero = [i for i, c in enumerate(counts) if c > 0]
    if not nonzero:
        return False
    left_edge, right_edge = min(nonzero), max(nonzero)

    best_len, best_start, best_end, run_start = 0, None, None, None
    for i in range(left_edge, right_edge + 1):
        if counts[i] == 0:
            if run_start is None:
                run_start = i
            if i - run_start + 1 > best_len:
                best_len, best_start, best_end = i - run_start + 1, run_start, i
        else:
            run_start = None
    if best_len == 0 or (best_len / COLUMN_GAP_BINS) < MIN_COLUMN_GUTTER_FRACTION:
        return False

    # The gutter's real edges are the actual word extents on either side of
    # the empty bin run — not the bin-index boundaries themselves, which
    # can fall mid-word (a word's midpoint can land in one bin while its
    # own x0/x1 extends into a neighbouring "empty" bin).
    bin_boundary_lo = best_start * bin_width
    bin_boundary_hi = (best_end + 1) * bin_width
    left_words = [w for w in words if (w["x0"] + w["x1"]) / 2 < bin_boundary_lo]
    right_words = [w for w in words if (w["x0"] + w["x1"]) / 2 >= bin_boundary_hi]
    if not left_words or not right_words:
        return False
    gutter_x0 = max(w["x1"] for w in left_words)
    gutter_x1 = min(w["x0"] for w in right_words)
    if gutter_x1 <= gutter_x0:
        return False

    left_only = right_only = 0
    for line in lines:
        x0 = min(w["x0"] for w in line)
        x1 = max(w["x1"] for w in line)
        if x1 <= gutter_x0:
            left_only += 1
        elif x0 >= gutter_x1:
            right_only += 1
    return left_only >= MIN_LINES_PER_COLUMN and right_only >= MIN_LINES_PER_COLUMN


def _detect_table_dense(page) -> bool:
    page_area = (page.width or 0.0) * (page.height or 0.0)
    if page_area <= 0:
        return False
    for t in page.find_tables():  # default (ruling-line) strategy, matching local_pdf.py's own table extraction
        data = t.extract()
        if not data:
            continue
        n_rows = len(data)
        n_cols = max((len(r) for r in data), default=0)
        if n_rows < MIN_TABLE_ROWS or n_cols < MIN_TABLE_COLS:
            continue
        x0, top, x1, bottom = t.bbox
        table_area = max(0.0, x1 - x0) * max(0.0, bottom - top)
        if (table_area / page_area) >= MIN_TABLE_PAGE_COVERAGE:
            return True
    return False


def _classify(char_count: int, word_count: int, density: float, image_coverage: float, quality: float,
              layout_multi_column: bool = False, layout_table_dense: bool = False) -> str:
    is_confidently_text = (
        char_count >= MIN_TEXT_CHARS
        and word_count >= MIN_TEXT_WORDS
        and density >= MIN_TEXT_DENSITY
        and quality >= MIN_EXTRACTION_QUALITY
        and image_coverage < MAX_TEXT_PAGE_IMAGE_COVERAGE
        and not layout_multi_column
        and not layout_table_dense
    )
    if is_confidently_text:
        return PAGE_TEXT
    if char_count <= MAX_SCANNED_CHARS or image_coverage >= SCANNED_IMAGE_COVERAGE:
        return PAGE_SCANNED
    return PAGE_AMBIGUOUS


def classify_page(page) -> PageSignal:
    """Classifies a single already-open `pdfplumber.Page`."""
    text = page.extract_text() or ""
    char_count = len(text.strip())
    words = page.extract_words()
    word_count = len(words)
    page_area = (page.width or 0.0) * (page.height or 0.0)
    density = (char_count / page_area) if page_area else 0.0
    image_coverage = _image_coverage(page)
    quality = _extraction_quality(text)
    layout_multi_column = _detect_multi_column(page, words)
    layout_table_dense = _detect_table_dense(page)
    classification = _classify(char_count, word_count, density, image_coverage, quality,
                                layout_multi_column, layout_table_dense)
    return PageSignal(
        page_number=page.page_number, char_count=char_count, word_count=word_count,
        text_density=density, image_coverage=image_coverage, extraction_quality=quality,
        layout_multi_column=layout_multi_column, layout_table_dense=layout_table_dense,
        classification=classification,
    )


def classify_pages(file_path: str) -> list[PageSignal]:
    """Cheap, local, no-OCR pass over every page of a PDF."""
    with pdfplumber.open(file_path) as pdf:
        return [classify_page(page) for page in pdf.pages]
