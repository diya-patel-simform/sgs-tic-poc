"""Tests for scripts/search_chunks.py's own logic (argument parsing,
output formatting) with the underlying `search()` call monkeypatched —
no real Azure service is contacted.
"""
from __future__ import annotations

import json
import sys
from unittest.mock import patch

from ticbot_chunking.scripts import search_chunks
from ticbot_chunking.search.retrieval_client import RetrievalQueryResult, RetrievalResult


def _fake_result():
    r = RetrievalResult(
        rank=1, score=1.23, reranker_score=None, chunk_id="c1", text="some real chunk text",
        chunking_strategy="hybrid", source_file="a.pdf", blob_path="a.pdf", parser_used="local_pdf",
        pages=[3], section_path="Chapter 1", section_number="1.1", chunk_type="text",
        document_type="regulation", sheet=None, cell_range=None, authority=None, lab_location=None,
        certificate_no=None, discipline=None, material=None, facility=None,
    )
    return RetrievalQueryResult(query="q", strategy="hybrid", index_name="ticbot-chunks-hybrid",
                                 mode="hybrid", top_k=5, filter=None, latency_seconds=0.2, results=[r])


def test_json_output_is_valid_and_round_trips(capsys):
    with patch.object(search_chunks, "search", return_value=_fake_result()):
        test_args = ["prog", "--strategy", "hybrid", "--mode", "hybrid", "--query", "q", "--json"]
        with patch.object(sys, "argv", test_args):
            search_chunks.main()

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["strategy"] == "hybrid"
    assert parsed["results"][0]["chunk_id"] == "c1"


def test_human_output_includes_key_fields(capsys):
    with patch.object(search_chunks, "search", return_value=_fake_result()):
        test_args = ["prog", "--strategy", "hybrid", "--mode", "hybrid", "--query", "q"]
        with patch.object(sys, "argv", test_args):
            search_chunks.main()

    out = capsys.readouterr().out
    assert "a.pdf" in out
    assert "c1" in out
    assert "some real chunk text" in out


def test_top_k_and_filter_are_forwarded_to_search():
    with patch.object(search_chunks, "search", return_value=_fake_result()) as mock_search:
        test_args = ["prog", "--strategy", "fixed", "--mode", "vector", "--query", "q",
                     "--top-k", "10", "--filter", "document_type eq 'regulation'", "--json"]
        with patch.object(sys, "argv", test_args):
            search_chunks.main()

    mock_search.assert_called_once_with("fixed", "vector", "q", top_k=10,
                                         filter="document_type eq 'regulation'", index_name=None)
