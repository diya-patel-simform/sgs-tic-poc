"""Maps one row of a strategy's chunks.jsonl (`{"text": ..., "metadata": {...}}`,
as written by `Chunk.to_dict()` — see `metadata/schema.py`) plus its
embedding vector into an Azure AI Search document, using the exact field
names `ticbot_chunking/search/schema.py` defines. Preserves every
ChunkMetadata field the schema has room for; nothing is reconstructed or
guessed here — a field that's absent from `row["metadata"]` (because
`ChunkMetadata.to_dict()` omits `None`/`[]` values) is simply left out of
the resulting document rather than sent as a fabricated value.
"""
from __future__ import annotations

from typing import Any

from ticbot_chunking.search.chunk_id import compute_chunk_id
from ticbot_chunking.search.schema import VECTOR_FIELD_NAME

# ChunkMetadata key -> Azure AI Search field name, for the fields the index
# schema renamed. Every other metadata field keeps its own name.
_RENAMED_METADATA_FIELDS = {
    "doc_type": "document_type",
    "parser": "parser_used",
}

# Metadata fields copied through unchanged (same name in ChunkMetadata and
# in the index schema). Deliberately excludes "strategy" (the internal,
# hybrid-only field) in favor of the caller-supplied `strategy` argument,
# which is reliable for all four strategies — see chunk_id.py's docstring.
_DIRECT_METADATA_FIELDS = (
    "chunk_type", "source_file", "pages", "page_start", "page_end", "printed_page_label", "doc_title",
    "section_path", "section_number",
    "authority", "lab_location", "certificate_no", "discipline", "material",
    "facility", "sheet", "cell_range", "access_class", "contains_pii",
)


def build_search_document(row: dict[str, Any], strategy: str, index_in_file: int,
                           vector: list[float]) -> dict[str, Any]:
    """`row` is one already-parsed line of chunks.jsonl. `index_in_file` is
    this row's 0-based position in that file — part of the stable chunk_id,
    so it must match the row's actual position (don't call this on a
    filtered/reordered subset without preserving original indices)."""
    metadata = row["metadata"]
    text = row["text"]
    source_file = metadata.get("source_file", "")

    doc: dict[str, Any] = {
        "chunk_id": compute_chunk_id(strategy, source_file, index_in_file, text),
        "text": text,
        "embed_text": row.get("embed_text"),  # short, spell-normalized embed-only copy — see Chunk.embed_text
        "chunking_strategy": strategy,
        "blob_path": source_file,
        VECTOR_FIELD_NAME: vector,
    }
    for metadata_key, field_name in _RENAMED_METADATA_FIELDS.items():
        doc[field_name] = metadata.get(metadata_key)
    for field_name in _DIRECT_METADATA_FIELDS:
        doc[field_name] = metadata.get(field_name)

    # Omit (not null-out) anything ChunkMetadata.to_dict() didn't have —
    # keeps the uploaded document's shape honest about what's actually known.
    return {k: v for k, v in doc.items() if v is not None}
