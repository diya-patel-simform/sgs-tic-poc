"""Chunk-size limits and Azure service configuration.

Default numbers below are taken directly from section 2 ("Chunk size
configuration") of TICbot_Chunking_Strategy_Answers.md. Every limit can be
overridden with an environment variable (e.g. in `.env`) without touching
code, so chunk size and overlap are configurable per deployment/tuning run.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_int_or_none(name: str) -> int | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


# Known output dimensionality of Azure OpenAI's embedding models, keyed by
# deployment/model name — used only as a fallback default when
# AZURE_OPENAI_EMBEDDING_DIMENSIONS isn't set explicitly. text-embedding-3-*
# models support the `dimensions` API parameter to shorten this, so an
# explicit override always wins.
KNOWN_EMBEDDING_DIMENSIONS = {
    "text-embedding-3-large": 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-ada-002": 1536,
}


@dataclass(frozen=True)
class NarrativeLimits:
    # smaller neighbouring sections under the same parent are merged below this
    min_tokens: int = _env_int("CHUNK_NARRATIVE_MIN_TOKENS", 60)
    target_tokens: int = _env_int("CHUNK_NARRATIVE_TARGET_TOKENS", 400)
    max_tokens: int = _env_int("CHUNK_NARRATIVE_MAX_TOKENS", 700)
    # ~10-15% of target, used only when splitting one long section
    overlap_max_tokens: int = _env_int("CHUNK_NARRATIVE_OVERLAP_MAX_TOKENS", 60)


@dataclass(frozen=True)
class TableLimits:
    # a row is never split; a chunk may slightly exceed this once the
    # breadcrumb header is added (see section 2 footnote)
    max_tokens: int = _env_int("CHUNK_TABLE_MAX_TOKENS", 550)


@dataclass(frozen=True)
class NablLimits:
    max_tokens: int = _env_int("CHUNK_NABL_MAX_TOKENS", 450)


@dataclass(frozen=True)
class ExcelLimits:
    max_tokens: int = _env_int("CHUNK_EXCEL_MAX_TOKENS", 450)


NARRATIVE = NarrativeLimits()
REGULATION_TABLE = TableLimits()
NABL_SCOPE = NablLimits()
EXCEL_BLOCK = ExcelLimits()

TOKENIZER_MODEL = "text-embedding-3-large"


@dataclass(frozen=True)
class AzureStorageConfig:
    account_url: str | None = os.environ.get("AZURE_STORAGE_ACCOUNT_URL") or None
    account_key: str | None = os.environ.get("AZURE_STORAGE_ACCOUNT_KEY") or None
    # A single container name, or a comma-separated list (e.g. sample docs
    # are split across "sample-pdf-data" and "sample-xlsx-data" containers).
    container_name: str | None = os.environ.get("AZURE_STORAGE_CONTAINER_NAME") or None

    @property
    def container_names(self) -> list[str]:
        if not self.container_name:
            return []
        return [c.strip() for c in self.container_name.split(",") if c.strip()]

    @property
    def is_configured(self) -> bool:
        return bool(self.account_url and self.account_key and self.container_names)


@dataclass(frozen=True)
class AzureDocIntelConfig:
    endpoint: str | None = os.environ.get("AZURE_DOCINTEL_ENDPOINT") or None
    key: str | None = os.environ.get("AZURE_DOCINTEL_KEY") or None

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.key)


@dataclass(frozen=True)
class AzureSearchConfig:
    endpoint: str | None = os.environ.get("AZURE_SEARCH_ENDPOINT") or None
    admin_key: str | None = os.environ.get("AZURE_SEARCH_ADMIN_KEY") or None
    index_name: str = os.environ.get("AZURE_SEARCH_INDEX_NAME", "ticbot-chunks")
    # The retrieval mode used by default (rag_service.answer, the Streamlit
    # UI) — "vector" scored far more reliably than "keyword" in manual
    # testing (keyword ranked the wrong document's chunk #1 on multiple
    # regulation questions). "hybrid" stays available for later re-testing
    # once Azure's semantic ranker is wired up and more documents are
    # indexed. Keyword-only is not offered as a default at all; it remains
    # callable directly via search/retrieval_client.py for eval tooling.
    retrieval_mode: str = os.environ.get("RETRIEVAL_MODE", "vector")

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.admin_key)


@dataclass(frozen=True)
class AzureOpenAIConfig:
    endpoint: str | None = os.environ.get("AZURE_OPENAI_ENDPOINT") or None
    api_key: str | None = os.environ.get("AZURE_OPENAI_API_KEY") or None
    api_version: str = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-06-01")
    embedding_deployment: str | None = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT") or None
    chat_deployment: str | None = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT") or None
    # Explicit override — takes priority over the KNOWN_EMBEDDING_DIMENSIONS
    # lookup by embedding_deployment. Needed because a deployment name isn't
    # a reliable proxy for its actual output size (a custom deployment name,
    # or a text-embedding-3-* model called with a shortened `dimensions`).
    embedding_dimensions_override: int | None = _env_int_or_none("AZURE_OPENAI_EMBEDDING_DIMENSIONS")

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.api_key and self.embedding_deployment)

    @property
    def embedding_dimensions(self) -> int | None:
        """The vector width to use for the search index's vector field.
        None means neither an explicit override nor a known default could
        be determined — callers must fail clearly rather than guess."""
        if self.embedding_dimensions_override is not None:
            return self.embedding_dimensions_override
        if self.embedding_deployment:
            return KNOWN_EMBEDDING_DIMENSIONS.get(self.embedding_deployment.lower())
        return None

    @property
    def sdk_endpoint(self) -> str | None:
        """`AzureOpenAI(azure_endpoint=...)` expects the bare resource root
        (https://<resource>.openai.azure.com) and appends its own
        /openai/... path — passing it the newer ".../openai/v1" endpoint
        format the Azure portal now also hands out (for the OpenAI-compatible
        v1 API surface) produces a doubled, 404ing URL. Both copy-paste
        forms are accepted by stripping a trailing /openai/v1 or /openai
        here, once, so every caller (embedding_client.py,
        retrieval/embeddings.py) gets a working endpoint regardless of
        which format ended up in .env."""
        if not self.endpoint:
            return self.endpoint
        stripped = self.endpoint.rstrip("/")
        for suffix in ("/openai/v1", "/openai"):
            if stripped.endswith(suffix):
                return stripped[: -len(suffix)]
        return stripped


STORAGE = AzureStorageConfig()
DOCINTEL = AzureDocIntelConfig()
SEARCH = AzureSearchConfig()
OPENAI = AzureOpenAIConfig()
