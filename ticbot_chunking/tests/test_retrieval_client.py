"""Tests for the common retrieval interface
(ticbot_chunking/search/retrieval_client.py). The Azure AI Search client
and the embedding function are both injected — no real Azure service is
contacted.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ticbot_chunking.search.retrieval_client import MODES, search


def _fake_doc(chunk_id="c1", source_file="a.pdf", score=1.0, **extra):
    doc = {
        "@search.score": score, "@search.rerankerScore": None, "chunk_id": chunk_id,
        "text": "some chunk text", "chunking_strategy": "fixed", "document_type": "regulation",
        "chunk_type": "text", "source_file": source_file, "blob_path": source_file,
        "parser_used": "local_pdf", "pages": [1], "section_path": "Chapter 1", "section_number": "1.1",
        "sheet": None, "cell_range": None, "authority": None, "lab_location": None,
        "certificate_no": None, "discipline": None, "material": None, "facility": None,
    }
    doc.update(extra)
    return doc


def test_rejects_an_unknown_mode():
    with pytest.raises(ValueError, match="Unknown retrieval mode"):
        search("fixed", "bogus-mode", "query", search_client=MagicMock())


def test_keyword_mode_passes_search_text_and_no_vector_query():
    client = MagicMock()
    client.search.return_value = [_fake_doc()]
    embed_fn = MagicMock(side_effect=AssertionError("embedding must not be called for keyword mode"))

    result = search("fixed", "keyword", "arsenic limit", top_k=5, search_client=client, embed_fn=embed_fn)

    call_kwargs = client.search.call_args.kwargs
    assert call_kwargs["search_text"] == "arsenic limit"
    assert call_kwargs["vector_queries"] is None
    assert call_kwargs["top"] == 5
    assert len(result.results) == 1
    assert result.results[0].chunk_id == "c1"
    embed_fn.assert_not_called()


def test_vector_mode_embeds_the_query_and_passes_no_search_text():
    client = MagicMock()
    client.search.return_value = [_fake_doc()]
    embed_fn = MagicMock(return_value=[0.1, 0.2, 0.3])

    search("fixed", "vector", "arsenic limit", top_k=3, search_client=client, embed_fn=embed_fn)

    embed_fn.assert_called_once_with("arsenic limit")
    call_kwargs = client.search.call_args.kwargs
    assert call_kwargs["search_text"] is None
    assert call_kwargs["vector_queries"] is not None
    assert call_kwargs["vector_queries"][0].k_nearest_neighbors == 3


def test_hybrid_mode_passes_both_search_text_and_vector_query():
    client = MagicMock()
    client.search.return_value = [_fake_doc()]
    embed_fn = MagicMock(return_value=[0.1])

    search("fixed", "hybrid", "arsenic limit", search_client=client, embed_fn=embed_fn)

    call_kwargs = client.search.call_args.kwargs
    assert call_kwargs["search_text"] == "arsenic limit"
    assert call_kwargs["vector_queries"] is not None
    embed_fn.assert_called_once()


def test_filter_is_passed_through_when_given():
    client = MagicMock()
    client.search.return_value = []

    search("fixed", "keyword", "q", filter="document_type eq 'regulation'", search_client=client)

    assert client.search.call_args.kwargs["filter"] == "document_type eq 'regulation'"


def test_filter_is_omitted_when_not_given():
    client = MagicMock()
    client.search.return_value = []

    search("fixed", "keyword", "q", search_client=client)

    assert "filter" not in client.search.call_args.kwargs


def test_result_preserves_every_citation_and_metadata_field():
    client = MagicMock()
    client.search.return_value = [_fake_doc(
        source_file="nabl.pdf", sheet="Sheet1", cell_range="A1:B2", authority="FSSAI",
        lab_location="Mumbai", certificate_no="TC-5378", discipline="Chemical", material="Water",
        facility="Permanent Facility",
    )]

    result = search("hybrid", "keyword", "q", search_client=client)
    r = result.results[0]

    assert r.source_file == "nabl.pdf"
    assert r.sheet == "Sheet1"
    assert r.cell_range == "A1:B2"
    assert r.authority == "FSSAI"
    assert r.lab_location == "Mumbai"
    assert r.certificate_no == "TC-5378"
    assert r.discipline == "Chemical"
    assert r.material == "Water"
    assert r.facility == "Permanent Facility"


def test_ranks_are_assigned_in_result_order_starting_at_one():
    client = MagicMock()
    client.search.return_value = [_fake_doc(chunk_id="c1"), _fake_doc(chunk_id="c2"), _fake_doc(chunk_id="c3")]

    result = search("fixed", "keyword", "q", search_client=client)

    assert [r.rank for r in result.results] == [1, 2, 3]
    assert [r.chunk_id for r in result.results] == ["c1", "c2", "c3"]


def test_empty_results_are_handled_without_error():
    client = MagicMock()
    client.search.return_value = []

    result = search("fixed", "keyword", "q", search_client=client)

    assert result.results == []


def test_top_k_is_forwarded_to_the_client():
    client = MagicMock()
    client.search.return_value = []

    search("fixed", "keyword", "q", top_k=10, search_client=client)

    assert client.search.call_args.kwargs["top"] == 10


def test_index_name_defaults_to_the_strategy_mapping():
    client = MagicMock()
    client.search.return_value = []

    result = search("structure_aware", "keyword", "q", search_client=client)

    assert result.index_name == "ticbot-chunks-structure"


def test_to_dict_round_trips_query_and_results():
    client = MagicMock()
    client.search.return_value = [_fake_doc()]

    result = search("fixed", "keyword", "q", search_client=client)
    d = result.to_dict()

    assert d["query"] == "q"
    assert d["strategy"] == "fixed"
    assert d["mode"] == "keyword"
    assert len(d["results"]) == 1
    assert d["results"][0]["chunk_id"] == "c1"


def test_all_three_modes_are_exposed():
    assert set(MODES) == {"keyword", "vector", "hybrid"}


def test_query_result_from_dict_round_trips_to_dict():
    from ticbot_chunking.search.retrieval_client import RetrievalQueryResult

    client = MagicMock()
    client.search.return_value = [_fake_doc()]
    original = search("fixed", "keyword", "q", search_client=client)

    reconstructed = RetrievalQueryResult.from_dict(original.to_dict())

    assert reconstructed.to_dict() == original.to_dict()
    assert reconstructed.results[0].chunk_id == "c1"
    assert isinstance(reconstructed.results[0].rank, int)
