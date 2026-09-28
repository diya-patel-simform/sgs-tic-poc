"""Local PDF parsing (pdfplumber) for text-based PDFs, and the automatic
text-layer detection used to route between this parser and Azure Document
Intelligence (see `parsers/router.py`).

Produces the exact same `LayoutDocument` IR as `parsers/azure_docintel.py`,
so every chunker downstream is unchanged and doesn't know which parser ran.

Table detection deliberately uses only pdfplumber's ruling-line-based
strategy (its default), not the text-alignment strategy — the latter is
prone to mis-segmenting ordinary paragraph text as garbled table cells on
whitespace-aligned (non-ruled) government/legal PDFs, which is exactly the
shape of the real FSSAI regulation sample in this project. An un-ruled
table therefore comes through as plain paragraph text via this parser
rather than as a `Table` — a real trade-off against Azure Document
Intelligence's ML-based layout model, and preferable to fabricating a
table structure that isn't really there.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import pdfplumber

from ticbot_chunking.chunkers.section_numbering import ANNEXURE_RE, CHAPTER_RE
from ticbot_chunking.parsers.ir import (
    BoundingBox,
    Figure,
    LayoutDocument,
    Page,
    Paragraph,
    ROLE_PAGE_FOOTER,
    ROLE_PAGE_HEADER,
    ROLE_PAGE_NUMBER,
    ROLE_SECTION_HEADING,
    ROLE_TEXT,
    ROLE_TITLE,
    Table,
    TableCell,
)

# A page with fewer non-whitespace characters than this is treated as
# having no usable text layer for that page.
MIN_CHARS_PER_PAGE = 20

# A document is routed to the local parser once at least this fraction of
# its pages have a usable text layer. Below it, the document is treated as
# "no usable text layer" (mostly/entirely scanned) and routed to Document
# Intelligence instead — chosen low (not a simple majority) so that a
# document that's overwhelmingly text-based with a handful of scanned
# inserts (e.g. one scanned certificate page in an otherwise text-based
# multi-page scope document) still gets the cheaper local parse; see the
# "remaining limitations" note in the project README for the trade-off
# this implies for those minority scanned pages.
MIN_TEXT_FRACTION = 0.10

HEADING_MAX_WORDS = 15

# Multi-level dotted numbering ("2.3" / "2.3.1"), followed by a short
# title — e.g. "2.3.1: Restriction on the use of insecticides.". A bare
# single-level number ("2.") is deliberately excluded: in the real
# FSSAI-style regulation sample this pattern is what an ordinary numbered
# list/table item looks like ("2. Copper (i) Beverages: ..."), and treating
# every leading digit as a heading would badly over-fire. The title part is
# also capped at DOTTED_HEADING_MAX_TITLE_WORDS: a genuine heading label is
# short ("Restriction on the use of insecticides", 6 words); a numbered
# clause of body text that happens to share the same "x.y.z:" numbering
# convention runs on much longer ("These regulations shall come into force
# on or after...", 12+ words) — this word-count cap is what tells them
# apart, since the two are otherwise visually and lexically identical in a
# document with no font-based heading styling at all.
DOTTED_HEADING_MAX_TITLE_WORDS = 7
_DOTTED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){1,3})\s*[:.]?\s+(\S.{0,80})$")
LINE_Y_TOLERANCE = 3.0          # points; words within this of each other's `top` are the same line
PARAGRAPH_GAP_FACTOR = 1.6      # a vertical gap bigger than this * median line height starts a new paragraph
HEADER_FOOTER_ZONE_FRACTION = 0.12  # top/bottom 12% of the page counts as the header/footer zone

# A standalone printed page number/label in the header/footer zone, e.g.
# "3", "(3)", "4/20" — recognized by shape alone (it necessarily differs
# page to page, so it can never be caught by the repeated-text check below)
# and dropped from chunk text the same way headers/footers are.
_PAGE_NUMBER_ONLY_RE = re.compile(r"^\(?\d{1,4}\)?(\s*/\s*\d{1,4})?$")

# A header/footer that embeds a changing page number or short date
# ("SERVICE CATALOG 4", "Page 3") would never match byte-for-byte across
# pages — stripped before the repeated-text check so it still matches as
# the same running header/footer.
_TRAILING_NUMBER_RE = re.compile(r"\s*\(?\d{1,4}\)?\s*(/\s*\d{1,4}\s*)?$")


def _normalize_for_repetition(text: str) -> str:
    return _TRAILING_NUMBER_RE.sub("", text).strip()


@dataclass
class TextLayerStats:
    total_pages: int
    pages_with_text: set[int]  # 1-based page numbers with a usable text layer

    @property
    def fraction_with_text(self) -> float:
        return len(self.pages_with_text) / self.total_pages if self.total_pages else 0.0

    @property
    def has_usable_text_layer(self) -> bool:
        return self.total_pages > 0 and self.fraction_with_text >= MIN_TEXT_FRACTION


def inspect_text_layer(file_path: str) -> TextLayerStats:
    """Cheap, local, no-OCR pass: does each page have real embedded text?"""
    with pdfplumber.open(file_path) as pdf:
        pages_with_text = set()
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if len(text.strip()) >= MIN_CHARS_PER_PAGE:
                pages_with_text.add(i)
        return TextLayerStats(total_pages=len(pdf.pages), pages_with_text=pages_with_text)


@dataclass
class _Line:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    bold: bool


@dataclass
class _RawParagraph:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    bold: bool
    page_number: int


def _group_words_into_lines(words: list[dict]) -> list[_Line]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        placed = False
        for line in lines:
            if abs(line[0]["top"] - w["top"]) <= LINE_Y_TOLERANCE:
                line.append(w)
                placed = True
                break
        if not placed:
            lines.append([w])

    out = []
    for line in lines:
        line = sorted(line, key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in line)
        sizes = [w.get("size", 0.0) for w in line]
        bold_frac = sum(1 for w in line if "bold" in (w.get("fontname") or "").lower()) / len(line)
        out.append(_Line(
            text=text, x0=min(w["x0"] for w in line), x1=max(w["x1"] for w in line),
            top=min(w["top"] for w in line), bottom=max(w["bottom"] for w in line),
            size=sum(sizes) / len(sizes) if sizes else 0.0, bold=bold_frac >= 0.5,
        ))
    return sorted(out, key=lambda l: l.top)


_WORD_RE = re.compile(r"\S+")


def _is_heading_line(text: str) -> bool:
    """Textual heading signal, independent of font styling — some real PDFs
    (the FSSAI regulation sample among them) convey structure purely
    through text convention ("CHAPTER 2", "2.3.1: ...") with headings set
    in the exact same font/size as body text, where a font-based heuristic
    alone finds nothing."""
    text = text.strip()
    if len(text) > 100:
        return False
    if CHAPTER_RE.match(text) or ANNEXURE_RE.match(text):
        return True
    m = _DOTTED_HEADING_RE.match(text)
    if not m:
        return False
    title_words = _WORD_RE.findall(m.group(2))
    return len(title_words) <= DOTTED_HEADING_MAX_TITLE_WORDS


def _group_lines_into_paragraphs(lines: list[_Line], page_number: int) -> list[_RawParagraph]:
    if not lines:
        return []
    heights = [l.bottom - l.top for l in lines if l.bottom > l.top]
    median_height = sorted(heights)[len(heights) // 2] if heights else 10.0

    paragraphs: list[_RawParagraph] = []
    current: list[_Line] = [lines[0]]
    for prev, line in zip(lines, lines[1:]):
        gap = line.top - prev.bottom
        same_style = abs(line.size - prev.size) < 0.5 and line.bold == prev.bold
        # A heading line (by text convention) is always isolated into its
        # own paragraph — otherwise it silently merges into the body text
        # that follows it, since it usually looks the same as that body
        # text stylistically (see _is_heading_line's docstring).
        forced_break = _is_heading_line(line.text) or _is_heading_line(prev.text)
        if forced_break or gap > median_height * PARAGRAPH_GAP_FACTOR or not same_style:
            paragraphs.append(_merge_paragraph(current, page_number))
            current = [line]
        else:
            current.append(line)
    paragraphs.append(_merge_paragraph(current, page_number))
    return paragraphs


def _merge_paragraph(lines: list[_Line], page_number: int) -> _RawParagraph:
    text = "\n".join(l.text for l in lines)
    sizes = [l.size for l in lines]
    return _RawParagraph(
        text=text, x0=min(l.x0 for l in lines), x1=max(l.x1 for l in lines),
        top=min(l.top for l in lines), bottom=max(l.bottom for l in lines),
        size=sum(sizes) / len(sizes) if sizes else 0.0,
        bold=all(l.bold for l in lines), page_number=page_number,
    )


def _classify_roles(raw_paragraphs: list[_RawParagraph], page_heights: dict[int, float]) -> list[Paragraph]:
    body_key = Counter((round(p.size), p.bold) for p in raw_paragraphs).most_common(1)
    body_size, body_bold = body_key[0][0] if body_key else (0.0, False)

    # Repeated short text across >= 2 pages, near the top/bottom of its
    # page, is treated as a running page header/footer. Matched on
    # normalized text (trailing page number/date stripped) so a header or
    # footer that embeds a changing page number still matches across pages
    # as the same running header/footer, not a one-off paragraph.
    text_page_counts = Counter(_normalize_for_repetition(p.text.strip()) for p in raw_paragraphs)
    # A page's own title is the first heading-like paragraph *on that
    # page* (tracked per page, not once for the whole document) — this is
    # what lets a brochure's per-page title (e.g. "Crop Science") become
    # its own hierarchy level (see chunkers/section_numbering.py's
    # `ingest_top_level` and chunkers/brochure.py's per-page-title walk).
    # The document's own overall title still comes from page 1's title-role
    # paragraph, same as before — see experiments/common.py:document_title().
    title_assigned_pages: set[int] = set()

    paragraphs: list[Paragraph] = []
    for p in raw_paragraphs:
        text = p.text.strip()
        if not text:
            continue
        n_words = len(_WORD_RE.findall(text))
        page_height = page_heights.get(p.page_number, 0.0) or 1.0
        near_top = p.top <= page_height * HEADER_FOOTER_ZONE_FRACTION
        near_bottom = p.bottom >= page_height * (1 - HEADER_FOOTER_ZONE_FRACTION)
        in_header_footer_zone = near_top or near_bottom
        normalized = _normalize_for_repetition(text)
        repeated = bool(normalized) and text_page_counts[normalized] >= 2

        role = ROLE_TEXT
        if in_header_footer_zone and _PAGE_NUMBER_ONLY_RE.match(text):
            role = ROLE_PAGE_NUMBER
        elif repeated and n_words <= HEADING_MAX_WORDS and in_header_footer_zone:
            role = ROLE_PAGE_HEADER if near_top else ROLE_PAGE_FOOTER
        else:
            # Textual convention (CHAPTER n / dotted numbering / Annexure)
            # is checked first since it catches real documents where
            # headings aren't visually distinguished by font at all; the
            # font-based signal (larger size, or bold where body isn't)
            # remains as a fallback for documents that DO style headings.
            is_heading_like = _is_heading_line(text) or (
                n_words <= HEADING_MAX_WORDS and (round(p.size) > body_size or (p.bold and not body_bold))
            )
            if is_heading_like:
                if p.page_number not in title_assigned_pages:
                    role = ROLE_TITLE
                    title_assigned_pages.add(p.page_number)
                else:
                    role = ROLE_SECTION_HEADING

        box = BoundingBox(page_number=p.page_number, x=p.x0, y=p.top, width=p.x1 - p.x0, height=p.bottom - p.top)
        paragraphs.append(Paragraph(text=text, role=role, bounding_boxes=[box]))

    return paragraphs


def _extract_tables(pdf, paragraphs: list[Paragraph], page_numbers: set[int] | None = None) -> list[Table]:
    tables: list[Table] = []
    for page in pdf.pages:
        if page_numbers is not None and page.page_number not in page_numbers:
            continue
        for pt in page.find_tables():  # default (ruling-line) strategy only — see module docstring
            data = pt.extract()
            if not data or not any(any((c or "").strip() for c in row) for row in data):
                continue
            cells = []
            for r, row in enumerate(data):
                for c, value in enumerate(row):
                    cells.append(TableCell(
                        row_index=r, column_index=c, content=(value or "").strip(),
                        kind="columnHeader" if r == 0 else None, page_number=page.page_number,
                    ))
            table_top = pt.bbox[1]
            preceding_idx = None
            for i, para in enumerate(paragraphs):
                pb = para.bounding_boxes[0] if para.bounding_boxes else None
                if pb and pb.page_number == page.page_number and pb.y < table_top:
                    preceding_idx = i
                elif pb and pb.page_number > page.page_number:
                    break
            tables.append(Table(
                row_count=len(data), column_count=max((len(r) for r in data), default=0), cells=cells,
                page_numbers=[page.page_number], preceding_paragraph_index=preceding_idx,
            ))
    return tables


def _extract_figures(pdf, page_numbers: set[int] | None = None) -> list[Figure]:
    figures = []
    for page in pdf.pages:
        if page_numbers is not None and page.page_number not in page_numbers:
            continue
        for img in page.images:
            box = BoundingBox(
                page_number=page.page_number, x=img.get("x0", 0.0), y=img.get("top", 0.0),
                width=img.get("x1", 0.0) - img.get("x0", 0.0), height=img.get("bottom", 0.0) - img.get("top", 0.0),
            )
            # pdfplumber doesn't associate a caption or nearby text with an
            # image the way Document Intelligence's figure detection does —
            # figures from this parser carry position only, no inline text.
            figures.append(Figure(caption=None, page_number=page.page_number, bounding_box=box,
                                   inline_text_fragments=[]))
    return figures


def parse_pdf_local(file_path: str) -> LayoutDocument:
    """Parses a text-based PDF entirely locally (no Azure call)."""
    return _parse_pdf_local(file_path, page_numbers=None)


def parse_pdf_local_pages(file_path: str, page_numbers: set[int]) -> LayoutDocument:
    """Parses only the given 1-based page numbers locally, preserving their
    original page numbers on every `Page`/`Paragraph`/`Table`/`Figure`
    produced (no renumbering) — the local-parser side of the page-level
    mixed-PDF router (`parsers/page_router.py`), which sends a text-based
    PDF's TEXT pages here and its SCANNED/AMBIGUOUS pages to
    `azure_docintel.parse_pdf_pages` instead of routing the whole document
    to one parser or the other."""
    if not page_numbers:
        raise ValueError("parse_pdf_local_pages requires at least one page number")
    return _parse_pdf_local(file_path, page_numbers=set(page_numbers))


def _parse_pdf_local(file_path: str, page_numbers: set[int] | None) -> LayoutDocument:
    with pdfplumber.open(file_path) as pdf:
        selected = [(i, p) for i, p in enumerate(pdf.pages, start=1)
                    if page_numbers is None or i in page_numbers]
        pages = [Page(page_number=i, width=p.width or 0.0, height=p.height or 0.0, is_scanned=False)
                 for i, p in selected]
        page_heights = {pg.page_number: pg.height for pg in pages}
        selected_numbers = {i for i, _ in selected}

        raw_paragraphs: list[_RawParagraph] = []
        for i, page in selected:
            words = page.extract_words(extra_attrs=["size", "fontname"])
            lines = _group_words_into_lines(words)
            raw_paragraphs.extend(_group_lines_into_paragraphs(lines, i))

        paragraphs = _classify_roles(raw_paragraphs, page_heights)
        tables = _extract_tables(pdf, paragraphs, page_numbers=selected_numbers if page_numbers is not None else None)
        figures = _extract_figures(pdf, page_numbers=selected_numbers if page_numbers is not None else None)

    return LayoutDocument(source_file=file_path, pages=pages, paragraphs=paragraphs, tables=tables, figures=figures)
