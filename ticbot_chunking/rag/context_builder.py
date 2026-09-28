"""Converts retrieved Azure AI Search chunks (RetrievalResult, from the
existing `search/retrieval_client.py`) into a numbered, LLM-readable
context block. Each numbered source in the returned text corresponds
1:1 (by position) to the `RetrievalResult` in the returned list, which
`rag_service.py` uses to build citations from real metadata — the LLM
never sees or invents a chunk_id, it only sees a source number.
"""
from __future__ import annotations

from ticbot_chunking.search.retrieval_client import RetrievalResult


def _source_block(index: int, result: RetrievalResult) -> str:
    lines = [f"Source [{index}]", f"File: {result.source_file or 'unknown'}"]
    if result.document_type:
        lines.append(f"Document type: {result.document_type}")
    if result.pages:
        lines.append(f"Page(s): {', '.join(str(p) for p in result.pages)}")
    if result.sheet:
        lines.append(f"Sheet: {result.sheet}")
    if result.cell_range:
        lines.append(f"Cell range: {result.cell_range}")
    section = result.section_path or result.section_number
    if section:
        lines.append(f"Section: {section}")
    if result.certificate_no:
        lines.append(f"Certificate number: {result.certificate_no}")
    if result.lab_location:
        lines.append(f"Laboratory: {result.lab_location}")
    if result.discipline:
        lines.append(f"Discipline: {result.discipline}")
    if result.material:
        lines.append(f"Material: {result.material}")
    if result.authority:
        lines.append(f"Authority: {result.authority}")
    lines.append(f"Content:\n{result.text}")
    return "\n".join(lines)


def build_context(results: list[RetrievalResult]) -> str:
    """Builds the full numbered context block for every retrieved result,
    in retrieval-rank order. Source [N] in the text is `results[N-1]`."""
    return "\n\n---\n\n".join(_source_block(i, r) for i, r in enumerate(results, start=1))
