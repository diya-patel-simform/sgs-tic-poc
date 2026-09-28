"""Tests for the batched embedding client
(ticbot_chunking/search/embedding_client.py). The Azure OpenAI client is
injected directly (`client=...`) — no real Azure OpenAI service is
contacted, and no credentials appear in any assertion or log line here.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ticbot_chunking.search.embedding_client import embed_batch_with_retry, is_transient_error


def _fake_response(vectors: list[list[float]]):
    return SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in vectors])


@pytest.mark.parametrize("message", ["Rate limit exceeded", "Request timeout", "503 Service Unavailable",
                                      "connection reset", "429 Too Many Requests"])
def test_is_transient_error_recognizes_known_transient_messages(message):
    assert is_transient_error(RuntimeError(message)) is True


def test_is_transient_error_false_for_content_errors():
    assert is_transient_error(ValueError("invalid input: text too long")) is False


def test_embed_batch_returns_one_vector_per_text():
    client = MagicMock()
    client.embeddings.create.return_value = _fake_response([[0.1, 0.2], [0.3, 0.4]])

    vectors = embed_batch_with_retry(["a", "b"], client=client)

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    client.embeddings.create.assert_called_once()


def test_embed_batch_retries_a_transient_error_then_succeeds():
    client = MagicMock()
    client.embeddings.create.side_effect = [
        RuntimeError("429 rate limit"),
        _fake_response([[0.1]]),
    ]

    vectors = embed_batch_with_retry(["a"], client=client, max_retries=2, backoff_seconds=0.001)

    assert vectors == [[0.1]]
    assert client.embeddings.create.call_count == 2


def test_embed_batch_raises_after_exhausting_retries():
    client = MagicMock()
    client.embeddings.create.side_effect = RuntimeError("timeout")

    with pytest.raises(RuntimeError, match="timeout"):
        embed_batch_with_retry(["a"], client=client, max_retries=2, backoff_seconds=0.001)

    assert client.embeddings.create.call_count == 3  # initial attempt + 2 retries


def test_embed_batch_does_not_retry_a_non_transient_error():
    client = MagicMock()
    client.embeddings.create.side_effect = ValueError("malformed input")

    with pytest.raises(ValueError, match="malformed input"):
        embed_batch_with_retry(["a"], client=client, max_retries=3, backoff_seconds=0.001)

    client.embeddings.create.assert_called_once()  # no retries for a non-transient error
