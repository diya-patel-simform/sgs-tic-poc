"""Tests for the blob-storage ingestion command
(ticbot_chunking/scripts/ingest_from_blob.py), which downloads blobs and
hands them to the existing local pipeline unchanged.

`ingest_from_blob.py` imports the `blob_store` module (not individual
functions) so that reloading `blob_store` in the fixture below is enough —
no cascading reload of `ingest_from_blob` itself is needed.
"""
from __future__ import annotations

import importlib
import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from openpyxl import Workbook


def _reload_config_and_blob_store():
    import ticbot_chunking.config as config
    importlib.reload(config)
    import ticbot_chunking.storage.blob_store as blob_store
    importlib.reload(blob_store)
    return blob_store


@pytest.fixture
def configured_blob_store(monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://fakeaccount.blob.core.windows.net")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "fake-key")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "ticbot-docs")
    blob_store = _reload_config_and_blob_store()
    try:
        yield blob_store
    finally:
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "")
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "")
        _reload_config_and_blob_store()


def _fake_blob(name: str, size: int = 100):
    return SimpleNamespace(name=name, size=size, content_settings=None, last_modified=None)


def _real_xlsx_bytes() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Capability"
    ws.append(["Category", "Service"])
    ws.append(["Food", "Pesticide residue testing"])
    ws.append(["Food", "Heavy metals testing"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_ingest_reads_one_excel_blob_end_to_end_and_sets_source_file_to_blob_path(configured_blob_store):
    from ticbot_chunking.scripts import ingest_from_blob

    mock_container = MagicMock()
    mock_container.list_blobs.return_value = [
        _fake_blob("Food and Multi lab testing capability/Food Testing capability.xlsx"),
    ]
    mock_stream = MagicMock()
    mock_stream.readall.return_value = _real_xlsx_bytes()
    mock_container.download_blob.return_value = mock_stream

    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.return_value = mock_container
        chunks, skipped = ingest_from_blob.ingest()

    assert skipped == []
    assert chunks
    assert all(
        c.metadata.source_file == "ticbot-docs/Food and Multi lab testing capability/Food Testing capability.xlsx"
        for c in chunks
    )


def test_ingest_reads_one_pdf_blob_and_calls_process_pdf(configured_blob_store):
    from ticbot_chunking.scripts import ingest_from_blob

    mock_container = MagicMock()
    mock_container.list_blobs.return_value = [_fake_blob("FSSAI Regulation/Contaminants_Regulations.pdf")]
    mock_stream = MagicMock()
    mock_stream.readall.return_value = b"%PDF-1.4 fake pdf bytes"
    mock_container.download_blob.return_value = mock_stream

    from ticbot_chunking.metadata.schema import Chunk, ChunkMetadata

    fake_chunk = Chunk(
        text="[Regulation] fake",
        metadata=ChunkMetadata(chunk_type="text", doc_type="regulation", source_file="ignored-local-name.pdf", tokens=10),
    )

    with patch("azure.storage.blob.BlobServiceClient") as mock_cls, \
         patch("ticbot_chunking.scripts.ingest_from_blob.process_pdf", return_value=[fake_chunk]) as mock_process_pdf:
        mock_cls.return_value.get_container_client.return_value = mock_container
        chunks, skipped = ingest_from_blob.ingest()

    assert skipped == []
    mock_process_pdf.assert_called_once()
    called_path = mock_process_pdf.call_args[0][0]
    assert called_path.endswith("Contaminants_Regulations.pdf")
    assert len(chunks) == 1
    assert chunks[0].metadata.source_file == "ticbot-docs/FSSAI Regulation/Contaminants_Regulations.pdf"


def test_ingest_skips_a_pdf_blob_when_document_intelligence_is_not_configured(configured_blob_store):
    # Simulates process_pdf's real "not configured" RuntimeError (see
    # parsers/azure_docintel.py) via a direct patch, rather than depending on
    # AZURE_DOCINTEL_* actually being unset in the environment running the
    # tests — this environment may have real Document Intelligence
    # credentials configured for other purposes, and a PDF blob's bytes here
    # are fake, so letting a real call through would either hit the live
    # service unintentionally or make this test's outcome environment-
    # dependent. Either way, ingest() must catch the error per-blob rather
    # than aborting the whole run.
    from ticbot_chunking.scripts import ingest_from_blob

    mock_container = MagicMock()
    mock_container.list_blobs.return_value = [_fake_blob("FSSAI Regulation/Contaminants_Regulations.pdf")]
    mock_stream = MagicMock()
    mock_stream.readall.return_value = b"%PDF-1.4 fake pdf bytes"
    mock_container.download_blob.return_value = mock_stream

    not_configured_error = RuntimeError(
        "Azure Document Intelligence is not configured. Set AZURE_DOCINTEL_ENDPOINT and "
        "AZURE_DOCINTEL_KEY (see .env.example) before parsing PDFs."
    )

    with patch("azure.storage.blob.BlobServiceClient") as mock_cls, \
         patch("ticbot_chunking.scripts.ingest_from_blob.process_pdf", side_effect=not_configured_error):
        mock_cls.return_value.get_container_client.return_value = mock_container
        chunks, skipped = ingest_from_blob.ingest()

    assert chunks == []
    assert len(skipped) == 1
    name, err = skipped[0]
    assert name == "ticbot-docs/FSSAI Regulation/Contaminants_Regulations.pdf"
    assert "RuntimeError" in err
    assert "not configured" in err


def test_ingest_respects_prefix_and_limit(configured_blob_store):
    from ticbot_chunking.scripts import ingest_from_blob

    mock_container = MagicMock()
    mock_container.list_blobs.return_value = [
        _fake_blob("Food and Multi lab testing capability/a.xlsx"),
        _fake_blob("Food and Multi lab testing capability/b.xlsx"),
    ]
    mock_stream = MagicMock()
    mock_stream.readall.return_value = _real_xlsx_bytes()
    mock_container.download_blob.return_value = mock_stream

    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.return_value = mock_container
        chunks, skipped = ingest_from_blob.ingest(prefix="Food and Multi lab testing capability/", limit=1)

    mock_container.list_blobs.assert_called_once_with(name_starts_with="Food and Multi lab testing capability/")
    assert skipped == []
    assert {c.metadata.source_file for c in chunks} == {"ticbot-docs/Food and Multi lab testing capability/a.xlsx"}
