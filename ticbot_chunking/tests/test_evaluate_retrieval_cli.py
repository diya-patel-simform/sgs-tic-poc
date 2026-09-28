"""Tests for scripts/evaluate_retrieval.py's own logic: reading saved raw
results (no Azure call at all) and the live-query path with `search`
monkeypatched. No real Azure service is contacted either way.
"""
from __future__ import annotations

import json
import sys
from unittest.mock import patch

import pytest

from ticbot_chunking.scripts import evaluate_retrieval
from ticbot_chunking.search.retrieval_client import RetrievalQueryResult, RetrievalResult


def _write_questions(tmp_path):
    path = tmp_path / "questions.jsonl"
    row = {
        "question_id": "Q001", "category": "A", "question": "Where is SGS Molecular located?",
        "expected_source_file": "a.pdf", "expected_pages": [2], "expected_sheet": None,
        "expected_cell_range": None, "expected_metadata": None, "suggested_filter": None,
        "ground_truth_status": "available", "notes": "verified",
    }
    path.write_text(json.dumps(row) + "\n")
    return path


def _fake_result(strategy, mode):
    r = RetrievalResult(
        rank=1, score=1.0, reranker_score=None, chunk_id="c1", text="chunk text", chunking_strategy=strategy,
        source_file="a.pdf", blob_path="a.pdf", parser_used="local_pdf", pages=[2], section_path=None,
        section_number=None, chunk_type="text", document_type="brochure", sheet=None, cell_range=None,
        authority=None, lab_location=None, certificate_no=None, discipline=None, material=None, facility=None,
    )
    return RetrievalQueryResult(query="q", strategy=strategy, index_name=f"ticbot-chunks-{strategy}", mode=mode,
                                 top_k=5, filter=None, latency_seconds=0.1, results=[r])


def test_unknown_question_id_raises_system_exit(tmp_path):
    questions_path = _write_questions(tmp_path)
    test_args = ["prog", "--question-id", "Q999", "--questions", str(questions_path)]
    with patch.object(sys, "argv", test_args):
        with pytest.raises(SystemExit):
            evaluate_retrieval.main()


def test_live_query_path_calls_search_for_every_strategy_and_mode(tmp_path, capsys):
    questions_path = _write_questions(tmp_path)
    calls = []

    def fake_search(strategy, mode, query, top_k=5, filter=None):
        calls.append((strategy, mode))
        return _fake_result(strategy, mode)

    with patch.object(evaluate_retrieval, "search", side_effect=fake_search):
        test_args = ["prog", "--question-id", "Q001", "--questions", str(questions_path)]
        with patch.object(sys, "argv", test_args):
            evaluate_retrieval.main()

    from ticbot_chunking.scripts.run_chunking_experiments import STRATEGIES
    from ticbot_chunking.search.retrieval_client import MODES
    assert len(calls) == len(STRATEGIES) * len(MODES)
    out = capsys.readouterr().out
    assert "Q001" in out
    assert "a.pdf" in out


def test_reads_from_saved_results_dir_without_calling_search(tmp_path, capsys):
    questions_path = _write_questions(tmp_path)
    results_dir = tmp_path / "results"
    (results_dir / "fixed").mkdir(parents=True)
    record = _fake_result("fixed", "keyword").to_dict()
    record["question_id"] = "Q001"
    (results_dir / "fixed" / "keyword.jsonl").write_text(json.dumps(record) + "\n")

    with patch.object(evaluate_retrieval, "search") as mock_search:
        test_args = ["prog", "--question-id", "Q001", "--questions", str(questions_path),
                     "--mode", "keyword", "--from-results-dir", str(results_dir)]
        with patch.object(sys, "argv", test_args):
            evaluate_retrieval.main()

    mock_search.assert_not_called()
    out = capsys.readouterr().out
    assert "c1" in out
