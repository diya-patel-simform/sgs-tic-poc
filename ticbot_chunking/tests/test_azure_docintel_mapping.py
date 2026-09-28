"""Tests for the pure IR-mapping logic in parsers/azure_docintel.py
(`_to_layout_document`), using lightweight stand-ins for the Document
Intelligence SDK's response objects so no Azure credentials or network
access are needed."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ticbot_chunking.parsers.azure_docintel import (
    _pages_param,
    _strip_markdown_syntax,
    _to_layout_document,
    parse_pdf_pages,
)


def _span(offset):
    return [SimpleNamespace(offset=offset)]


def _region(page_number=1, polygon=None):
    return SimpleNamespace(page_number=page_number, polygon=polygon or [0, 0, 10, 0, 10, 10, 0, 10])


def test_table_attaches_to_nearest_preceding_paragraph_even_when_one_paragraph_has_no_spans():
    # Paragraph B has no spans (offset -1), which used to make the
    # preceding-paragraph search break early and mis-attach the table to A
    # instead of the true nearest preceding paragraph, C.
    para_a = SimpleNamespace(content="A", role="text", bounding_regions=[_region()], spans=_span(0))
    para_b = SimpleNamespace(content="B", role="text", bounding_regions=[_region()], spans=None)
    para_c = SimpleNamespace(content="C", role="text", bounding_regions=[_region()], spans=_span(10))

    table = SimpleNamespace(
        row_count=1, column_count=1, cells=[], spans=_span(20),
    )

    result = SimpleNamespace(
        pages=[SimpleNamespace(page_number=1, width=0, height=0)],
        paragraphs=[para_a, para_b, para_c],
        tables=[table],
        figures=[],
    )

    doc = _to_layout_document(result, source_file="test.pdf")

    assert doc.tables[0].preceding_paragraph_index == 2  # index of para_c, not para_a


def test_figures_pick_up_overlapping_inline_text():
    para = SimpleNamespace(
        content="Step 1", role="text",
        bounding_regions=[_region(page_number=1, polygon=[0, 0, 10, 0, 10, 10, 0, 10])],
        spans=_span(0),
    )
    figure = SimpleNamespace(
        caption=None,
        bounding_regions=[_region(page_number=1, polygon=[0, 0, 20, 0, 20, 20, 0, 20])],
    )
    result = SimpleNamespace(
        pages=[SimpleNamespace(page_number=1, width=0, height=0)],
        paragraphs=[para],
        tables=[],
        figures=[figure],
    )

    doc = _to_layout_document(result, source_file="test.pdf")

    assert doc.figures[0].inline_text_fragments == ["Step 1"]


# ---------------------------------------------------------------------------
# _pages_param / parse_pdf_pages — the page-selection entry point used by
# the page-level mixed-PDF router (parsers/page_router.py) so only the
# pages that need OCR are sent to Document Intelligence.
# ---------------------------------------------------------------------------

def test_pages_param_compresses_contiguous_and_isolated_pages():
    assert _pages_param({41, 81, 82}) == "41,81-82"


def test_pages_param_single_contiguous_range():
    assert _pages_param({1, 2, 3}) == "1-3"


def test_pages_param_single_page():
    assert _pages_param({5}) == "5"


def test_pages_param_all_isolated_pages():
    assert _pages_param({1, 3, 5}) == "1,3,5"


def test_parse_pdf_pages_sends_only_the_requested_pages_and_tags_them_scanned():
    fake_result = SimpleNamespace(
        pages=[SimpleNamespace(page_number=41, width=100, height=100)],
        paragraphs=[], tables=[], figures=[],
    )
    with patch("ticbot_chunking.parsers.azure_docintel.DOCINTEL") as mock_config, \
         patch("azure.ai.documentintelligence.DocumentIntelligenceClient") as mock_client_cls, \
         patch("builtins.open"):
        mock_config.is_configured = True
        mock_config.endpoint = "https://fake.example.com"
        mock_config.key = "fake-key"
        mock_client_cls.return_value.begin_analyze_document.return_value.result.return_value = fake_result

        doc = parse_pdf_pages("fake.pdf", {41})

        call_kwargs = mock_client_cls.return_value.begin_analyze_document.call_args.kwargs
        assert call_kwargs["pages"] == "41"

    assert doc.pages[0].is_scanned is True  # defaults to tagging every requested page as scanned


def test_parse_pdf_pages_rejects_empty_page_set():
    with pytest.raises(ValueError):
        parse_pdf_pages("fake.pdf", set())


# ---------------------------------------------------------------------------
# _strip_markdown_syntax — Document Intelligence is called with
# output_content_format="markdown", which can leak markdown syntax into a
# paragraph's own content; untested in production so far (this path has
# never run against real data), so covered directly here against synthetic
# markdown-laden content strings.
# ---------------------------------------------------------------------------

def test_strip_markdown_syntax_removes_heading_markers():
    assert _strip_markdown_syntax("## Chapter 2") == "Chapter 2"


def test_strip_markdown_syntax_removes_bold_and_italic_emphasis():
    assert _strip_markdown_syntax("This is **bold** and *italic* and _also italic_.") == (
        "This is bold and italic and also italic."
    )


def test_strip_markdown_syntax_drops_a_stray_table_row_line():
    assert _strip_markdown_syntax("Intro line\n| Col A | Col B |\nMore text") == "Intro line\nMore text"


def test_strip_markdown_syntax_leaves_ordinary_text_unchanged():
    text = "Ordinary paragraph text with no markdown syntax at all."
    assert _strip_markdown_syntax(text) == text


def test_strip_markdown_syntax_handles_empty_string():
    assert _strip_markdown_syntax("") == ""


def test_to_layout_document_strips_markdown_from_paragraph_content():
    fake_para = SimpleNamespace(
        content="**Bold heading**", role="title",
        bounding_regions=[SimpleNamespace(page_number=1, polygon=[0, 0, 10, 0, 10, 10, 0, 10])],
        spans=_span(0),
    )
    result = SimpleNamespace(
        pages=[SimpleNamespace(page_number=1, width=100, height=100)],
        paragraphs=[fake_para], tables=[], figures=[],
    )
    doc = _to_layout_document(result, source_file="fake.pdf")
    assert doc.paragraphs[0].text == "Bold heading"
