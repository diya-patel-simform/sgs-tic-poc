"""Structural validation of a (built or fetched) Azure AI Search
`SearchIndex` object against what this project's schema requires. Used both
right after `build_index(...)` (before ever calling the real service) and
against a `get_index(...)` response from a live service — same function,
same checks, so "the index we asked for" and "the index that actually
exists" are held to the same bar.
"""
from __future__ import annotations

from ticbot_chunking.search.schema import (
    KEY_FIELD_NAME,
    TEXT_FIELD_NAME,
    VECTOR_FIELD_NAME,
)

# Every non-key, non-text, non-vector field the task's citation/filtering
# requirements call for.
REQUIRED_METADATA_FIELDS = {
    "chunking_strategy", "document_type", "chunk_type", "source_file", "blob_path",
    "parser_used", "pages", "section_path", "section_number", "authority", "lab_location",
    "certificate_no", "discipline", "material", "facility", "sheet", "cell_range",
    "access_class", "contains_pii",
}

# Fields that must be filterable to support metadata filtering / citation lookups.
EXPECTED_FILTERABLE_FIELDS = REQUIRED_METADATA_FIELDS - {"section_path"}


def validate_index_schema(index, expected_dimensions: int) -> list[str]:
    """Returns a list of problems (empty means the schema is valid)."""
    problems: list[str] = []
    fields_by_name = {f.name: f for f in index.fields}

    missing = (REQUIRED_METADATA_FIELDS | {KEY_FIELD_NAME, TEXT_FIELD_NAME, VECTOR_FIELD_NAME}) - set(fields_by_name)
    if missing:
        problems.append(f"missing required field(s): {sorted(missing)}")

    key_fields = [f for f in index.fields if f.key]
    if len(key_fields) != 1:
        problems.append(f"expected exactly one key field, found {len(key_fields)}")
    elif key_fields[0].name != KEY_FIELD_NAME:
        problems.append(f"expected key field to be '{KEY_FIELD_NAME}', found '{key_fields[0].name}'")

    text_field = fields_by_name.get(TEXT_FIELD_NAME)
    if text_field is None:
        problems.append(f"missing '{TEXT_FIELD_NAME}' field")
    elif not text_field.searchable:
        problems.append(f"'{TEXT_FIELD_NAME}' field must be searchable")

    vector_field = fields_by_name.get(VECTOR_FIELD_NAME)
    if vector_field is None:
        problems.append(f"missing vector field '{VECTOR_FIELD_NAME}'")
    else:
        if vector_field.vector_search_dimensions != expected_dimensions:
            problems.append(
                f"vector field dimension mismatch: expected {expected_dimensions}, "
                f"got {vector_field.vector_search_dimensions}"
            )
        if not vector_field.vector_search_profile_name:
            problems.append("vector field is missing a vector_search_profile_name")

    if not getattr(index, "vector_search", None) or not index.vector_search.profiles:
        problems.append("index is missing a vector search configuration/profile")
    elif vector_field is not None:
        profile_names = {p.name for p in index.vector_search.profiles}
        if vector_field.vector_search_profile_name not in profile_names:
            problems.append(
                f"vector field references profile '{vector_field.vector_search_profile_name}', "
                f"which isn't defined in vector_search.profiles ({sorted(profile_names)})"
            )

    for name in EXPECTED_FILTERABLE_FIELDS:
        f = fields_by_name.get(name)
        if f is not None and not f.filterable:
            problems.append(f"'{name}' should be filterable")

    if "section_path" in fields_by_name and not fields_by_name["section_path"].searchable:
        problems.append("'section_path' should be searchable")

    return problems
