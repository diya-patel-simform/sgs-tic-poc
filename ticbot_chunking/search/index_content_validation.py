"""Post-indexing DATA validation: does the live index actually contain what
`indexer.index_chunks_file` just tried to put there? Distinct from
`validate.py` (index SCHEMA validation, run before any document exists) —
this checks live document content: total count vs. the chunks.jsonl that
was read, and a sample of real documents for vector/text/metadata
population and chunk_id uniqueness. This is data validation, not a
retrieval feature — no ranking, answering, or citation logic here.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IndexContentReport:
    index_name: str
    expected_chunk_count: int
    live_document_count: int
    sampled_documents: int
    vector_field_populated: bool
    text_field_populated: bool
    source_metadata_populated: bool
    chunk_ids_unique_in_sample: bool
    problems: list[str] = field(default_factory=list)

    @property
    def count_matches(self) -> bool:
        return self.expected_chunk_count == self.live_document_count

    @property
    def ok(self) -> bool:
        return not self.problems


def validate_indexed_content(search_client, expected_chunk_count: int, index_name: str,
                              sample_size: int = 50) -> IndexContentReport:
    problems: list[str] = []

    live_count = search_client.get_document_count()
    if live_count != expected_chunk_count:
        problems.append(
            f"document count mismatch: expected {expected_chunk_count} (chunks read from chunks.jsonl), "
            f"found {live_count} in '{index_name}'"
        )

    sampled = list(search_client.search(
        search_text="*", select=["chunk_id", "text", "chunk_vector", "source_file"], top=sample_size,
    ))

    vector_populated = bool(sampled) and all(bool(d.get("chunk_vector")) for d in sampled)
    text_populated = bool(sampled) and all(bool(d.get("text")) for d in sampled)
    source_populated = bool(sampled) and all(bool(d.get("source_file")) for d in sampled)
    ids = [d.get("chunk_id") for d in sampled]
    ids_unique = len(ids) == len(set(ids))

    if not sampled:
        problems.append("no documents could be sampled from the index to check field population")
    else:
        if not vector_populated:
            problems.append("one or more sampled documents have an empty chunk_vector")
        if not text_populated:
            problems.append("one or more sampled documents have an empty text field")
        if not source_populated:
            problems.append("one or more sampled documents have an empty source_file field")
    if not ids_unique:
        problems.append("duplicate chunk_id values found among the sampled documents")

    return IndexContentReport(
        index_name=index_name, expected_chunk_count=expected_chunk_count, live_document_count=live_count,
        sampled_documents=len(sampled), vector_field_populated=vector_populated,
        text_field_populated=text_populated, source_metadata_populated=source_populated,
        chunk_ids_unique_in_sample=ids_unique, problems=problems,
    )
