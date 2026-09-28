"""Tests for the local (pdfplumber) PDF parser and its automatic
text-layer detection. Uses the real sample PDFs already in this repo
(`upadated_data_sgs/`) for the "has a usable text layer" cases — per the
project's standing rule not to fabricate parsing results, no synthetic
text content is invented here. A genuinely blank PDF (built with
pypdfium2, zero text, no fabricated content) stands in for "no usable text
layer at all".
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ticbot_chunking.parsers.ir import ROLE_PAGE_HEADER, ROLE_PAGE_NUMBER, ROLE_SECTION_HEADING, ROLE_TITLE
from ticbot_chunking.parsers.local_pdf import (
    TextLayerStats,
    _is_heading_line,
    inspect_text_layer,
    parse_pdf_local,
    parse_pdf_local_pages,
)
from ticbot_chunking.tests.pdf_builders import add_multi_block_page, new_pdf, save_pdf

REAL_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "upadated_data_sgs"
REAL_REGULATION_PDF = REAL_SAMPLES_DIR / "Contaminants_Regulations_pages_1-5.pdf"


def _require_real_sample(path: Path):
    if not path.exists():
        pytest.skip(f"real sample PDF not present: {path}")


@pytest.fixture
def blank_pdf(tmp_path) -> str:
    pdfium = pytest.importorskip("pypdfium2")
    doc = pdfium.PdfDocument.new()
    doc.new_page(200, 200)
    doc.new_page(200, 200)
    path = tmp_path / "blank.pdf"
    doc.save(str(path))
    return str(path)


# ---------------------------------------------------------------------------
# TextLayerStats — pure dataclass logic, no PDF I/O needed
# ---------------------------------------------------------------------------

def test_text_layer_stats_fraction_and_usability():
    stats = TextLayerStats(total_pages=10, pages_with_text={1, 2, 3})
    assert stats.fraction_with_text == 0.3
    assert stats.has_usable_text_layer is True  # 0.3 >= MIN_TEXT_FRACTION (0.10)


def test_text_layer_stats_below_threshold_is_not_usable():
    stats = TextLayerStats(total_pages=20, pages_with_text={1})  # 5%
    assert stats.has_usable_text_layer is False


def test_text_layer_stats_zero_pages_with_text():
    stats = TextLayerStats(total_pages=5, pages_with_text=set())
    assert stats.fraction_with_text == 0.0
    assert stats.has_usable_text_layer is False


def test_text_layer_stats_empty_document_does_not_crash():
    stats = TextLayerStats(total_pages=0, pages_with_text=set())
    assert stats.fraction_with_text == 0.0
    assert stats.has_usable_text_layer is False


# ---------------------------------------------------------------------------
# inspect_text_layer against real files
# ---------------------------------------------------------------------------

def test_inspect_text_layer_detects_real_text_based_pdf():
    _require_real_sample(REAL_REGULATION_PDF)
    stats = inspect_text_layer(str(REAL_REGULATION_PDF))
    assert stats.total_pages == 5
    assert stats.has_usable_text_layer is True
    assert len(stats.pages_with_text) == 5  # every page of this real sample has real embedded text


def test_inspect_text_layer_detects_pdf_with_no_usable_text(blank_pdf):
    stats = inspect_text_layer(blank_pdf)
    assert stats.total_pages == 2
    assert stats.pages_with_text == set()
    assert stats.has_usable_text_layer is False


# ---------------------------------------------------------------------------
# _is_heading_line — the textual heading-detection heuristic
# ---------------------------------------------------------------------------

def test_is_heading_line_matches_chapter():
    assert _is_heading_line("CHAPTER 2")
    assert _is_heading_line("CHAPTER 2 – Contaminants, Toxins And Residues")


def test_is_heading_line_matches_short_dotted_numbering():
    assert _is_heading_line("2.3.1: Restriction on the use of insecticides.")
    assert _is_heading_line("2.1 : METAL CONTAMINANTS")
    assert _is_heading_line("1.1: Short title and commencement-")


def test_is_heading_line_rejects_bare_single_level_number():
    # A plain numbered list/table item, not a heading — this is real
    # content from the sample regulation PDF's insecticide table.
    assert not _is_heading_line("2. Copper (i) Beverages: Soft drinks excluding concentrates")


def test_is_heading_line_rejects_long_numbered_clause():
    # Found against the real sample: a body clause that happens to share
    # the "x.y.z:" numbering convention with genuine headings, but is a
    # full sentence, not a short heading label.
    assert not _is_heading_line(
        "1.1.2: These regulations shall come into force on or after 5th August, 2011"
    )
    assert not _is_heading_line(
        "1.2.1: In these regulations unless the context otherwise requires:"
    )


def test_is_heading_line_matches_annexure():
    assert _is_heading_line("Annexure A: Scope of Accreditation")


def test_is_heading_line_rejects_ordinary_prose():
    assert not _is_heading_line("The quick brown fox jumps over the lazy dog in the park today.")


# ---------------------------------------------------------------------------
# parse_pdf_local end-to-end against a real sample
# ---------------------------------------------------------------------------

def test_parse_pdf_local_produces_layout_document_with_structure():
    _require_real_sample(REAL_REGULATION_PDF)
    doc = parse_pdf_local(str(REAL_REGULATION_PDF))

    assert doc.source_file == str(REAL_REGULATION_PDF)
    assert doc.page_count == 5
    assert all(not p.is_scanned for p in doc.pages)  # routed here because it IS text-based
    assert len(doc.paragraphs) > 0

    titles = [p for p in doc.paragraphs if p.role == ROLE_TITLE]
    headings = [p for p in doc.paragraphs if p.role == ROLE_SECTION_HEADING]
    # ROLE_TITLE is assigned once per physical PAGE (the first heading-like
    # paragraph on it), not once for the whole document — this is what lets
    # a per-page title become its own hierarchy level for other document
    # types (see chunkers/section_numbering.py's `ingest_top_level`). The
    # real ministry letterhead on page 1 is always one of them; other pages
    # get one too whenever a heading happens to open right at the top of a
    # new page (real for this sample: section 2.2 starts exactly on page 5).
    assert len(titles) >= 1
    assert titles[0].text.startswith("MINISTRY OF HEALTH")
    assert any("CHAPTER" in h.text for h in headings)  # real chapter headings detected

    for p in doc.paragraphs:
        assert p.bounding_boxes  # every paragraph carries position info
        assert p.bounding_boxes[0].page_number in range(1, 6)


# ---------------------------------------------------------------------------
# Per-page titles, fuzzy header/footer matching, and bare page-number
# detection — synthetic multi-page fixtures (pdf_builders), since these
# specifically need multiple distinct, precisely-positioned text blocks per
# page that no real sample in this repo happens to exercise cleanly.
# ---------------------------------------------------------------------------

def _two_page_doc_with_header_and_page_number():
    doc = new_pdf()
    body = "This is enough real body text on the page to read as ordinary paragraph prose here."
    add_multi_block_page(doc, [
        ("SERVICE CATALOG 1", 20, 15),         # running header, page number embedded
        ("Page One Title", 20, 60, 18.0),       # this page's own title-like heading (larger font)
        (body, 20, 200),
        ("3", 20, 390),                          # bare printed page number, footer zone
    ])
    add_multi_block_page(doc, [
        ("SERVICE CATALOG 2", 20, 15),         # same header, different embedded number
        ("Page Two Title", 20, 60, 18.0),       # a DIFFERENT per-page title (larger font)
        (body, 20, 200),
        ("4/20", 20, 390),                       # bare printed page label, footer zone
    ])
    return doc


def test_running_header_with_changing_page_number_is_still_recognized(tmp_path):
    doc = _two_page_doc_with_header_and_page_number()
    path = save_pdf(doc, tmp_path / "header_pagenum.pdf")

    result = parse_pdf_local(path)
    headers = [p for p in result.paragraphs if p.role == ROLE_PAGE_HEADER]
    # Byte-identical matching alone would never catch this (each page's
    # header text differs by its embedded page number) — fuzzy matching
    # (trailing number stripped before comparing) must still recognize both
    # as the same running header.
    assert len(headers) == 2
    assert {p.bounding_boxes[0].page_number for p in headers} == {1, 2}


def test_bare_page_number_and_printed_label_are_tagged_and_dropped_from_body(tmp_path):
    doc = _two_page_doc_with_header_and_page_number()
    path = save_pdf(doc, tmp_path / "page_numbers.pdf")

    result = parse_pdf_local(path)
    page_numbers = {p.text: p.role for p in result.paragraphs if p.text in ("3", "4/20")}
    assert page_numbers == {"3": ROLE_PAGE_NUMBER, "4/20": ROLE_PAGE_NUMBER}

    body_texts = [p.text for p in result.paragraphs if p.role not in (ROLE_PAGE_HEADER, ROLE_PAGE_NUMBER)]
    assert not any(t in ("3", "4/20") for t in body_texts)


def test_each_page_gets_its_own_title_not_just_the_first_page(tmp_path):
    doc = _two_page_doc_with_header_and_page_number()
    path = save_pdf(doc, tmp_path / "per_page_titles.pdf")

    result = parse_pdf_local(path)
    titles = {p.bounding_boxes[0].page_number: p.text for p in result.paragraphs if p.role == ROLE_TITLE}
    assert titles == {1: "Page One Title", 2: "Page Two Title"}


def test_parse_pdf_local_on_blank_pdf_returns_empty_but_well_formed_document(blank_pdf):
    doc = parse_pdf_local(blank_pdf)
    assert doc.page_count == 2
    assert doc.paragraphs == []
    assert doc.tables == []


# ---------------------------------------------------------------------------
# parse_pdf_local_pages — the page-subset entry point used by the page-level
# mixed-PDF router (parsers/page_router.py) to parse only a document's TEXT
# pages, preserving their original page numbers.
# ---------------------------------------------------------------------------

def test_parse_pdf_local_pages_only_parses_the_requested_pages_and_keeps_original_numbers():
    _require_real_sample(REAL_REGULATION_PDF)
    doc = parse_pdf_local_pages(str(REAL_REGULATION_PDF), {2, 4})

    assert doc.page_count == 2
    assert [p.page_number for p in doc.pages] == [2, 4]
    assert len(doc.paragraphs) > 0
    assert {p.bounding_boxes[0].page_number for p in doc.paragraphs} == {2, 4}


def test_parse_pdf_local_pages_matches_full_parse_for_the_same_page():
    # Parsing page 2 alone should produce the same paragraph text as
    # parsing the whole document and filtering to page 2 — page subsetting
    # must not change what's extracted, only which pages are included.
    _require_real_sample(REAL_REGULATION_PDF)
    full_doc = parse_pdf_local(str(REAL_REGULATION_PDF))
    subset_doc = parse_pdf_local_pages(str(REAL_REGULATION_PDF), {2})

    full_page_2_text = [p.text for p in full_doc.paragraphs if p.bounding_boxes[0].page_number == 2]
    subset_text = [p.text for p in subset_doc.paragraphs]
    assert subset_text == full_page_2_text


def test_parse_pdf_local_pages_rejects_empty_page_set():
    _require_real_sample(REAL_REGULATION_PDF)
    with pytest.raises(ValueError):
        parse_pdf_local_pages(str(REAL_REGULATION_PDF), set())
