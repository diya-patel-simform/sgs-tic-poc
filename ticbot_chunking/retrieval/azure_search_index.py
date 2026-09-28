"""Azure AI Search index: schema, creation, and chunk upload — for the
single `AZURE_SEARCH_INDEX_NAME` index used by the retrieval/citation-accuracy
eval (`scripts/build_index.py` + `scripts/run_eval.py`, `retrieval/qa_eval.py`).

This is a different index from `ticbot_chunking/search/` (created by
`scripts/create_search_index.py`), which builds four separate,
strategy-specific indexes (ticbot-chunks-fixed/recursive/structure/hybrid)
so the four chunking strategies can be compared fairly. This module's
single index is for the QA/citation eval instead, and — unlike
`ticbot_chunking/search/` — this module already performs embedding
generation and document upload (`upload_chunks`); it predates the
"index-schema-only, no embeddings/upload yet" step and is left as-is here
since the eval step isn't part of it.

Hybrid retrieval (keyword + vector, fused by Reciprocal Rank Fusion) is
Azure AI Search's built-in behavior when a query supplies both `search_text`
and a vector query in the same call — see section 8 of
TICbot_Chunking_Strategy_Answers.md.
"""
from __future__ import annotations

import hashlib

from ticbot_chunking.config import SEARCH
from ticbot_chunking.metadata.schema import Chunk
from ticbot_chunking.retrieval.embeddings import EMBEDDING_DIMENSIONS, embed_texts

VECTOR_PROFILE_NAME = "ticbot-hnsw-profile"
VECTOR_ALGO_NAME = "ticbot-hnsw"


def _require_index_client():
    if not SEARCH.is_configured:
        raise RuntimeError(
            "Azure AI Search is not configured. Set AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_ADMIN_KEY "
            "(see .env.example)."
        )
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient

    return SearchIndexClient(endpoint=SEARCH.endpoint, credential=AzureKeyCredential(SEARCH.admin_key))


def build_index_schema():
    from azure.search.documents.indexes.models import (
        HnswAlgorithmConfiguration,
        SearchableField,
        SearchField,
        SearchFieldDataType,
        SearchIndex,
        SimpleField,
        VectorSearch,
        VectorSearchProfile,
    )

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SearchField(
            name="content_vector", type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True, vector_search_dimensions=EMBEDDING_DIMENSIONS,
            vector_search_profile_name=VECTOR_PROFILE_NAME,
        ),
        SimpleField(name="doc_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="chunk_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="source_file", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="pages", type=SearchFieldDataType.Collection(SearchFieldDataType.Int32), filterable=True),
        SimpleField(name="sheet", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="cell_range", type=SearchFieldDataType.String),
        SearchableField(name="section_path", type=SearchFieldDataType.String),
        SimpleField(name="section_number", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="discipline", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="material", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="lab_location", type=SearchFieldDataType.String, filterable=True, facetable=True),
        SimpleField(name="certificate_no", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="validity", type=SearchFieldDataType.String),
        SimpleField(name="access_class", type=SearchFieldDataType.String, filterable=True),
        SimpleField(name="contains_pii", type=SearchFieldDataType.Boolean, filterable=True),
        SimpleField(name="excel_table", type=SearchFieldDataType.String, filterable=True),
    ]

    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name=VECTOR_ALGO_NAME)],
        profiles=[VectorSearchProfile(name=VECTOR_PROFILE_NAME, algorithm_configuration_name=VECTOR_ALGO_NAME)],
    )

    return SearchIndex(name=SEARCH.index_name, fields=fields, vector_search=vector_search)


def create_or_update_index() -> None:
    client = _require_index_client()
    client.create_or_update_index(build_index_schema())


def _chunk_id(chunk: Chunk, idx: int) -> str:
    raw = f"{chunk.metadata.source_file}:{chunk.metadata.chunk_type}:{idx}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _to_search_document(chunk: Chunk, idx: int, vector: list[float]) -> dict:
    m = chunk.metadata
    return {
        "id": _chunk_id(chunk, idx),
        "content": chunk.text,
        "content_vector": vector,
        "doc_type": m.doc_type,
        "chunk_type": m.chunk_type,
        "source_file": m.source_file,
        "pages": m.pages or [],
        "sheet": m.sheet,
        "cell_range": m.cell_range,
        "section_path": m.section_path,
        "section_number": m.section_number,
        "discipline": m.discipline,
        "material": m.material,
        "lab_location": m.lab_location,
        "certificate_no": m.certificate_no,
        "validity": m.validity,
        "access_class": m.access_class,
        "contains_pii": m.contains_pii,
        "excel_table": m.excel_table,
    }


def upload_chunks(chunks: list[Chunk], batch_size: int = 200) -> None:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient

    client = SearchClient(endpoint=SEARCH.endpoint, index_name=SEARCH.index_name,
                           credential=AzureKeyCredential(SEARCH.admin_key))

    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        vectors = embed_texts([c.text for c in batch])
        docs = [_to_search_document(c, i + j, v) for j, (c, v) in enumerate(zip(batch, vectors))]
        client.upload_documents(documents=docs)
