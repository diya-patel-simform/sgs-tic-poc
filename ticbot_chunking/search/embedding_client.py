"""Batched Azure OpenAI embedding generation for the index-chunks pipeline.

Retries a whole batch request on transient errors (rate limiting, timeouts,
5xx) with exponential backoff; a non-transient error (e.g. a malformed
input) or a batch that exhausts its retries is raised back to the caller,
which is expected to record it as a failure for every chunk in that batch
and continue with the next one — see `ticbot_chunking/search/indexer.py`.
Never indexes a document without its vector: a failed batch's chunks are
simply not embedded, not embedded-with-a-placeholder.
"""
from __future__ import annotations

import time

from ticbot_chunking.config import OPENAI

DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 2.0

_TRANSIENT_MARKERS = (
    "rate limit", "timeout", "temporarily", "connection", "throttl",
    "429", "500", "502", "503", "504",
)


def is_transient_error(error: Exception) -> bool:
    return any(marker in str(error).lower() for marker in _TRANSIENT_MARKERS)


def _client():
    if not OPENAI.is_configured:
        raise RuntimeError(
            "Azure OpenAI is not configured. Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and "
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT (see .env.example) before generating embeddings."
        )
    from openai import AzureOpenAI

    return AzureOpenAI(azure_endpoint=OPENAI.sdk_endpoint, api_key=OPENAI.api_key, api_version=OPENAI.api_version)


def embed_batch_with_retry(texts: list[str], *, max_retries: int = DEFAULT_MAX_RETRIES,
                            backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
                            client=None) -> list[list[float]]:
    """Embeds one batch of texts in a single Azure OpenAI request. Raises
    the last exception if every retry is exhausted, or immediately for a
    non-transient error."""
    client = client or _client()
    attempt = 0
    while True:
        try:
            response = client.embeddings.create(model=OPENAI.embedding_deployment, input=texts)
            return [d.embedding for d in response.data]
        except Exception as e:
            attempt += 1
            if attempt > max_retries or not is_transient_error(e):
                raise
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))
