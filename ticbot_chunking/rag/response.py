"""Typed response model for the RAG service — suitable for direct
consumption by a future UI (Streamlit or otherwise) without that caller
needing to know anything about Azure AI Search or Azure OpenAI.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ticbot_chunking.search.retrieval_client import RetrievalResult


@dataclass
class Citation:
    """One structured citation. Every field here is copied from an actual
    retrieved chunk's metadata (see rag_service._build_citation) — never
    from LLM-generated text. `page` is a comma-joined string of the
    chunk's real `pages` list (e.g. "3,4"), not a single invented number.

    `source_numbers` holds every `[N]` marker the model cited that this one
    (deduplicated) citation represents — e.g. if the model wrote `[1][3]`
    and both pointed at the same source_file+section, this Citation appears
    once with `source_numbers=[1, 3]`, rather than twice (see
    `rag_service._dedupe_citations`)."""
    chunk_id: str | None
    source_file: str | None
    document_type: str | None
    page: str | None
    sheet: str | None
    cell_range: str | None
    section: str | None
    certificate_no: str | None
    lab_location: str | None
    discipline: str | None
    material: str | None
    score: float | None
    source_numbers: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RagResponse:
    query: str
    strategy: str
    retrieval_mode: str
    top_k: int
    answer: str
    citations: list[Citation]
    retrieved_chunks: list[RetrievalResult]  # every chunk retrieval returned, cited or not — for debugging
    context_used: bool  # False only when retrieval returned zero results (no LLM call was made)
    retrieval_latency_seconds: float
    llm_latency_seconds: float | None = None  # None when no LLM call was made (empty retrieval)

    @property
    def total_latency_seconds(self) -> float:
        return self.retrieval_latency_seconds + (self.llm_latency_seconds or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "strategy": self.strategy,
            "retrieval_mode": self.retrieval_mode,
            "top_k": self.top_k,
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "retrieved_chunks": [r.to_dict() for r in self.retrieved_chunks],
            "context_used": self.context_used,
            "retrieval_latency_seconds": self.retrieval_latency_seconds,
            "llm_latency_seconds": self.llm_latency_seconds,
            "total_latency_seconds": self.total_latency_seconds,
        }
