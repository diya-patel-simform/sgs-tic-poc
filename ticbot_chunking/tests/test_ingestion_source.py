"""Tests for ticbot_chunking/ingestion/source.py — document listing/fetching
for the end-to-end ingestion pipeline. Azure Blob Storage is mocked
(never a live call), following the same pattern as test_blob_store.py.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ticbot_chunking.ingestion.source import fetch_to_local, list_source_files


def _reload_config_and_blob_store():
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
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "ticbot-docs")
    source = _reload_config_and_blob_store()
    try:
        yield source
    finally:
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "")
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "")
        _reload_config_and_blob_store()


def _fake_blob(name: str, size: int = 100):
    return SimpleNamespace(name=name, size=size, content_settings=None, last_modified=None)


def test_list_source_files_uses_blob_storage_when_configured(configured_blob_store):
    source = configured_blob_store
    mock_container = MagicMock()
    mock_container.list_blobs.return_value = [_fake_blob("a.pdf"), _fake_blob("b.xlsx"), _fake_blob("notes.txt")]
    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.return_value = mock_container
        kind, files = source.list_source_files()

    assert kind == "blob"
    assert {f.name for f in files} == {"ticbot-docs/a.pdf", "ticbot-docs/b.xlsx"}  # notes.txt filtered out
    assert {f.blob_name for f in files} == {"a.pdf", "b.xlsx"}
    assert all(f.container == "ticbot-docs" for f in files)


def test_list_source_files_container_override_restricts_to_that_container(configured_blob_store):
    source = configured_blob_store
    mock_container = MagicMock()
    mock_container.list_blobs.return_value = [_fake_blob("c.pdf")]
    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.return_value = mock_container
        kind, files = source.list_source_files(container="updated-pdf-data")

    mock_cls.return_value.get_container_client.assert_called_once_with("updated-pdf-data")
    assert {f.name for f in files} == {"updated-pdf-data/c.pdf"}
    assert files[0].container == "updated-pdf-data"


def test_list_source_files_no_longer_accepts_a_local_fallback_dir(configured_blob_store, tmp_path):
    # The local-fallback parameter was removed entirely: Azure Blob Storage
    # is the sole ingestion source now, so passing this raises a plain
    # TypeError (unknown keyword) rather than silently being accepted.
    source = configured_blob_store
    with pytest.raises(TypeError):
        source.list_source_files(local_fallback_dir=str(tmp_path))


def test_list_source_files_raises_clear_error_when_blob_not_configured_and_never_reads_local_dir(
    monkeypatch, tmp_path
):
    # Even with real files sitting in a local directory, an unconfigured
    # Blob Storage must fail clearly, never silently read that directory —
    # there is no fallback path left to take.
    (tmp_path / "a.pdf").write_bytes(b"x")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "")
    _reload_config_and_blob_store()

    with pytest.raises(RuntimeError, match="not configured"):
        list_source_files()


def test_fetch_to_local_from_blob_delegates_to_blob_store(configured_blob_store, tmp_path):
    source = configured_blob_store
    mock_container = MagicMock()
    mock_stream = MagicMock()
    mock_stream.readall.return_value = b"pdf-bytes"
    mock_container.download_blob.return_value = mock_stream
    with patch("azure.storage.blob.BlobServiceClient") as mock_cls:
        mock_cls.return_value.get_container_client.return_value = mock_container
        local_path = source.fetch_to_local("blob", "FSSAI Regulation/a.pdf", str(tmp_path))

    assert local_path.name == "a.pdf"
    assert local_path.read_bytes() == b"pdf-bytes"


def test_fetch_to_local_rejects_any_source_kind_other_than_blob(tmp_path):
    # No local-fallback path remains at all: "local_fallback" (or anything
    # else) is rejected outright rather than falling back to copying a
    # local file.
    with pytest.raises(ValueError, match="Blob Storage"):
        fetch_to_local("local_fallback", "a.pdf", str(tmp_path))


def test_fetch_to_local_no_longer_accepts_a_local_fallback_dir():
    with pytest.raises(TypeError):
        fetch_to_local("blob", "a.pdf", "/tmp", local_fallback_dir="/somewhere")
