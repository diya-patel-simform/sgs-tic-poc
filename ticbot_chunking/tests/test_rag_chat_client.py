"""Tests for the RAG chat client (ticbot_chunking/rag/chat_client.py). The
Azure OpenAI client is injected directly — no real Azure OpenAI service is
contacted, and no credentials appear in any assertion here.
"""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ticbot_chunking.rag.chat_client import complete_chat_with_retry


def _fake_response(text: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def _reload_config_and_chat_client():
    import ticbot_chunking.config as config
    importlib.reload(config)
    import ticbot_chunking.rag.chat_client as chat_client
    importlib.reload(chat_client)
    return chat_client


def test_require_chat_client_raises_when_openai_not_configured(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
    chat_client = _reload_config_and_chat_client()
    try:
        with pytest.raises(RuntimeError, match="not configured"):
            chat_client.require_chat_client()
    finally:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
        _reload_config_and_chat_client()


def test_require_chat_client_raises_a_distinct_error_when_chat_deployment_missing(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://fake.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "")
    chat_client = _reload_config_and_chat_client()
    try:
        with pytest.raises(RuntimeError, match="AZURE_OPENAI_CHAT_DEPLOYMENT"):
            chat_client.require_chat_client()
    finally:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
        monkeypatch.setenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "")
        monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "")
        _reload_config_and_chat_client()


def test_complete_chat_returns_the_message_content():
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response("the grounded answer")

    result = complete_chat_with_retry([{"role": "user", "content": "q"}], client=client)

    assert result == "the grounded answer"


def test_complete_chat_retries_a_transient_error_then_succeeds():
    client = MagicMock()
    client.chat.completions.create.side_effect = [RuntimeError("429 rate limit"), _fake_response("ok")]

    result = complete_chat_with_retry([{"role": "user", "content": "q"}], client=client, max_retries=2,
                                       backoff_seconds=0.001)

    assert result == "ok"
    assert client.chat.completions.create.call_count == 2


def test_complete_chat_does_not_retry_a_non_transient_error():
    client = MagicMock()
    client.chat.completions.create.side_effect = ValueError("malformed request")

    with pytest.raises(ValueError, match="malformed request"):
        complete_chat_with_retry([{"role": "user", "content": "q"}], client=client, max_retries=3,
                                  backoff_seconds=0.001)

    client.chat.completions.create.assert_called_once()
