"""Tests for parsers/page_router.py — page-level routing and merging for
mixed text/scanned PDFs. This is the fix for the "mixed text/scanned PDFs
route as a whole document, not per page" item in KNOWN_ISSUES.md: a PDF
must not be sent to Document Intelligence as a whole just because one page
is scanned, and Document Intelligence must only ever be called with the
specific pages that need it (via its `pages=` selection).

Document Intelligence is always mocked here (never a live call) — these
tests confirm *routing and merging*, not Document Intelligence's own
response-mapping logic (covered separately in test_azure_docintel_mapping.py).

Six scenarios are covered end to end, per the page-router spec:
  1. All-text PDF            -> test_all_text_pdf_*
  2. All-scanned PDF         -> test_all_scanned_pdf_*
  3. Mixed text/scanned/text -> test_mixed_text_scanned_text_pdf_*
  4. Multiple scanned pages  -> test_multiple_non_contiguous_scanned_pages_*
  5. Ambiguous page          -> test_ambiguous_page_*
  6. Table/image-heavy page  -> test_image_heavy_page_with_table_*
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ticbot_chunking.parsers.page_router import (
    PARSER_DOCUMENT_INTELLIGENCE,
    PARSER_LOCAL,
    parse_pdf_paged,
    plan_page_routing,
)
from ticbot_chunking.tests.pdf_builders import (
    add_blank_page,
    add_image_page,
    add_text_page,
    new_pdf,
    save_pdf,
)

REAL_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "upadated_data_sgs"
REAL_REGULATION_PDF = REAL_SAMPLES_DIR / "Contaminants_Regulations_pages_1-5.pdf"


def _require_real_sample(path: Path):
    if not path.exists():
        pytest.skip(f"real sample PDF not present: {path}")


def _region(page_number, polygon=None):
    return SimpleNamespace(page_number=page_number, polygon=polygon or [0, 0, 10, 0, 10, 10, 0, 10])


def _span(offset):
    return [SimpleNamespace(offset=offset)]


def _fake_azure_result(page_numbers: list[int], width=300, height=400, tables=None):
    """A minimal stand-in for an Azure Document Intelligence AnalyzeResult,
    with one clearly-tagged OCR paragraph per requested page — enough to
    prove which pages the mocked call actually covered and to trace each
    resulting paragraph back to Document Intelligence in assertions."""
    pages = [SimpleNamespace(page_number=n, width=width, height=height) for n in page_numbers]
    paragraphs = [
        SimpleNamespace(
            content=f"OCR text for page {n}", role="text",
            bounding_regions=[_region(n)], spans=_span(i),
        )
        for i, n in enumerate(page_numbers)
    ]
    return SimpleNamespace(pages=pages, paragraphs=paragraphs, tables=tables or [], figures=[])


class _RecordingClient:
    """Like `_patch_azure`'s inline stand-in, but records the `pages=` kwarg
    every call was made with, so tests can assert exactly which pages were
    sent to Document Intelligence."""

    def __init__(self, fake_result):
        self.fake_result = fake_result
        self.calls: list[dict] = []

    def begin_analyze_document(self, *args, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(result=lambda: self.fake_result)


# ---------------------------------------------------------------------------
# 1. All-text PDF — must never call Document Intelligence at all
# ---------------------------------------------------------------------------

def test_all_text_pdf_never_calls_document_intelligence():
    _require_real_sample(REAL_REGULATION_PDF)
    with patch("ticbot_chunking.parsers.page_router.azure_docintel.parse_pdf_pages") as mock_di:
        doc = parse_pdf_paged(str(REAL_REGULATION_PDF))

    mock_di.assert_not_called()
    assert doc.page_count == 5
    assert all(not p.is_scanned for p in doc.pages)


def test_all_text_pdf_routing_plan_sends_every_page_to_local_parser():
    _require_real_sample(REAL_REGULATION_PDF)
    plan = plan_page_routing(str(REAL_REGULATION_PDF))
    assert plan.text_pages == {1, 2, 3, 4, 5}
    assert plan.ocr_pages == set()
    assert all(plan.parser_for_page(n) == PARSER_LOCAL for n in range(1, 6))


def test_text_normalize_runs_exactly_once_on_the_all_local_path():
    _require_real_sample(REAL_REGULATION_PDF)
    with patch("ticbot_chunking.parsers.page_router.text_normalize.normalize_paragraphs") as mock_normalize:
        doc = parse_pdf_paged(str(REAL_REGULATION_PDF))

    mock_normalize.assert_called_once_with(doc.paragraphs)


def test_text_normalize_runs_exactly_once_on_the_merged_path(tmp_path):
    doc_builder = new_pdf()
    add_text_page(doc_builder, word_count=40)
    add_blank_page(doc_builder)
    path = save_pdf(doc_builder, tmp_path / "mixed_normalize.pdf")

    with patch("ticbot_chunking.parsers.page_router.azure_docintel._require_client",
               return_value=_RecordingClient(_fake_azure_result([2]))), \
         patch("ticbot_chunking.parsers.page_router.text_normalize.normalize_paragraphs") as mock_normalize:
        doc = parse_pdf_paged(path)

    mock_normalize.assert_called_once_with(doc.paragraphs)


# ---------------------------------------------------------------------------
# 2. All-scanned PDF — every page goes through Document Intelligence's page
#    selection (never the blind local parser), local parser never invoked
# ---------------------------------------------------------------------------

def test_all_scanned_pdf_sends_every_page_to_document_intelligence(tmp_path):
    doc_builder = new_pdf()
    add_blank_page(doc_builder)
    add_blank_page(doc_builder)
    add_blank_page(doc_builder)
    path = save_pdf(doc_builder, tmp_path / "all_scanned.pdf")

    client = _RecordingClient(_fake_azure_result([1, 2, 3]))
    with patch("ticbot_chunking.parsers.page_router.azure_docintel._require_client", return_value=client), \
         patch("ticbot_chunking.parsers.page_router.local_pdf.parse_pdf_local") as mock_local_whole, \
         patch("ticbot_chunking.parsers.page_router.local_pdf.parse_pdf_local_pages") as mock_local_pages:
        result = parse_pdf_paged(path)

    mock_local_whole.assert_not_called()
    mock_local_pages.assert_not_called()
    assert client.calls[0]["pages"] == "1-3"  # one call, contiguous range, not the whole doc "blindly"
    assert result.page_count == 3
    assert all(p.is_scanned for p in result.pages)
    assert [p.bounding_boxes[0].page_number for p in result.paragraphs] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 3. Mixed PDF: text -> scanned -> text
# ---------------------------------------------------------------------------

def test_mixed_text_scanned_text_pdf(tmp_path):
    doc_builder = new_pdf()
    add_text_page(doc_builder, word_count=40)   # page 1: text
    add_blank_page(doc_builder)                  # page 2: scanned
    add_text_page(doc_builder, word_count=40)   # page 3: text
    path = save_pdf(doc_builder, tmp_path / "mixed.pdf")

    client = _RecordingClient(_fake_azure_result([2]))
    with patch("ticbot_chunking.parsers.page_router.azure_docintel._require_client", return_value=client):
        result = parse_pdf_paged(path)

    # Only the scanned page was sent to Document Intelligence.
    assert client.calls[0]["pages"] == "2"

    # Every original page is represented exactly once.
    assert [p.page_number for p in result.pages] == [1, 2, 3]

    # Final ordering follows original page number, ascending.
    para_pages = [p.bounding_boxes[0].page_number for p in result.paragraphs]
    assert para_pages == sorted(para_pages)
    assert set(para_pages) == {1, 2, 3}

    # Text pages come from the local parser: real filler text, not the
    # "OCR text for page N" marker the fake Document Intelligence result
    # uses.
    page_1_text = next(p.text for p in result.paragraphs if p.bounding_boxes[0].page_number == 1)
    page_3_text = next(p.text for p in result.paragraphs if p.bounding_boxes[0].page_number == 3)
    assert "word0" in page_1_text
    assert "word0" in page_3_text

    # The scanned page comes from Document Intelligence.
    page_2_text = next(p.text for p in result.paragraphs if p.bounding_boxes[0].page_number == 2)
    assert page_2_text == "OCR text for page 2"

    # Metadata identifies the parser used for each page.
    plan = plan_page_routing(path)
    assert plan.parser_for_page(1) == PARSER_LOCAL
    assert plan.parser_for_page(2) == PARSER_DOCUMENT_INTELLIGENCE
    assert plan.parser_for_page(3) == PARSER_LOCAL
    assert [p.is_scanned for p in result.pages] == [False, True, False]

    assert result.source_file == path  # source_file metadata preserved


def test_mixed_pdf_does_not_duplicate_or_lose_content(tmp_path):
    doc_builder = new_pdf()
    add_text_page(doc_builder, word_count=40)
    add_blank_page(doc_builder)
    add_text_page(doc_builder, word_count=40)
    path = save_pdf(doc_builder, tmp_path / "mixed2.pdf")

    with patch("ticbot_chunking.parsers.page_router.azure_docintel._require_client",
               return_value=_RecordingClient(_fake_azure_result([2]))):
        result = parse_pdf_paged(path)

    # Exactly one paragraph per page in this fixture — no duplication, no
    # dropped page.
    assert len(result.paragraphs) == 3
    assert sorted(p.bounding_boxes[0].page_number for p in result.paragraphs) == [1, 2, 3]


# ---------------------------------------------------------------------------
# 4. Multiple (non-contiguous) scanned pages
# ---------------------------------------------------------------------------

def test_multiple_non_contiguous_scanned_pages_use_compact_page_selection(tmp_path):
    doc_builder = new_pdf()
    add_text_page(doc_builder, word_count=40)   # 1: text
    add_blank_page(doc_builder)                  # 2: scanned
    add_text_page(doc_builder, word_count=40)   # 3: text
    add_blank_page(doc_builder)                  # 4: scanned
    add_blank_page(doc_builder)                  # 5: scanned
    path = save_pdf(doc_builder, tmp_path / "multi_scanned.pdf")

    client = _RecordingClient(_fake_azure_result([2, 4, 5]))
    with patch("ticbot_chunking.parsers.page_router.azure_docintel._require_client", return_value=client):
        result = parse_pdf_paged(path)

    assert client.calls[0]["pages"] == "2,4-5"  # compressed selection, not "1-5"
    assert [p.page_number for p in result.pages] == [1, 2, 3, 4, 5]
    assert [p.is_scanned for p in result.pages] == [False, True, False, True, True]


# ---------------------------------------------------------------------------
# 5. Ambiguous page — routed to Document Intelligence, same as SCANNED
# ---------------------------------------------------------------------------

def test_ambiguous_page_routes_to_document_intelligence(tmp_path):
    doc_builder = new_pdf()
    add_text_page(doc_builder, word_count=40)   # page 1: confidently text
    add_text_page(doc_builder, word_count=5)    # page 2: ambiguous (sparse text)
    path = save_pdf(doc_builder, tmp_path / "ambiguous.pdf")

    plan = plan_page_routing(path)
    assert plan.signals[1].classification == "ambiguous"
    assert 2 in plan.ocr_pages
    assert 1 in plan.text_pages

    client = _RecordingClient(_fake_azure_result([2]))
    with patch("ticbot_chunking.parsers.page_router.azure_docintel._require_client", return_value=client):
        result = parse_pdf_paged(path)

    assert client.calls[0]["pages"] == "2"
    assert result.page_count == 2
    assert result.pages[1].is_scanned is True


# ---------------------------------------------------------------------------
# 6. Table/image-heavy page
# ---------------------------------------------------------------------------

def test_image_heavy_page_with_table_routes_to_document_intelligence_and_keeps_table(tmp_path):
    doc_builder = new_pdf()
    add_text_page(doc_builder, word_count=40)                                  # page 1: text
    add_image_page(doc_builder, image_coverage=0.95, caption_word_count=15)    # page 2: scanned (image-heavy)
    path = save_pdf(doc_builder, tmp_path / "image_heavy.pdf")

    fake_para = SimpleNamespace(
        content="Table caption", role="text", bounding_regions=[_region(2)], spans=_span(0),
    )
    fake_table = SimpleNamespace(
        row_count=2, column_count=2,
        cells=[SimpleNamespace(row_index=0, column_index=0, content="A", row_span=1, column_span=1,
                                kind="columnHeader", bounding_regions=[_region(2)])],
        spans=_span(10),
    )
    fake_result = SimpleNamespace(
        pages=[SimpleNamespace(page_number=2, width=300, height=400)],
        paragraphs=[fake_para], tables=[fake_table], figures=[],
    )

    client = _RecordingClient(fake_result)
    with patch("ticbot_chunking.parsers.page_router.azure_docintel._require_client", return_value=client):
        result = parse_pdf_paged(path)

    assert client.calls[0]["pages"] == "2"
    assert len(result.tables) == 1
    assert result.tables[0].page_numbers == [2]
    # The table's preceding-paragraph index was remapped onto the merged
    # paragraph list, not left pointing at Document Intelligence's own
    # (pre-merge) paragraph list.
    preceding = result.paragraphs[result.tables[0].preceding_paragraph_index]
    assert preceding.text == "Table caption"


# ---------------------------------------------------------------------------
# Cross-cutting: every original page represented exactly once, in every
# scenario that mixes both parsers.
# ---------------------------------------------------------------------------

def test_every_original_page_represented_exactly_once(tmp_path):
    doc_builder = new_pdf()
    add_text_page(doc_builder, word_count=40)
    add_blank_page(doc_builder)
    add_text_page(doc_builder, word_count=40)
    add_blank_page(doc_builder)
    path = save_pdf(doc_builder, tmp_path / "coverage_check.pdf")

    with patch("ticbot_chunking.parsers.page_router.azure_docintel._require_client",
               return_value=_RecordingClient(_fake_azure_result([2, 4]))):
        result = parse_pdf_paged(path)

    page_numbers = [p.page_number for p in result.pages]
    assert page_numbers == [1, 2, 3, 4]
    assert len(page_numbers) == len(set(page_numbers))  # no duplicates
