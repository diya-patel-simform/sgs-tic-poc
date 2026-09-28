"""Tests for ticbot_chunking/ingestion/orchestrator.py — per-document
ingestion (classification, parser selection, provenance recording). Uses
the real sample PDF in upadated_data_sgs/ (routes to the local parser, no
Azure call) and a synthetic Excel workbook.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from ticbot_chunking.ingestion.orchestrator import (
    PARSER_EXCEL,
    PARSER_LOCAL_PDF,
    _classify_retry,
    ingest_document,
)

REAL_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "upadated_data_sgs"
REAL_REGULATION_PDF = REAL_SAMPLES_DIR / "Contaminants_Regulations_pages_1-5.pdf"


def _require_real_sample(path: Path):
    if not path.exists():
        pytest.skip(f"real sample PDF not present: {path}")


def test_ingest_document_excel(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["A", "B"])
    ws.append([1, 2])
    ws2 = wb.create_sheet("Sheet2")
    ws2.append(["X"])
    path = tmp_path / "book.xlsx"
    wb.save(path)

    doc = ingest_document("Some Folder/book.xlsx", path)

    assert doc.kind == "excel"
    assert doc.parser == PARSER_EXCEL
    assert doc.source_name == "Some Folder/book.xlsx"
    assert doc.filename == "book.xlsx"
    assert doc.sheets == ["Sheet1", "Sheet2"]
    assert doc.parsed.source_file == "Some Folder/book.xlsx"
    assert doc.parsed.local_path == str(path)
    assert doc.parsed.kind == "excel"


def test_ingest_document_pdf_routes_to_local_parser_and_preserves_provenance():
    _require_real_sample(REAL_REGULATION_PDF)

    doc = ingest_document("FSSAI Regulation/Contaminants_Regulations.pdf", REAL_REGULATION_PDF)

    assert doc.kind == "pdf"
    assert doc.parser == PARSER_LOCAL_PDF
    assert doc.text_classification == "text-based"
    assert doc.text_layer_fraction == 1.0
    assert doc.total_pages == 5
    assert doc.source_name == "FSSAI Regulation/Contaminants_Regulations.pdf"
    assert doc.filename == "Contaminants_Regulations.pdf"
    # the blob path is preserved as the ParsedDoc's source_file, distinct
    # from local_path (the actual downloaded file on disk)
    assert doc.parsed.source_file == "FSSAI Regulation/Contaminants_Regulations.pdf"
    assert doc.parsed.local_path == str(REAL_REGULATION_PDF)
    assert doc.parsed.layout_doc is not None
    assert doc.parsed.layout_doc.page_count == 5


def test_classify_retry_true_for_config_and_connectivity_errors():
    assert _classify_retry(RuntimeError("Azure Document Intelligence is not configured.")) is True
    assert _classify_retry(RuntimeError("Connection timeout while reaching the service")) is True
    assert _classify_retry(RuntimeError("Request was throttled, please retry")) is True


def test_classify_retry_false_for_content_errors():
    assert _classify_retry(ValueError("could not read PDF structure: corrupt cross-reference table")) is False
