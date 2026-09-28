"""Common retrieval interface across the four strategy-specific Azure AI
Search indexes and three retrieval modes:

    keyword — search_text only (Azure's default BM25-style relevance)
    vector  — vector_queries only, against the query's own embedding
              (same AZURE_OPENAI_EMBEDDING_DEPLOYMENT used for document
              embeddings, so query and document vectors are comparable)
    hybrid  — search_text + vector_queries together (Azure AI Search fuses
              both rankings internally, RRF, when both are supplied)

No local vector database — every mode goes through Azure AI Search.
Semantic/reranker scoring isn't enabled by any of these three modes (no
`query_type="semantic"`), so `reranker_score` is always None here; the
field is still preserved (as None) rather than omitted, since the schema
has a semantic configuration ready for it later.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from ticbot_chunking.search.embedding_client import embed_batch_with_retry
from ticbot_chunking.search.indexer import require_search_client
from ticbot_chunking.search.schema import STRATEGY_INDEX_NAMES, VECTOR_FIELD_NAME

MODES = ("keyword", "vector", "hybrid")

# Every citation/provenance field the schema defines, plus chunk_id/text —
# selected explicitly so retrieval never silently drops a metadata field.
SELECT_FIELDS = [
    "chunk_id", "text", "chunking_strategy", "document_type", "chunk_type", "source_file",
    "blob_path", "parser_used", "pages", "page_start", "page_end", "printed_page_label", "doc_title",
    "section_path", "section_number", "authority",
    "lab_location", "certificate_no", "discipline", "material", "facility", "sheet",
    "cell_range", "access_class", "contains_pii",
]

EmbedFn = Callable[[str], list[float]]


@dataclass
class RetrievalResult:
    rank: int
    score: float | None
    reranker_score: float | None
    chunk_id: str | None
    text: str | None
    chunking_strategy: str | None
    source_file: str | None
    blob_path: str | None
    parser_used: str | None
    pages: list[int] | None
    section_path: str | None
    section_number: str | None
    chunk_type: str | None
    document_type: str | None
    sheet: str | None
    cell_range: str | None
    authority: str | None
    lab_location: str | None
    certificate_no: str | None
    discipline: str | None
    material: str | None
    facility: str | None
    # Added after the page-level-routing/chunking overhaul — defaulted so
    # every existing keyword-constructed fixture/caller (tests, from_dict)
    # stays valid without needing to name these explicitly.
    page_start: int | None = None
    page_end: int | None = None
    printed_page_label: str | None = None
    doc_title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RetrievalResult":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


@dataclass
class RetrievalQueryResult:
    query: str
    strategy: str
    index_name: str
    mode: str
    top_k: int
    filter: str | None
    latency_seconds: float
    results: list[RetrievalResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query, "strategy": self.strategy, "index_name": self.index_name,
            "mode": self.mode, "top_k": self.top_k, "filter": self.filter,
            "latency_seconds": self.latency_seconds,
            "results": [r.to_dict() for r in self.results],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RetrievalQueryResult":
        return cls(
            query=d["query"], strategy=d["strategy"], index_name=d["index_name"], mode=d["mode"],
            top_k=d["top_k"], filter=d.get("filter"), latency_seconds=d["latency_seconds"],
            results=[RetrievalResult.from_dict(r) for r in d.get("results", [])],
        )


def embed_query(text: str) -> list[float]:
    """Embeds a single query with the same embedding client (and therefore
    the same deployment/dimension) used for document embeddings."""
    return embed_batch_with_retry([text])[0]


def _doc_to_result(rank: int, doc: dict[str, Any]) -> RetrievalResult:
    return RetrievalResult(
        rank=rank,
        score=doc.get("@search.score"),
        reranker_score=doc.get("@search.rerankerScore"),
        chunk_id=doc.get("chunk_id"),
        text=doc.get("text"),
        chunking_strategy=doc.get("chunking_strategy"),
        source_file=doc.get("source_file"),
        blob_path=doc.get("blob_path"),
        parser_used=doc.get("parser_used"),
        pages=doc.get("pages"),
        page_start=doc.get("page_start"),
        page_end=doc.get("page_end"),
        printed_page_label=doc.get("printed_page_label"),
        doc_title=doc.get("doc_title"),
        section_path=doc.get("section_path"),
        section_number=doc.get("section_number"),
        chunk_type=doc.get("chunk_type"),
        document_type=doc.get("document_type"),
        sheet=doc.get("sheet"),
        cell_range=doc.get("cell_range"),
        authority=doc.get("authority"),
        lab_location=doc.get("lab_location"),
        certificate_no=doc.get("certificate_no"),
        discipline=doc.get("discipline"),
        material=doc.get("material"),
        facility=doc.get("facility"),
    )


def search(strategy: str, mode: str, query: str, *, top_k: int = 5, filter: str | None = None,
           index_name: str | None = None, search_client=None, embed_fn: EmbedFn | None = None,
           ) -> RetrievalQueryResult:
    """Runs one query against one strategy's index in one retrieval mode.
    `search_client`/`embed_fn` are injectable for tests — no real Azure
    service is required to exercise this function's logic."""
    if mode not in MODES:
        raise ValueError(f"Unknown retrieval mode: {mode!r} (expected one of {MODES})")

    index_name = index_name or STRATEGY_INDEX_NAMES[strategy]
    client = search_client if search_client is not None else require_search_client(index_name)
    embed = embed_fn or embed_query

    search_text = query if mode in ("keyword", "hybrid") else None
    vector_queries = None
    if mode in ("vector", "hybrid"):
        from azure.search.documents.models import VectorizedQuery

        vector_queries = [VectorizedQuery(vector=embed(query), k_nearest_neighbors=top_k,
                                           fields=VECTOR_FIELD_NAME)]

    search_kwargs: dict[str, Any] = {"search_text": search_text, "vector_queries": vector_queries,
                                      "select": SELECT_FIELDS, "top": top_k}
    if filter:
        search_kwargs["filter"] = filter

    start = time.monotonic()
    raw_results = list(client.search(**search_kwargs))
    latency = time.monotonic() - start

    results = [_doc_to_result(rank, doc) for rank, doc in enumerate(raw_results, start=1)]
    return RetrievalQueryResult(query=query, strategy=strategy, index_name=index_name, mode=mode,
                                 top_k=top_k, filter=filter, latency_seconds=latency, results=results)
