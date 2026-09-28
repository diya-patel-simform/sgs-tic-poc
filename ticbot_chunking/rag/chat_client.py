"""Azure OpenAI chat-completion client for RAG answer generation.

Mirrors `search/embedding_client.py`'s retry behavior exactly (reusing its
`is_transient_error` classifier rather than duplicating it) — a transient
error (rate limit, timeout, 5xx) is retried with exponential backoff; a
non-transient error, or a batch that exhausts its retries, is raised to
the caller.
"""
from __future__ import annotations

import time

from ticbot_chunking.config import OPENAI
from ticbot_chunking.search.embedding_client import DEFAULT_MAX_RETRIES, DEFAULT_RETRY_BACKOFF_SECONDS, is_transient_error


def require_chat_client():
    if not OPENAI.is_configured:
        raise RuntimeError(
            "Azure OpenAI is not configured. Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and "
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT (see .env.example)."
        )
    if not OPENAI.chat_deployment:
        raise RuntimeError(
            "AZURE_OPENAI_CHAT_DEPLOYMENT is not set. A chat deployment is required for RAG answer "
            "generation — set it in .env (see .env.example) before using the RAG service."
        )
    from openai import AzureOpenAI

    return AzureOpenAI(azure_endpoint=OPENAI.sdk_endpoint, api_key=OPENAI.api_key, api_version=OPENAI.api_version)


def complete_chat_with_retry(messages: list[dict[str, str]], *, max_retries: int = DEFAULT_MAX_RETRIES,
                              backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS, temperature: float = 0.0,
                              client=None) -> str:
    client = client or require_chat_client()
    attempt = 0
    while True:
        try:
            response = client.chat.completions.create(model=OPENAI.chat_deployment, messages=messages,
                                                        temperature=temperature)
            return (response.choices[0].message.content or "").strip()
        except Exception as e:
            attempt += 1
            if attempt > max_retries or not is_transient_error(e):
                raise
            time.sleep(backoff_seconds * (2 ** (attempt - 1)))
