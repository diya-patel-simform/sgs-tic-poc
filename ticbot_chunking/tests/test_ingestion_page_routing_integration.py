"""Integration tests for page-level PDF routing wired into the actual
ingestion entry points — `ingestion.orchestrator.ingest_document` (used by
`scripts/run_ingestion.py`, the Blob-Storage-backed pipeline with the
processing report) and `pipeline.process_pdf` (used by
`scripts/run_pipeline.py` and `scripts/ingest_from_blob.py`).

Unlike `test_page_router.py` (unit tests for `parsers/page_router.py` in
isolation), these tests exercise the real pipeline/orchestrator functions
themselves, confirming the integration actually took effect: local parser
gets only TEXT pages, Document Intelligence gets only SCANNED/AMBIGUOUS
pages (and is never sent the whole document just because one page is
scanned), the merged output is what downstream chunking receives, and
existing all-text-PDF behavior is unchanged. Document Intelligence is
always mocked here — never a live call.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ticbot_chunking.ingestion.orchestrator import (
    PARSER_DOCUMENT_INTELLIGENCE,
    PARSER_LOCAL_PDF,
    PARSER_MIXED,
    ingest_document,
)
from ticbot_chunking.pipeline import process_pdf
from ticbot_chunking.tests.pdf_builders import add_blank_page, add_text_page, new_pdf, save_pdf

REAL_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "upadated_data_sgs"
REAL_REGULATION_PDF = REAL_SAMPLES_DIR / "Contaminants_Regulations_pages_1-5.pdf"


def _require_real_sample(path: Path):
    if not path.exists():
        pytest.skip(f"real sample PDF not present: {path}")


def _region(page_number):
    return SimpleNamespace(page_number=page_number, polygon=[0, 0, 10, 0, 10, 10, 0, 10])


def _span(offset):
    return [SimpleNamespace(offset=offset)]


def _fake_azure_result(page_numbers: list[int]):
    pages = [SimpleNamespace(page_number=n, width=300, height=400) for n in page_numbers]
    paragraphs = [
        SimpleNamespace(content=f"OCR text for page {n}", role="text", bounding_regions=[_region(n)], spans=_span(i))
        for i, n in enumerate(page_numbers)
    ]
    return SimpleNamespace(pages=pages, paragraphs=paragraphs, tables=[], figures=[])


class _RecordingClient:
    def __init__(self, fake_result):
        self.fake_result = fake_result
        self.calls: list[dict] = []

    def begin_analyze_document(self, *args, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(result=lambda: self.fake_result)


def _mixed_pdf(tmp_path) -> str:
    doc_builder = new_pdf()
    add_text_page(doc_builder, word_count=40)   # page 1: text
    add_blank_page(doc_builder)                  # page 2: scanned
    add_text_page(doc_builder, word_count=40)   # page 3: text
    return save_pdf(doc_builder, tmp_path / "mixed.pdf")


def _all_scanned_pdf(tmp_path) -> str:
    doc_builder = new_pdf()
    add_blank_page(doc_builder)
    add_blank_page(doc_builder)
    add_blank_page(doc_builder)
    return save_pdf(doc_builder, tmp_path / "all_scanned.pdf")


# ---------------------------------------------------------------------------
# ingestion.orchestrator.ingest_document — the real Blob-Storage ingestion path
# ---------------------------------------------------------------------------

def test_orchestrator_all_text_pdf_behavior_is_unchanged():
    _require_real_sample(REAL_REGULATION_PDF)
    with patch("ticbot_chunking.parsers.page_router.azure_docintel.parse_pdf_pages") as mock_di:
        doc = ingest_document("FSSAI Regulation/Contaminants_Regulations.pdf", REAL_REGULATION_PDF)

    mock_di.assert_not_called()
    assert doc.parser == PARSER_LOCAL_PDF
    assert doc.text_classification == "text-based"
    assert doc.text_layer_fraction == 1.0
    assert doc.total_pages == 5


def test_orchestrator_mixed_pdf_routes_each_page_to_the_right_parser_and_merges(tmp_path):
    path = _mixed_pdf(tmp_path)
    client = _RecordingClient(_fake_azure_result([2]))

    with patch("ticbot_chunking.parsers.page_router.azure_docintel._require_client", return_value=client):
        doc = ingest_document("Folder/mixed.pdf", Path(path))

    # Only the scanned page was ever sent to Document Intelligence — not
    # the whole 3-page document.
    assert len(client.calls) == 1
    assert client.calls[0]["pages"] == "2"

    # Provenance/report metadata correctly reflects that both parsers ran.
    assert doc.parser == PARSER_MIXED
    assert doc.text_classification == "mixed (page-level routed)"
    assert doc.total_pages == 3
    assert doc.text_layer_fraction == pytest.approx(2 / 3)

    layout_doc = doc.parsed.layout_doc
    # Every original page represented exactly once, correctly ordered.
    assert [p.page_number for p in layout_doc.pages] == [1, 2, 3]
    assert [p.is_scanned for p in layout_doc.pages] == [False, True, False]

    # source_file metadata preserved (the real blob path passed to ParsedDoc,
    # not the local temp path) — the orchestration-layer contract already
    # relied on elsewhere (see scripts/run_ingestion.py's force-correction).
    assert doc.parsed.source_file == "Folder/mixed.pdf"

    # Text pages came from the local parser (real filler text), the scanned
    # page came from the mocked Document Intelligence result — no
    # duplication, no dropped page.
    para_by_page = {p.bounding_boxes[0].page_number: p.text for p in layout_doc.paragraphs}
    assert len(layout_doc.paragraphs) == 3
    assert "word0" in para_by_page[1]
    assert para_by_page[2] == "OCR text for page 2"
    assert "word0" in para_by_page[3]


def test_orchestrator_all_scanned_pdf_uses_one_compact_document_intelligence_call(tmp_path):
    path = _all_scanned_pdf(tmp_path)
    client = _RecordingClient(_fake_azure_result([1, 2, 3]))

    with patch("ticbot_chunking.parsers.page_router.azure_docintel._require_client", return_value=client):
        doc = ingest_document("Folder/all_scanned.pdf", Path(path))

    assert len(client.calls) == 1
    assert client.calls[0]["pages"] == "1-3"  # one compact call, not per-page, not omitted
    assert doc.parser == PARSER_DOCUMENT_INTELLIGENCE
    assert doc.text_classification == "no usable text layer"
    assert doc.text_layer_fraction == 0.0
    assert doc.total_pages == 3


# ---------------------------------------------------------------------------
# pipeline.process_pdf — the local-directory / ingest_from_blob path, and
# confirmation that the merged document actually flows through the existing,
# unmodified chunking strategy that owns it (chunk_brochure by default).
# ---------------------------------------------------------------------------

def test_pipeline_process_pdf_all_text_never_calls_document_intelligence():
    _require_real_sample(REAL_REGULATION_PDF)
    with patch("ticbot_chunking.parsers.page_router.azure_docintel.parse_pdf_pages") as mock_di:
        chunks = process_pdf(str(REAL_REGULATION_PDF))

    mock_di.assert_not_called()
    assert len(chunks) > 0


def test_pipeline_process_pdf_mixed_pdf_reaches_chunking_with_content_from_every_page(tmp_path):
    path = _mixed_pdf(tmp_path)
    client = _RecordingClient(_fake_azure_result([2]))

    with patch("ticbot_chunking.parsers.page_router.azure_docintel._require_client", return_value=client):
        chunks = process_pdf(path)

    assert len(client.calls) == 1
    assert client.calls[0]["pages"] == "2"  # never the whole 3-page document

    # Downstream chunking (chunk_brochure, since this filename doesn't match
    # any specific doc-type pattern) ran unmodified on the merged document
    # and produced chunks covering content from both parsers.
    assert len(chunks) > 0
    all_text = "\n".join(c.text for c in chunks)
    assert "word0" in all_text  # from the local-parsed text pages
    assert "OCR text for page 2" in all_text  # from the Document-Intelligence-parsed page
