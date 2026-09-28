"""Azure AI Search index schema for the four strategy-specific chunk
indexes (ticbot-chunks-<strategy>).

Schema-only, by design: this module builds `SearchIndex` objects and
validates them. It never uploads documents, generates embeddings, or runs
queries — see `scripts/create_search_index.py` for index creation, and the
project README for why those come later.

Field list is deliberately limited to what `ticbot_chunking/metadata/schema.py`
(ChunkMetadata) actually produces, plus what Azure Search itself requires
(exactly one key field, a vector field) or what the task explicitly asked
for even though it isn't a literal ChunkMetadata attribute:
  - chunk_id: synthetic key, since ChunkMetadata has no unique id of its own.
  - chunking_strategy: which of the four experiment outputs a chunk came
    from — set by the loader from the source chunks.jsonl path, since
    ChunkMetadata.strategy is only populated by the hybrid strategy today.
  - blob_path: an alias of ChunkMetadata.source_file, kept as a separate
    index field because the task calls for both names explicitly.
  - document_type / parser_used: ChunkMetadata's `doc_type` / `parser`,
    renamed for the index's external field names.
Every other field is a direct, same-named copy of a ChunkMetadata field.
"""
from __future__ import annotations

from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    HnswParameters,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    VectorSearch,
    VectorSearchAlgorithmMetric,
    VectorSearchProfile,
)

VECTOR_FIELD_NAME = "chunk_vector"
VECTOR_PROFILE_NAME = "ticbot-vector-profile"
VECTOR_ALGORITHM_NAME = "ticbot-hnsw"
SEMANTIC_CONFIG_NAME = "ticbot-semantic-config"

KEY_FIELD_NAME = "chunk_id"
TEXT_FIELD_NAME = "text"

# strategy -> its dedicated index name (matches scripts/run_chunking_experiments.STRATEGIES)
STRATEGY_INDEX_NAMES = {
    "fixed": "ticbot-chunks-fixed",
    "recursive": "ticbot-chunks-recursive",
    "structure_aware": "ticbot-chunks-structure",
    "hybrid": "ticbot-chunks-hybrid",
}


def _field(name: str, type_: str = SearchFieldDataType.String, *, searchable: bool = False,
           filterable: bool = False, sortable: bool = False, facetable: bool = False,
           retrievable: bool = True) -> SearchField:
    return SearchField(name=name, type=type_, searchable=searchable, filterable=filterable,
                        sortable=sortable, facetable=facetable, retrievable=retrievable)


def build_key_field() -> SearchField:
    return SearchField(name=KEY_FIELD_NAME, type=SearchFieldDataType.String, key=True,
                        searchable=False, filterable=True, sortable=False, facetable=False, retrievable=True)


def build_text_field() -> SearchField:
    """The full-text-searchable chunk content — the one field every keyword
    and semantic query targets."""
    return _field(TEXT_FIELD_NAME, searchable=True, retrievable=True)


def build_embed_text_field() -> SearchField:
    """The short, spell-normalized, embed-only copy of a chunk (Chunk.embed_text)
    — stored for debuggability/re-embedding, not itself searched (the
    `text` field above remains the one full-text/semantic-search target)."""
    return _field("embed_text", searchable=False, retrievable=True)


def build_metadata_fields() -> list[SearchField]:
    """One field per requirement's citation/filtering list. Categorical,
    low-cardinality fields (doc/chunk type, parser, authority, discipline,
    material, facility, access_class) are filterable+facetable+sortable for
    faceted browsing and comparison; free-text provenance (section_path) is
    searchable instead; everything else is filterable/retrievable only —
    exact-match citation data, not something to facet or full-text search.
    Nothing here is searchable by default except `section_path` and the
    dedicated `text` field."""
    return [
        _field("chunking_strategy", filterable=True, facetable=True, sortable=True),
        _field("document_type", filterable=True, facetable=True, sortable=True),
        _field("chunk_type", filterable=True, facetable=True, sortable=True),
        _field("source_file", filterable=True, sortable=True),
        _field("blob_path", filterable=True, sortable=True),
        _field("parser_used", filterable=True, facetable=True, sortable=True),
        _field("pages", type_=SearchFieldDataType.Collection(SearchFieldDataType.Int32), filterable=True),
        _field("page_start", type_=SearchFieldDataType.Int32, filterable=True, sortable=True),
        _field("page_end", type_=SearchFieldDataType.Int32, filterable=True, sortable=True),
        _field("printed_page_label", filterable=True),
        _field("doc_title", searchable=True),
        _field("section_path", searchable=True),
        _field("section_number", filterable=True, sortable=True),
        _field("authority", filterable=True, facetable=True),
        _field("lab_location", filterable=True, facetable=True),
        _field("certificate_no", filterable=True),
        _field("discipline", filterable=True, facetable=True),
        _field("material", filterable=True, facetable=True),
        _field("facility", filterable=True, facetable=True),
        _field("sheet", filterable=True),
        _field("cell_range", filterable=True),
        _field("access_class", filterable=True, facetable=True),
        _field("contains_pii", type_=SearchFieldDataType.Boolean, filterable=True),
    ]


def build_vector_field(dimensions: int) -> SearchField:
    if not dimensions or dimensions <= 0:
        raise ValueError(
            f"Invalid vector dimension: {dimensions!r}. Set AZURE_OPENAI_EMBEDDING_DIMENSIONS "
            "explicitly, or use a recognized AZURE_OPENAI_EMBEDDING_DEPLOYMENT name (see "
            "config.KNOWN_EMBEDDING_DIMENSIONS) — the index schema will not guess a wrong "
            "vector width."
        )
    return SearchField(
        name=VECTOR_FIELD_NAME,
        type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
        searchable=True,
        retrievable=True,
        filterable=False,
        sortable=False,
        facetable=False,
        vector_search_dimensions=dimensions,
        vector_search_profile_name=VECTOR_PROFILE_NAME,
    )


def build_vector_search() -> VectorSearch:
    return VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name=VECTOR_ALGORITHM_NAME,
                parameters=HnswParameters(metric=VectorSearchAlgorithmMetric.COSINE),
            )
        ],
        profiles=[
            VectorSearchProfile(name=VECTOR_PROFILE_NAME, algorithm_configuration_name=VECTOR_ALGORITHM_NAME)
        ],
    )


def build_semantic_search() -> SemanticSearch:
    """Ready for later semantic re-ranking (title = the human-readable
    section trail, content = the chunk text, keywords = the section
    number) — not used by anything in this step, since retrieval isn't
    implemented yet."""
    return SemanticSearch(
        default_configuration_name=SEMANTIC_CONFIG_NAME,
        configurations=[
            SemanticConfiguration(
                name=SEMANTIC_CONFIG_NAME,
                prioritized_fields=SemanticPrioritizedFields(
                    title_field=SemanticField(field_name="section_path"),
                    content_fields=[SemanticField(field_name=TEXT_FIELD_NAME)],
                    keywords_fields=[SemanticField(field_name="section_number")],
                ),
            )
        ],
    )


def build_index(index_name: str, strategy: str, vector_dimensions: int) -> SearchIndex:
    fields = [
        build_key_field(),
        build_text_field(),
        build_embed_text_field(),
        *build_metadata_fields(),
        build_vector_field(vector_dimensions),
    ]
    return SearchIndex(
        name=index_name,
        fields=fields,
        vector_search=build_vector_search(),
        semantic_search=build_semantic_search(),
        description=f"TICBot chunks — {strategy} chunking strategy",
    )
