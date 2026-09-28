"""Tests for parsers/router.py — automatic parser selection between the
local PDF parser and Azure Document Intelligence, and that both paths
produce the same LayoutDocument IR shape.

Azure Document Intelligence itself is always mocked here (never a live
call) — these tests confirm *routing*, not Document Intelligence's own
parsing behavior (covered separately in test_azure_docintel_mapping.py).
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ticbot_chunking.parsers.ir import LayoutDocument
from ticbot_chunking.parsers.router import describe_routing, parse_pdf_auto

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
    path = tmp_path / "blank.pdf"
    doc.save(str(path))
    return str(path)


def test_text_based_pdf_routes_to_local_parser_and_never_touches_azure():
    _require_real_sample(REAL_REGULATION_PDF)
    with patch("ticbot_chunking.parsers.router.azure_docintel.parse_pdf") as mock_di:
        doc = parse_pdf_auto(str(REAL_REGULATION_PDF))

    mock_di.assert_not_called()
    assert isinstance(doc, LayoutDocument)
    assert doc.page_count == 5
    assert len(doc.paragraphs) > 0


def test_pdf_with_no_usable_text_routes_to_document_intelligence(blank_pdf):
    fake_result = SimpleNamespace(pages=[], paragraphs=[], tables=[], figures=[])
    with patch("ticbot_chunking.parsers.router.local_pdf.parse_pdf_local") as mock_local, \
         patch("ticbot_chunking.parsers.azure_docintel.DOCINTEL") as mock_config, \
         patch("azure.ai.documentintelligence.DocumentIntelligenceClient") as mock_client_cls:
        mock_config.is_configured = True
        mock_config.endpoint = "https://fake.example.com"
        mock_config.key = "fake-key"
        mock_client_cls.return_value.begin_analyze_document.return_value.result.return_value = fake_result

        doc = parse_pdf_auto(blank_pdf)

    mock_local.assert_not_called()
    assert isinstance(doc, LayoutDocument)


def test_pdf_with_no_usable_text_marks_every_page_scanned_automatically(blank_pdf):
    # No manual scanned-page flag is passed anywhere in this call chain —
    # is_scanned is derived purely from the automatic text-layer detection.
    fake_pages = [SimpleNamespace(page_number=1, width=200, height=200)]
    fake_result = SimpleNamespace(pages=fake_pages, paragraphs=[], tables=[], figures=[])
    with patch("ticbot_chunking.parsers.router.local_pdf.parse_pdf_local"), \
         patch("ticbot_chunking.parsers.azure_docintel.DOCINTEL") as mock_config, \
         patch("azure.ai.documentintelligence.DocumentIntelligenceClient") as mock_client_cls:
        mock_config.is_configured = True
        mock_config.endpoint = "https://fake.example.com"
        mock_config.key = "fake-key"
        mock_client_cls.return_value.begin_analyze_document.return_value.result.return_value = fake_result

        doc = parse_pdf_auto(blank_pdf)

    assert doc.pages[0].is_scanned is True


def test_describe_routing_reports_local_for_real_text_pdf():
    _require_real_sample(REAL_REGULATION_PDF)
    parser_name, stats = describe_routing(str(REAL_REGULATION_PDF))
    assert parser_name == "local"
    assert stats.has_usable_text_layer is True


def test_describe_routing_reports_document_intelligence_for_blank_pdf(blank_pdf):
    parser_name, stats = describe_routing(blank_pdf)
    assert parser_name == "azure_document_intelligence"
    assert stats.has_usable_text_layer is False


def test_both_parser_paths_return_the_same_ir_shape():
    """Structural compatibility check: whichever parser ran, downstream
    chunkers see the exact same LayoutDocument shape — same dataclasses,
    same field types — so no adapter is needed."""
    from ticbot_chunking.parsers.azure_docintel import _to_layout_document
    from ticbot_chunking.parsers.local_pdf import parse_pdf_local

    _require_real_sample(REAL_REGULATION_PDF)
    local_doc = parse_pdf_local(str(REAL_REGULATION_PDF))

    fake_para = SimpleNamespace(content="Hello", role="text", bounding_regions=[], spans=[SimpleNamespace(offset=0)])
    fake_result = SimpleNamespace(
        pages=[SimpleNamespace(page_number=1, width=100, height=100)],
        paragraphs=[fake_para], tables=[], figures=[],
    )
    di_doc = _to_layout_document(fake_result, source_file="fake.pdf")

    for doc in (local_doc, di_doc):
        assert isinstance(doc, LayoutDocument)
        assert isinstance(doc.source_file, str)
        assert isinstance(doc.pages, list)
        assert isinstance(doc.paragraphs, list)
        assert isinstance(doc.tables, list)
        assert isinstance(doc.figures, list)
        for p in doc.paragraphs:
            assert isinstance(p.text, str)
            assert isinstance(p.role, str)
            assert isinstance(p.page_numbers, list)
