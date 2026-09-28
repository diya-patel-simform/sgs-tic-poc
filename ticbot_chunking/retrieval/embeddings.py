"""Azure OpenAI embeddings for the vector side of hybrid search."""
from __future__ import annotations

from ticbot_chunking.config import OPENAI

# The embedding vector width — from config.OPENAI.embedding_dimensions
# (AZURE_OPENAI_EMBEDDING_DIMENSIONS override, else a known default for
# AZURE_OPENAI_EMBEDDING_DEPLOYMENT), falling back to text-embedding-3-large's
# native 3072 only if neither resolves anything.
EMBEDDING_DIMENSIONS = OPENAI.embedding_dimensions or 3072


def _client():
    if not OPENAI.is_configured:
        raise RuntimeError(
            "Azure OpenAI is not configured. Set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and "
            "AZURE_OPENAI_EMBEDDING_DEPLOYMENT (see .env.example)."
        )
    from openai import AzureOpenAI

    return AzureOpenAI(azure_endpoint=OPENAI.sdk_endpoint, api_key=OPENAI.api_key, api_version=OPENAI.api_version)


def embed_texts(texts: list[str], batch_size: int = 96) -> list[list[float]]:
    client = _client()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        resp = client.embeddings.create(model=OPENAI.embedding_deployment, input=batch)
        vectors.extend(d.embedding for d in resp.data)
    return vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
