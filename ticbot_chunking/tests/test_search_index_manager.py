"""Tests for the Azure AI Search index manager
(ticbot_chunking/search/index_manager.py). `SearchIndexClient` is mocked at
its source module — no real Azure AI Search service is needed or contacted.
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest

from ticbot_chunking.search.schema import STRATEGY_INDEX_NAMES, build_index


def _reload_config_and_index_manager():
    import ticbot_chunking.config as config
    importlib.reload(config)
    import ticbot_chunking.search.index_manager as index_manager
    importlib.reload(index_manager)
    return index_manager


@pytest.fixture
def configured_search(monkeypatch):
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://fake-search.search.windows.net")
    monkeypatch.setenv("AZURE_SEARCH_ADMIN_KEY", "fake-admin-key")
    index_manager = _reload_config_and_index_manager()
    try:
        yield index_manager
    finally:
        monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "")
        monkeypatch.setenv("AZURE_SEARCH_ADMIN_KEY", "")
        _reload_config_and_index_manager()


def _fake_index():
    return build_index(STRATEGY_INDEX_NAMES["fixed"], "fixed", 3072)


def test_raises_clear_error_when_search_not_configured(monkeypatch):
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "")
    monkeypatch.setenv("AZURE_SEARCH_ADMIN_KEY", "")
    index_manager = _reload_config_and_index_manager()

    with pytest.raises(RuntimeError, match="not configured"):
        index_manager.index_exists("ticbot-chunks-fixed")
    with pytest.raises(RuntimeError, match="not configured"):
        index_manager.create_index(_fake_index())


def test_index_exists_true_when_name_in_list(configured_search):
    index_manager = configured_search
    mock_client = MagicMock()
    mock_client.list_index_names.return_value = ["ticbot-chunks-fixed", "some-other-index"]
    with patch("azure.search.documents.indexes.SearchIndexClient", return_value=mock_client):
        assert index_manager.index_exists("ticbot-chunks-fixed") is True


def test_index_exists_false_when_name_absent(configured_search):
    index_manager = configured_search
    mock_client = MagicMock()
    mock_client.list_index_names.return_value = ["some-other-index"]
    with patch("azure.search.documents.indexes.SearchIndexClient", return_value=mock_client):
        assert index_manager.index_exists("ticbot-chunks-fixed") is False


def test_create_index_creates_when_absent(configured_search):
    index_manager = configured_search
    mock_client = MagicMock()
    mock_client.list_index_names.return_value = []
    index = _fake_index()

    with patch("azure.search.documents.indexes.SearchIndexClient", return_value=mock_client):
        result = index_manager.create_index(index)

    assert result == "created"
    mock_client.create_index.assert_called_once_with(index)
    mock_client.delete_index.assert_not_called()


def test_create_index_reports_exists_and_never_deletes_by_default(configured_search):
    index_manager = configured_search
    mock_client = MagicMock()
    mock_client.list_index_names.return_value = [STRATEGY_INDEX_NAMES["fixed"]]
    index = _fake_index()

    with patch("azure.search.documents.indexes.SearchIndexClient", return_value=mock_client):
        result = index_manager.create_index(index)

    assert result == "exists"
    mock_client.create_index.assert_not_called()
    mock_client.delete_index.assert_not_called()


def test_create_index_recreates_only_when_explicitly_requested(configured_search):
    index_manager = configured_search
    mock_client = MagicMock()
    mock_client.list_index_names.return_value = [STRATEGY_INDEX_NAMES["fixed"]]
    index = _fake_index()

    with patch("azure.search.documents.indexes.SearchIndexClient", return_value=mock_client):
        result = index_manager.create_index(index, recreate=True)

    assert result == "recreated"
    mock_client.delete_index.assert_called_once_with(index.name)
    mock_client.create_index.assert_called_once_with(index)


def test_get_index_delegates_to_the_client(configured_search):
    index_manager = configured_search
    mock_client = MagicMock()
    fake_live_index = _fake_index()
    mock_client.get_index.return_value = fake_live_index

    with patch("azure.search.documents.indexes.SearchIndexClient", return_value=mock_client):
        result = index_manager.get_index("ticbot-chunks-fixed")

    assert result is fake_live_index
    mock_client.get_index.assert_called_once_with("ticbot-chunks-fixed")
