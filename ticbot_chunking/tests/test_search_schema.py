"""Tests for the Azure AI Search index schema builder
(ticbot_chunking/search/schema.py). Builds SearchIndex objects only — never
touches a real service.
"""
from __future__ import annotations

import pytest
from azure.search.documents.indexes.models import SearchFieldDataType

from ticbot_chunking.search.schema import (
    KEY_FIELD_NAME,
    STRATEGY_INDEX_NAMES,
    TEXT_FIELD_NAME,
    VECTOR_FIELD_NAME,
    VECTOR_PROFILE_NAME,
    build_index,
    build_metadata_fields,
    build_vector_field,
    build_vector_search,
)

EXPECTED_METADATA_FIELD_NAMES = {
    "chunking_strategy", "document_type", "chunk_type", "source_file", "blob_path",
    "parser_used", "pages", "page_start", "page_end", "printed_page_label", "doc_title",
    "section_path", "section_number", "authority", "lab_location",
    "certificate_no", "discipline", "material", "facility", "sheet", "cell_range",
    "access_class", "contains_pii",
}


def test_strategy_index_names_cover_all_four_strategies_with_requested_names():
    assert STRATEGY_INDEX_NAMES == {
        "fixed": "ticbot-chunks-fixed",
        "recursive": "ticbot-chunks-recursive",
        "structure_aware": "ticbot-chunks-structure",
        "hybrid": "ticbot-chunks-hybrid",
    }


def test_build_metadata_fields_covers_every_requested_field_exactly_once():
    fields = build_metadata_fields()
    names = [f.name for f in fields]
    assert set(names) == EXPECTED_METADATA_FIELD_NAMES
    assert len(names) == len(set(names))  # no duplicates


def test_build_metadata_fields_categorical_fields_are_filterable_facetable_sortable():
    fields = {f.name: f for f in build_metadata_fields()}
    for name in ("chunking_strategy", "document_type", "chunk_type", "parser_used"):
        f = fields[name]
        assert f.filterable is True
        assert f.facetable is True
        assert f.sortable is True
        assert f.searchable is False, f"{name} should not be searchable by default"


def test_build_metadata_fields_pages_is_a_filterable_int_collection():
    fields = {f.name: f for f in build_metadata_fields()}
    pages = fields["pages"]
    assert pages.type == SearchFieldDataType.Collection(SearchFieldDataType.Int32)
    assert pages.filterable is True


def test_build_metadata_fields_contains_pii_is_a_filterable_boolean():
    fields = {f.name: f for f in build_metadata_fields()}
    f = fields["contains_pii"]
    assert f.type == SearchFieldDataType.Boolean
    assert f.filterable is True


def test_build_metadata_fields_section_path_is_searchable_not_filterable():
    fields = {f.name: f for f in build_metadata_fields()}
    f = fields["section_path"]
    assert f.searchable is True
    assert f.filterable is False


def test_not_every_field_is_searchable_by_default():
    fields = build_metadata_fields()
    searchable_names = {f.name for f in fields if f.searchable}
    # Only the free-text provenance fields should be searchable among metadata fields.
    assert searchable_names == {"section_path", "doc_title"}


def test_build_vector_field_sets_dimension_and_profile():
    field = build_vector_field(3072)
    assert field.name == VECTOR_FIELD_NAME
    assert field.type == SearchFieldDataType.Collection(SearchFieldDataType.Single)
    assert field.vector_search_dimensions == 3072
    assert field.vector_search_profile_name == VECTOR_PROFILE_NAME
    assert field.searchable is True


@pytest.mark.parametrize("bad_dimension", [0, -1, None])
def test_build_vector_field_rejects_invalid_dimensions(bad_dimension):
    with pytest.raises(ValueError):
        build_vector_field(bad_dimension)


def test_build_vector_search_profile_references_a_defined_algorithm():
    vs = build_vector_search()
    algorithm_names = {a.name for a in vs.algorithms}
    for profile in vs.profiles:
        assert profile.algorithm_configuration_name in algorithm_names


@pytest.mark.parametrize("strategy", ["fixed", "recursive", "structure_aware", "hybrid"])
def test_build_index_for_each_strategy_has_key_text_metadata_and_vector_fields(strategy):
    index_name = STRATEGY_INDEX_NAMES[strategy]
    index = build_index(index_name, strategy, 3072)

    assert index.name == index_name
    field_names = {f.name for f in index.fields}
    assert field_names == (
        EXPECTED_METADATA_FIELD_NAMES | {KEY_FIELD_NAME, TEXT_FIELD_NAME, "embed_text", VECTOR_FIELD_NAME}
    )

    key_fields = [f for f in index.fields if f.key]
    assert len(key_fields) == 1
    assert key_fields[0].name == KEY_FIELD_NAME

    assert index.vector_search is not None
    assert index.semantic_search is not None
    assert strategy in index.description


def test_build_index_does_not_mix_strategies_into_a_shared_index_name():
    names = [build_index(STRATEGY_INDEX_NAMES[s], s, 3072).name for s in STRATEGY_INDEX_NAMES]
    assert len(names) == len(set(names))
