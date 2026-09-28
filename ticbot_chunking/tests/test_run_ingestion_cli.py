"""End-to-end test for scripts/run_ingestion.py, run in-process (calling
`main()` directly) against a **mocked** Azure Blob Storage account —
`azure.storage.blob.BlobServiceClient` is patched, never a live call.

Azure Blob Storage is the sole ingestion source (no local-directory
fallback exists anymore), so this is the only way to exercise the CLI
safely without either hitting a real account or being unable to test it at
all. Uses the real all-text sample PDF (routes to the local parser, no
Document Intelligence call) plus a synthetic Excel workbook served as
"blob content" — a genuine, safe, Azure-free run of the whole CLI.
"""
from __future__ import annotations

import importlib
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from openpyxl import Workbook

from ticbot_chunking.scripts import run_ingestion

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REAL_SAMPLES_DIR = PROJECT_ROOT / "upadated_data_sgs"
REAL_PDF = REAL_SAMPLES_DIR / "Contaminants_Regulations_pages_1-5.pdf"


def _require_real_sample():
    if not REAL_PDF.exists():
        pytest.skip(f"real sample PDF not present: {REAL_PDF}")


def _reload_ingestion_stack():
    import ticbot_chunking.config as config
    importlib.reload(config)
    import ticbot_chunking.storage.blob_store as blob_store
    importlib.reload(blob_store)
    import ticbot_chunking.ingestion.source as source
    importlib.reload(source)
    return source


@pytest.fixture
def configured_blob_store(monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://fakeaccount.blob.core.windows.net")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "fake-key")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "sample-pdf-data,sample-xlsx-data")
    _reload_ingestion_stack()
    try:
        yield
    finally:
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "")
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "")
        _reload_ingestion_stack()


def _fake_blob(name: str, size: int):
    return SimpleNamespace(name=name, size=size, content_settings=None, last_modified=None)


def _xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Category", "Service"])
    for i in range(1, 10):
        ws.append([f"Category {i}", f"Service description {i} with extra detail for token count."])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _mock_blob_service(pdf_blobs: dict[str, bytes], xlsx_blobs: dict[str, bytes]):
    """Starts a patch of `azure.storage.blob.BlobServiceClient` so the
    "sample-pdf-data" / "sample-xlsx-data" containers list and serve
    exactly the given {blob_name: content_bytes} maps — standing in for a
    real Blob Storage account. Returns (patcher, pdf_container_mock,
    xlsx_container_mock) so callers can also assert on which blobs were
    actually downloaded."""
    pdf_container = MagicMock()
    pdf_container.list_blobs.return_value = [_fake_blob(n, len(b)) for n, b in pdf_blobs.items()]
    pdf_container.download_blob.side_effect = lambda name: SimpleNamespace(readall=lambda: pdf_blobs[name])

    xlsx_container = MagicMock()
    xlsx_container.list_blobs.return_value = [_fake_blob(n, len(b)) for n, b in xlsx_blobs.items()]
    xlsx_container.download_blob.side_effect = lambda name: SimpleNamespace(readall=lambda: xlsx_blobs[name])

    mock_cls_patch = patch("azure.storage.blob.BlobServiceClient")
    mock_cls = mock_cls_patch.start()
    mock_cls.return_value.get_container_client.side_effect = lambda name: {
        "sample-pdf-data": pdf_container, "sample-xlsx-data": xlsx_container,
    }[name]
    return mock_cls_patch, pdf_container, xlsx_container


def test_ingestion_cli_end_to_end_from_blob_storage(configured_blob_store, tmp_path, monkeypatch, capsys):
    _require_real_sample()
    output_dir = tmp_path / "experiments"
    pdf_bytes = {REAL_PDF.name: REAL_PDF.read_bytes()}
    xlsx_bytes = {"capability.xlsx": _xlsx_bytes()}
    mock_patch, _, _ = _mock_blob_service(pdf_bytes, xlsx_bytes)
    try:
        monkeypatch.setattr(sys, "argv", ["run_ingestion", "--output-dir", str(output_dir)])
        run_ingestion.main()
    finally:
        mock_patch.stop()

    out = capsys.readouterr().out
    assert "Source: blob" in out  # never "local_fallback" — no such source_kind exists anymore

    for strategy in ("fixed", "recursive", "structure_aware", "hybrid"):
        chunks_path = output_dir / strategy / "chunks.jsonl"
        assert chunks_path.exists()
        with open(chunks_path) as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert rows, f"{strategy} produced no chunks"
        for row in rows:
            assert row["metadata"].get("parser") is not None, row
            # source_file is the blob provenance path ("<container>/<blob name>"),
            # never a local filesystem path or the ingestion temp dir.
            assert row["metadata"]["source_file"].startswith(("sample-pdf-data/", "sample-xlsx-data/")), row
            assert "ticbot_ingestion_" not in row["metadata"]["source_file"]

    with open(output_dir / "processing_report.json") as f:
        report = json.load(f)

    assert report["stats"]["source_kind"] == "blob"
    assert report["stats"]["total_files"] == 2
    assert report["stats"]["processing_failures"] == 0
    assert report["failures"] == []

    report_md = (output_dir / "processing_report.md").read_text()
    assert "# TICBot Ingestion Processing Report" in report_md
    assert "Azure Blob Storage" in report_md
    assert "local directory" not in report_md.lower()  # no local-fallback disclosure exists anymore


def test_ingestion_cli_exclude_file_skips_it_without_downloading_it(configured_blob_store, tmp_path, monkeypatch):
    _require_real_sample()
    output_dir = tmp_path / "experiments"
    pdf_bytes = {REAL_PDF.name: REAL_PDF.read_bytes()}
    xlsx_bytes = {"capability.xlsx": _xlsx_bytes()}
    mock_patch, _, xlsx_container = _mock_blob_service(pdf_bytes, xlsx_bytes)
    try:
        monkeypatch.setattr(sys, "argv", [
            "run_ingestion", "--output-dir", str(output_dir), "--exclude-file", "capability.xlsx",
        ])
        run_ingestion.main()
    finally:
        mock_patch.stop()

    # The excluded blob is never fetched — exclusion happens before any
    # download, not just before chunking.
    xlsx_container.download_blob.assert_not_called()

    with open(output_dir / "processing_report.json") as f:
        report = json.load(f)

    assert report["stats"]["excluded_file_count"] == 1
    assert report["stats"]["excluded_files"] == ["sample-xlsx-data/capability.xlsx"]
    assert report["stats"]["total_files"] == 1  # only the PDF was considered
    assert report["stats"]["source_kind"] == "blob"

    report_md = (output_dir / "processing_report.md").read_text()
    assert "## Intentionally excluded files" in report_md
    assert "NOT fully validated" in report_md
    assert "capability.xlsx" in report_md

    for strategy in ("fixed", "recursive", "structure_aware", "hybrid"):
        with open(output_dir / strategy / "chunks.jsonl") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        assert all("capability.xlsx" not in row["metadata"]["source_file"] for row in rows)


def test_ingestion_cli_reports_a_failure_without_aborting_the_whole_run(configured_blob_store, tmp_path, monkeypatch):
    output_dir = tmp_path / "experiments"
    # No PDF blobs at all this run; one broken "xlsx" blob (not a real
    # workbook) alongside one good one, both served from Blob Storage.
    pdf_bytes: dict[str, bytes] = {}
    xlsx_bytes = {"broken.xlsx": b"not a real xlsx file", "good.xlsx": _xlsx_bytes()}
    mock_patch, _, _ = _mock_blob_service(pdf_bytes, xlsx_bytes)
    try:
        monkeypatch.setattr(sys, "argv", ["run_ingestion", "--output-dir", str(output_dir)])
        run_ingestion.main()
    finally:
        mock_patch.stop()

    with open(output_dir / "processing_report.json") as f:
        report = json.load(f)

    assert report["stats"]["source_kind"] == "blob"
    assert report["stats"]["processing_failures"] == 1
    failure = report["failures"][0]
    assert failure["filename"] == "sample-xlsx-data/broken.xlsx"
    assert set(failure.keys()) == {"filename", "reason", "parser_attempted", "error", "retry_recommended"}
    assert report["stats"]["successfully_ingested"] == 1  # good.xlsx still got processed


def test_ingestion_cli_fails_clearly_when_blob_storage_is_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "")
    _reload_ingestion_stack()

    output_dir = tmp_path / "experiments"
    monkeypatch.setattr(sys, "argv", ["run_ingestion", "--output-dir", str(output_dir)])

    with pytest.raises(RuntimeError, match="not configured"):
        run_ingestion.main()

    # No local fallback was attempted, and nothing was written.
    assert not output_dir.exists()
