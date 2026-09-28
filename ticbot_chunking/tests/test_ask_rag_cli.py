"""Tests for scripts/ask_rag.py's own logic (argument parsing, output
formatting) with the underlying `answer()` call monkeypatched — no real
Azure service is contacted.
"""
from __future__ import annotations

import json
import sys
from unittest.mock import patch

from ticbot_chunking.rag.response import Citation, RagResponse
from ticbot_chunking.scripts import ask_rag
from ticbot_chunking.search.retrieval_client import RetrievalResult


def _fake_response():
    chunk = RetrievalResult(
        rank=1, score=0.9, reranker_score=None, chunk_id="c1", text="chunk text", chunking_strategy="hybrid",
        source_file="a.pdf", blob_path="a.pdf", parser_used="local_pdf", pages=[2], section_path=None,
        section_number=None, chunk_type="text", document_type="brochure", sheet=None, cell_range=None,
        authority=None, lab_location=None, certificate_no=None, discipline=None, material=None, facility=None,
    )
    citation = Citation(chunk_id="c1", source_file="a.pdf", document_type="brochure", page="2", sheet=None,
                         cell_range=None, section=None, certificate_no=None, lab_location=None, discipline=None,
                         material=None, score=0.9)
    return RagResponse(query="q", strategy="hybrid", retrieval_mode="hybrid", top_k=5, answer="The answer [1].",
                        citations=[citation], retrieved_chunks=[chunk], context_used=True,
                        retrieval_latency_seconds=0.1, llm_latency_seconds=0.5)


def test_human_output_includes_answer_citations_and_sources(capsys):
    with patch.object(ask_rag, "answer", return_value=_fake_response()):
        with patch.object(sys, "argv", ["prog", "--question", "q"]):
            ask_rag.main()

    out = capsys.readouterr().out
    assert "The answer [1]." in out
    assert "a.pdf" in out
    assert "page: 2" in out
    assert "c1" not in out.split("Citations:")[0]  # chunk_id isn't shown in the human citation line itself


def test_json_output_is_valid_and_includes_full_response(capsys):
    with patch.object(ask_rag, "answer", return_value=_fake_response()):
        with patch.object(sys, "argv", ["prog", "--question", "q", "--json"]):
            ask_rag.main()

    parsed = json.loads(capsys.readouterr().out)
    assert parsed["answer"] == "The answer [1]."
    assert parsed["citations"][0]["source_file"] == "a.pdf"
    assert parsed["retrieved_chunks"][0]["chunk_id"] == "c1"


def test_defaults_to_hybrid_strategy_and_mode():
    with patch.object(ask_rag, "answer", return_value=_fake_response()) as mock_answer:
        with patch.object(sys, "argv", ["prog", "--question", "q"]):
            ask_rag.main()

    mock_answer.assert_called_once_with("q", strategy="hybrid", mode="hybrid", top_k=5, filter=None, index_name=None)


def test_mode_top_k_and_strategy_flags_are_forwarded():
    with patch.object(ask_rag, "answer", return_value=_fake_response()) as mock_answer:
        args = ["prog", "--question", "q", "--mode", "vector", "--top-k", "10", "--strategy", "fixed"]
        with patch.object(sys, "argv", args):
            ask_rag.main()

    mock_answer.assert_called_once_with("q", strategy="fixed", mode="vector", top_k=10, filter=None, index_name=None)


def test_index_override_is_forwarded():
    with patch.object(ask_rag, "answer", return_value=_fake_response()) as mock_answer:
        args = ["prog", "--question", "q", "--index", "ticbot-chunks-hybrid-updated"]
        with patch.object(sys, "argv", args):
            ask_rag.main()

    mock_answer.assert_called_once_with("q", strategy="hybrid", mode="hybrid", top_k=5, filter=None,
                                         index_name="ticbot-chunks-hybrid-updated")


def test_empty_citations_are_reported_as_none(capsys):
    response = _fake_response()
    response.citations = []
    with patch.object(ask_rag, "answer", return_value=response):
        with patch.object(sys, "argv", ["prog", "--question", "q"]):
            ask_rag.main()

    out = capsys.readouterr().out
    assert "Citations:\n  (none)" in out
