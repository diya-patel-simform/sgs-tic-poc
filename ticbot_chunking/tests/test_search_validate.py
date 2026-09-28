"""Tests for schema validation (ticbot_chunking/search/validate.py) — run
against locally-built SearchIndex objects, never a live service."""
from __future__ import annotations

from azure.search.documents.indexes.models import SearchField, SearchFieldDataType, VectorSearch

from ticbot_chunking.search.schema import STRATEGY_INDEX_NAMES, build_index
from ticbot_chunking.search.validate import validate_index_schema


def test_a_freshly_built_index_has_no_validation_problems():
    index = build_index(STRATEGY_INDEX_NAMES["fixed"], "fixed", 3072)
    assert validate_index_schema(index, 3072) == []


def test_detects_a_missing_required_field():
    index = build_index(STRATEGY_INDEX_NAMES["fixed"], "fixed", 3072)
    index.fields = [f for f in index.fields if f.name != "discipline"]

    problems = validate_index_schema(index, 3072)
    assert any("discipline" in p for p in problems)


def test_detects_wrong_key_field_name():
    index = build_index(STRATEGY_INDEX_NAMES["fixed"], "fixed", 3072)
    for f in index.fields:
        if f.key:
            f.key = False
    index.fields.append(SearchField(name="id", type=SearchFieldDataType.String, key=True))

    problems = validate_index_schema(index, 3072)
    assert any("key field" in p for p in problems)


def test_detects_non_searchable_text_field():
    index = build_index(STRATEGY_INDEX_NAMES["fixed"], "fixed", 3072)
    for f in index.fields:
        if f.name == "text":
            f.searchable = False

    problems = validate_index_schema(index, 3072)
    assert any("'text'" in p and "searchable" in p for p in problems)


def test_detects_vector_dimension_mismatch():
    index = build_index(STRATEGY_INDEX_NAMES["fixed"], "fixed", 3072)

    problems = validate_index_schema(index, 1536)  # expecting a different dimension than it was built with
    assert any("dimension mismatch" in p for p in problems)


def test_detects_missing_vector_search_configuration():
    index = build_index(STRATEGY_INDEX_NAMES["fixed"], "fixed", 3072)
    index.vector_search = None

    problems = validate_index_schema(index, 3072)
    assert any("vector search configuration" in p for p in problems)


def test_detects_vector_field_referencing_an_undefined_profile():
    index = build_index(STRATEGY_INDEX_NAMES["fixed"], "fixed", 3072)
    index.vector_search = VectorSearch(profiles=[], algorithms=[])

    problems = validate_index_schema(index, 3072)
    assert any("vector search configuration" in p or "profile" in p for p in problems)


def test_detects_a_non_filterable_metadata_field():
    index = build_index(STRATEGY_INDEX_NAMES["fixed"], "fixed", 3072)
    for f in index.fields:
        if f.name == "document_type":
            f.filterable = False

    problems = validate_index_schema(index, 3072)
    assert any("'document_type' should be filterable" in p for p in problems)


def test_detects_non_searchable_section_path():
    index = build_index(STRATEGY_INDEX_NAMES["fixed"], "fixed", 3072)
    for f in index.fields:
        if f.name == "section_path":
            f.searchable = False

    problems = validate_index_schema(index, 3072)
    assert any("section_path" in p and "searchable" in p for p in problems)
