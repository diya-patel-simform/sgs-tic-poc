"""Tests for the Azure Blob Storage client (ticbot_chunking/storage/blob_store.py).

No real Azure Storage account is needed: `azure.storage.blob.BlobServiceClient`
is mocked at its source module, and credentials are supplied via monkeypatched
env vars. `config` and `blob_store` are reloaded around each test so the
`STORAGE` singleton (captured at import time, like the other Azure config
singletons) picks up the patched environment — mirroring the pattern already
used in test_config.py.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


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


def _fake_blob(name: str, size: int = 100, content_type: str | None = None):
    content_settings = SimpleNamespace(content_type=content_type) if content_type else None
    return SimpleNamespace(name=name, size=size, content_settings=content_settings, last_modified=None)


def test_raises_clear_error_when_credentials_missing(monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "")
    blob_store = _reload_config_and_blob_store()

    with pytest.raises(RuntimeError, match="not configured"):
        blob_store.list_blobs()
    with pytest.raises(RuntimeError, match="not configured"):
        blob_store.download_blob_bytes("anything.pdf")


def test_list_blobs_identifies_pdfs_and_excel_files(configured_blob_store):
    blob_store = configured_blob_store
    mock_container = MagicMock()
    mock_container.list_blobs.return_value = [
        _fake_blob("FSSAI Regulation/Contaminants_Regulations.pdf"),
        _fake_blob("Food and Multi lab testing capability/Food Testing capability.xlsx"),
        _fake_blob("Brochures/catalog.PDF"),  # extension matching should be case-insensitive
        _fake_blob("notes.txt"),
    ]
    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.return_value = mock_container
        blobs = blob_store.list_blobs()
        pdfs = blob_store.list_pdf_blobs()
        excels = blob_store.list_excel_blobs()

    assert len(blobs) == 4
    assert {b.name for b in pdfs} == {"FSSAI Regulation/Contaminants_Regulations.pdf", "Brochures/catalog.PDF"}
    assert {b.name for b in excels} == {"Food and Multi lab testing capability/Food Testing capability.xlsx"}
    assert not any(b.is_pdf or b.is_excel for b in blobs if b.name == "notes.txt")


def test_list_blobs_passes_prefix_through_to_the_container_client(configured_blob_store):
    blob_store = configured_blob_store
    mock_container = MagicMock()
    mock_container.list_blobs.return_value = []
    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.return_value = mock_container
        blob_store.list_blobs(prefix="FSSAI Regulation/")

    mock_container.list_blobs.assert_called_once_with(name_starts_with="FSSAI Regulation/")


def test_download_blob_to_file_reads_a_pdf_and_preserves_basename(configured_blob_store, tmp_path):
    blob_store = configured_blob_store
    mock_container = MagicMock()
    mock_stream = MagicMock()
    mock_stream.readall.return_value = b"%PDF-1.4 fake pdf bytes"
    mock_container.download_blob.return_value = mock_stream

    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.return_value = mock_container
        local_path = blob_store.download_blob_to_file("FSSAI Regulation/Contaminants_Regulations.pdf", tmp_path)

    mock_container.download_blob.assert_called_once_with("FSSAI Regulation/Contaminants_Regulations.pdf")
    assert local_path.name == "Contaminants_Regulations.pdf"
    assert local_path.read_bytes() == b"%PDF-1.4 fake pdf bytes"


def test_download_blob_to_file_reads_an_excel_file(configured_blob_store, tmp_path):
    blob_store = configured_blob_store
    mock_container = MagicMock()
    mock_stream = MagicMock()
    mock_stream.readall.return_value = b"fake-xlsx-bytes"
    mock_container.download_blob.return_value = mock_stream

    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.return_value = mock_container
        local_path = blob_store.download_blob_to_file(
            "Food and Multi lab testing capability/Food Testing capability.xlsx", tmp_path
        )

    assert local_path.name == "Food Testing capability.xlsx"
    assert local_path.read_bytes() == b"fake-xlsx-bytes"


def test_blob_connection_is_built_from_configured_account_and_container(configured_blob_store):
    blob_store = configured_blob_store
    mock_container = MagicMock()
    mock_container.list_blobs.return_value = []
    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.return_value = mock_container
        blob_store.list_blobs()

    mock_cls.assert_called_once_with(
        account_url="https://fakeaccount.blob.core.windows.net", credential="fake-key"
    )
    mock_cls.return_value.get_container_client.assert_called_once_with("ticbot-docs")


@pytest.fixture
def connection_string_blob_store(monkeypatch):
    conn_str = (
        "DefaultEndpointsProtocol=https;AccountName=fakeaccount;"
        "AccountKey=fake-key;EndpointSuffix=core.windows.net"
    )
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", conn_str)
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


@pytest.fixture
def multi_container_blob_store(monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://fakeaccount.blob.core.windows.net")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "fake-key")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "sample-pdf-data,sample-xlsx-data")
    blob_store = _reload_config_and_blob_store()
    try:
        yield blob_store
    finally:
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "")
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "")
        _reload_config_and_blob_store()


def test_list_blobs_scans_every_configured_container_and_tags_each_blob(multi_container_blob_store):
    blob_store = multi_container_blob_store
    pdf_container = MagicMock()
    pdf_container.list_blobs.return_value = [_fake_blob("FSSAI Regulation/Contaminants_Regulations.pdf")]
    xlsx_container = MagicMock()
    xlsx_container.list_blobs.return_value = [_fake_blob("Food Testing capability.xlsx")]

    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.side_effect = lambda name: {
            "sample-pdf-data": pdf_container, "sample-xlsx-data": xlsx_container,
        }[name]
        blobs = blob_store.list_blobs()

    assert len(blobs) == 2
    by_container = {b.container: b.name for b in blobs}
    assert by_container == {
        "sample-pdf-data": "FSSAI Regulation/Contaminants_Regulations.pdf",
        "sample-xlsx-data": "Food Testing capability.xlsx",
    }


def test_download_blob_to_file_targets_the_given_container(multi_container_blob_store, tmp_path):
    blob_store = multi_container_blob_store
    xlsx_container = MagicMock()
    mock_stream = MagicMock()
    mock_stream.readall.return_value = b"fake-xlsx-bytes"
    xlsx_container.download_blob.return_value = mock_stream

    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.return_value = xlsx_container
        blob_store.download_blob_to_file("Food Testing capability.xlsx", tmp_path, container="sample-xlsx-data")

    mock_cls.return_value.get_container_client.assert_called_once_with("sample-xlsx-data")


def test_blob_connection_accepts_a_full_connection_string_in_account_url(connection_string_blob_store):
    # A connection string copy-pasted from the Azure portal into
    # AZURE_STORAGE_ACCOUNT_URL (instead of the documented plain endpoint)
    # must still work, via BlobServiceClient.from_connection_string.
    blob_store = connection_string_blob_store
    mock_container = MagicMock()
    mock_container.list_blobs.return_value = []
    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.from_connection_string.return_value.get_container_client.return_value = mock_container
        blob_store.list_blobs()

    mock_cls.from_connection_string.assert_called_once_with(blob_store.STORAGE.account_url)
    mock_cls.assert_not_called()
    mock_cls.from_connection_string.return_value.get_container_client.assert_called_once_with("ticbot-docs")
