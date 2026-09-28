"""Tests for `infer_printed_page_labels` (metadata/classifier.py) — the
generic, filename-driven fallback for a chunk's printed page label."""
from __future__ import annotations

from ticbot_chunking.metadata.classifier import infer_printed_page_labels


def test_resolves_the_real_molecular_catalog_filename_suffix():
    labels = infer_printed_page_labels("SGS_Molecular_Catalog_pages_3-4-12.pdf", [1, 2, 3])
    assert labels == {1: "3", 2: "4", 3: "12"}


def test_resolves_the_real_health_nutrition_filename_suffix():
    labels = infer_printed_page_labels("SGS_Health_Nutrition_pages_2-5-6-9-10.pdf", [1, 2, 3, 4, 5])
    assert labels == {1: "2", 2: "5", 3: "6", 4: "9", 5: "10"}


def test_returns_none_when_filename_does_not_match_the_convention():
    assert infer_printed_page_labels("random_document.pdf", [1, 2, 3]) is None


def test_returns_none_when_page_count_encoded_does_not_match_physical_pages():
    # "pages_1-5" is ambiguous here (a 2-page excerpt of pages 1 and 5, vs.
    # a contiguous 5-page range) for a genuinely 5-page physical file —
    # safer to decline than guess which.
    assert infer_printed_page_labels("Contaminants_Regulations_pages_1-5.pdf", [1, 2, 3, 4, 5]) is None


def test_returns_none_for_empty_physical_pages_list():
    assert infer_printed_page_labels("SGS_Molecular_Catalog_pages_3-4-12.pdf", []) is None
