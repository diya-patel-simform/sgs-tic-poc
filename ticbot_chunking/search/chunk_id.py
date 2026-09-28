"""Stable document key for Azure AI Search, since `ChunkMetadata` doesn't
carry an id of its own (see `metadata/schema.py`).

Deterministic from (strategy, source_file, position within that strategy's
chunks.jsonl, chunk text): re-indexing the same, unchanged chunks.jsonl
produces the same ids, so `SearchClient.upload_documents` (action="upload")
replaces the existing documents in place instead of duplicating them — the
idempotency this project's index_chunks.py step relies on. Regenerating
chunks.jsonl (a different chunking run) will generally change ids, since
chunk boundaries/content or ordering may shift; that's expected, not a bug.
"""
from __future__ import annotations

import hashlib


def compute_chunk_id(strategy: str, source_file: str, index_in_file: int, text: str) -> str:
    """A hex digest — safe as an Azure AI Search key (letters/digits only)."""
    raw = f"{strategy}|{source_file}|{index_in_file}|{text}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
