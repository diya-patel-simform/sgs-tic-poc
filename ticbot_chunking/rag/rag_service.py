"""RAG answer-generation service:

    question -> existing retrieval client (search/retrieval_client.py)
             -> top-K RetrievalResult
             -> context assembly (context_builder.py)
             -> Azure OpenAI chat model (chat_client.py), grounded by prompt.py
             -> RagResponse (answer + structured citations + raw retrieved chunks)

Reuses the existing retrieval interface exactly as-is — no second Azure AI
Search client, no separate vector store, no duplicated query-embedding
logic (that already happens inside `retrieval_client.search()` for
vector/hybrid mode). This module's only new Azure dependency is the chat
completion call itself.

Citation safety: the LLM is shown numbered sources and asked to cite them
as [N], but the structured `citations` returned to the caller are built
directly from the corresponding `RetrievalResult`'s real metadata — never
parsed or trusted from the LLM's own text beyond which numbers it cited.
An out-of-range or malformed [N] is silently ignored, never surfaced as a
fabricated source.
"""
from __future__ import annotations

import re
import time
from typing import Callable

from ticbot_chunking.config import SEARCH
from ticbot_chunking.rag.chat_client import complete_chat_with_retry
from ticbot_chunking.rag.context_builder import build_context
from ticbot_chunking.rag.prompt import NO_CONTEXT_ANSWER, build_messages
from ticbot_chunking.rag.response import Citation, RagResponse
from ticbot_chunking.search.retrieval_client import RetrievalQueryResult, RetrievalResult
from ticbot_chunking.search.retrieval_client import search as default_search_fn

SearchFn = Callable[..., RetrievalQueryResult]
ChatFn = Callable[[list[dict[str, str]]], str]

_CITATION_MARKER_RE = re.compile(r"\[(\d+)\]")


def _extract_cited_indices(answer_text: str, num_sources: int) -> list[int]:
    """Every [N] the model wrote, deduplicated in first-seen order, and
    filtered to only indices that actually correspond to a source it was
    given — an invented or out-of-range number is dropped, not trusted."""
    seen: list[int] = []
    for m in _CITATION_MARKER_RE.finditer(answer_text):
        idx = int(m.group(1))
        if 1 <= idx <= num_sources and idx not in seen:
            seen.append(idx)
    return seen


def _dedupe_citations(citations: list[Citation], source_numbers: list[int]) -> list[Citation]:
    """Groups citations that point at the same (source_file, section) into
    one, carrying every `[N]` marker that led to it — e.g. the model
    writing `[1][3]` for the same source_file+section previously rendered
    as two separate, redundant citation blocks; now it's one, showing both
    numbers. `section` (not just `source_file`) is part of the key so two
    genuinely different sections of the same document are never collapsed
    into one citation. Order of first appearance is preserved."""
    grouped: dict[tuple, Citation] = {}
    order: list[tuple] = []
    for citation, source_number in zip(citations, source_numbers):
        # Only dedupe by (source_file, section) when there's a real section
        # to key on — two different chunks from the same document that both
        # happen to carry no section metadata are NOT the same citation,
        # so they fall back to a chunk_id-based key instead (never merged).
        key = (citation.source_file, citation.section) if citation.section else (citation.source_file, citation.chunk_id)
        existing = grouped.get(key)
        if existing is None:
            citation.source_numbers = [source_number]
            grouped[key] = citation
            order.append(key)
        else:
            existing.source_numbers.append(source_number)
    return [grouped[k] for k in order]


def _build_citation(result: RetrievalResult) -> Citation:
    """Every field here is copied from the actual retrieved chunk's
    metadata — the LLM never supplies any of these values."""
    return Citation(
        chunk_id=result.chunk_id,
        source_file=result.source_file,
        document_type=result.document_type,
        page=", ".join(str(p) for p in result.pages) if result.pages else None,
        sheet=result.sheet,
        cell_range=result.cell_range,
        section=result.section_path or result.section_number,
        certificate_no=result.certificate_no,
        lab_location=result.lab_location,
        discipline=result.discipline,
        material=result.material,
        score=result.score,
    )


def _looks_like_no_context_answer(answer_text: str) -> bool:
    # Substring rather than exact match — the model is instructed to reply
    # with this sentence exactly, but matching the distinctive fragment is
    # robust to minor formatting/whitespace differences in the real response.
    return "couldn't find enough information" in answer_text.lower()


def answer(question: str, *, strategy: str = "hybrid", mode: str = SEARCH.retrieval_mode, top_k: int = 5,
           filter: str | None = None, index_name: str | None = None, search_fn: SearchFn = default_search_fn,
           chat_fn: ChatFn | None = None) -> RagResponse:
    """Answers `question` using retrieval strategy `strategy`'s index
    (default "hybrid" — the document-type-aware strategy; each of the four
    chunking strategies has its own index) and retrieval mode `mode`
    (default from `config.SEARCH.retrieval_mode`, itself "vector" unless
    the RETRIEVAL_MODE env var overrides it — see that field's docstring
    for why vector, not hybrid or keyword, is the default). `index_name` overrides
    the strategy's default index name (e.g. to test against a separate
    index built from different documents) — passed straight through to
    the existing retrieval client, same as `search_chunks.py`'s own
    `--index` override. `search_fn`/`chat_fn` are injectable for tests;
    neither is called with any mocking in normal use."""
    query_result = search_fn(strategy, mode, question, top_k=top_k, filter=filter, index_name=index_name)

    if not query_result.results:
        return RagResponse(
            query=question, strategy=strategy, retrieval_mode=mode, top_k=top_k,
            answer=NO_CONTEXT_ANSWER, citations=[], retrieved_chunks=[],
            context_used=False, retrieval_latency_seconds=query_result.latency_seconds,
            llm_latency_seconds=None,
        )

    context_text = build_context(query_result.results)
    messages = build_messages(question, context_text)

    chat = chat_fn or complete_chat_with_retry
    start = time.monotonic()
    answer_text = chat(messages)
    llm_latency = time.monotonic() - start

    if _looks_like_no_context_answer(answer_text):
        cited_indices: list[int] = []
    else:
        cited_indices = _extract_cited_indices(answer_text, len(query_result.results))
        wrote_any_marker = bool(_CITATION_MARKER_RE.search(answer_text))
        if not cited_indices and not wrote_any_marker:
            # The model wrote no [N] marker at all but did attempt an answer —
            # default to citing every source it was actually given, since all
            # of it was supplied as potential grounding. This is distinct from
            # writing only invalid/out-of-range markers (e.g. a hallucinated
            # [99]): in that case cited_indices stays empty and citations are
            # correctly left empty too, rather than silently substituting
            # sources the model never actually claimed.
            cited_indices = list(range(1, len(query_result.results) + 1))

    citations = [_build_citation(query_result.results[i - 1]) for i in cited_indices]
    citations = _dedupe_citations(citations, cited_indices)

    return RagResponse(
        query=question, strategy=strategy, retrieval_mode=mode, top_k=top_k,
        answer=answer_text, citations=citations, retrieved_chunks=query_result.results,
        context_used=True, retrieval_latency_seconds=query_result.latency_seconds,
        llm_latency_seconds=llm_latency,
    )
