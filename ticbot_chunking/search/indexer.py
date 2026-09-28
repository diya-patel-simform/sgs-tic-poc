"""Core embedding + upload pipeline for one strategy's chunks.jsonl:

    chunks.jsonl -> read chunk -> generate embedding -> build Search
    document (ticbot_chunking.search.document_mapper) -> upload to the
    strategy's Azure AI Search index (action="upload": creates a new
    document, or entirely replaces an existing one with the same
    chunk_id — the idempotency this step relies on; see chunk_id.py).

Batches both embedding requests and Search uploads (`--batch-size`).
Never indexes a document without its embedding: a batch whose embedding
call fails (after retries) is recorded as a failure for every chunk in it
and skipped, not indexed with a missing/placeholder vector. Kept separate
from `scripts/index_chunks.py` so the pipeline is unit-testable without a
CLI or a live Azure service (both `embed_fn` and `search_client` are
injectable).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ticbot_chunking.config import SEARCH
from ticbot_chunking.search.document_mapper import build_search_document
from ticbot_chunking.search.embedding_client import embed_batch_with_retry

EmbedFn = Callable[[list[str]], list[list[float]]]


@dataclass
class IndexingRunResult:
    strategy: str
    index_name: str
    chunks_read: int = 0
    embeddings_generated: int = 0
    documents_uploaded: int = 0
    documents_updated: int = 0
    embedding_failures: list[dict[str, Any]] = field(default_factory=list)
    upload_failures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def documents_indexed(self) -> int:
        return self.documents_uploaded + self.documents_updated

    @property
    def total_failures(self) -> int:
        return len(self.embedding_failures) + len(self.upload_failures)


def load_chunks_jsonl(path: str | Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def require_search_client(index_name: str):
    if not SEARCH.is_configured:
        raise RuntimeError(
            "Azure AI Search is not configured. Set AZURE_SEARCH_ENDPOINT and "
            "AZURE_SEARCH_ADMIN_KEY (see .env.example) before indexing documents."
        )
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    return SearchClient(endpoint=SEARCH.endpoint, index_name=index_name,
                         credential=AzureKeyCredential(SEARCH.admin_key))


def index_chunks_file(chunks_path: str | Path, strategy: str, index_name: str, *, batch_size: int = 16,
                       max_retries: int = 3, retry_backoff_seconds: float = 2.0,
                       embed_fn: EmbedFn | None = None, search_client=None) -> IndexingRunResult:
    rows = load_chunks_jsonl(chunks_path)
    result = IndexingRunResult(strategy=strategy, index_name=index_name, chunks_read=len(rows))

    embed = embed_fn or (lambda texts: embed_batch_with_retry(
        texts, max_retries=max_retries, backoff_seconds=retry_backoff_seconds))
    client = search_client if search_client is not None else require_search_client(index_name)

    for batch_start in range(0, len(rows), batch_size):
        batch = list(enumerate(rows))[batch_start:batch_start + batch_size]  # [(index_in_file, row), ...]
        # Embed the short, spell-normalized `embed_text` when a chunk has
        # one (Chunk.embed_text — see chunkers/regulation.py, brochure.py)
        # instead of the long citation-oriented `text`, which repeats the
        # full breadcrumb on every chunk from the same document and was
        # confirmed to bunch vector similarity scores together. Falls back
        # to `text` for chunk types that don't set one (e.g. Excel).
        texts = [row.get("embed_text") or row["text"] for _, row in batch]

        try:
            vectors = embed(texts)
        except Exception as e:
            for index_in_file, row in batch:
                metadata = row.get("metadata", {})
                result.embedding_failures.append({
                    "index_in_file": index_in_file,
                    "source_file": metadata.get("source_file"),
                    "error": f"{type(e).__name__}: {e}",
                })
            continue

        result.embeddings_generated += len(vectors)

        documents = [
            build_search_document(row, strategy, index_in_file, vector)
            for (index_in_file, row), vector in zip(batch, vectors)
        ]

        try:
            upload_results = client.upload_documents(documents=documents)
        except Exception as e:
            for doc in documents:
                result.upload_failures.append({"chunk_id": doc["chunk_id"], "error": f"{type(e).__name__}: {e}"})
            continue

        for upload_result in upload_results:
            if not upload_result.succeeded:
                result.upload_failures.append({
                    "chunk_id": upload_result.key,
                    "error": upload_result.error_message or f"status_code={upload_result.status_code}",
                })
            elif upload_result.status_code == 201:
                result.documents_uploaded += 1
            else:  # 200: an existing document with this chunk_id was replaced
                result.documents_updated += 1

    return result
