"""Test for scripts/run_retrieval_eval.py's own main() logic, with
run_evaluation's underlying search_fn effectively mocked via the injected
default in eval_runner — here we monkeypatch retrieval_client.search
itself (the true network boundary) so no real Azure call happens.
"""
from __future__ import annotations

import json
import sys
from unittest.mock import patch

from ticbot_chunking.scripts import run_retrieval_eval
from ticbot_chunking.search.retrieval_client import RetrievalQueryResult, RetrievalResult


def _write_questions(tmp_path, n=2):
    path = tmp_path / "questions.jsonl"
    with open(path, "w") as f:
        for i in range(1, n + 1):
            row = {
                "question_id": f"Q{i:03d}", "category": "A", "question": f"question {i}",
                "expected_source_file": "a.pdf", "expected_pages": [1], "expected_sheet": None,
                "expected_cell_range": None, "expected_metadata": None, "suggested_filter": None,
                "ground_truth_status": "available", "notes": "verified",
            }
            f.write(json.dumps(row) + "\n")
    return path


def _fake_search(strategy, mode, query, top_k=5, filter=None):
    r = RetrievalResult(
        rank=1, score=1.0, reranker_score=None, chunk_id="c1", text="t", chunking_strategy=strategy,
        source_file="a.pdf", blob_path="a.pdf", parser_used="local_pdf", pages=[1], section_path=None,
        section_number=None, chunk_type="text", document_type="regulation", sheet=None, cell_range=None,
        authority=None, lab_location=None, certificate_no=None, discipline=None, material=None, facility=None,
    )
    return RetrievalQueryResult(query=query, strategy=strategy, index_name=f"ticbot-chunks-{strategy}",
                                 mode=mode, top_k=top_k, filter=filter, latency_seconds=0.01, results=[r])


def test_full_matrix_run_produces_reports_and_raw_results(tmp_path):
    questions_path = _write_questions(tmp_path)
    results_dir = tmp_path / "results"
    report_json = tmp_path / "comparison.json"
    report_md = tmp_path / "comparison.md"

    test_args = [
        "prog", "--questions", str(questions_path), "--results-dir", str(results_dir),
        "--report-json", str(report_json), "--report-md", str(report_md),
        "--strategy", "fixed", "--strategy", "hybrid", "--mode", "keyword", "--top-k", "5",
    ]
    with patch.object(run_retrieval_eval, "search", side_effect=_fake_search):
        with patch.object(sys, "argv", test_args):
            run_retrieval_eval.main()

    assert report_json.exists()
    assert report_md.exists()
    report = json.loads(report_json.read_text())
    assert report["num_combinations_tested"] == 2  # fixed x keyword, hybrid x keyword
    assert (results_dir / "fixed" / "keyword.jsonl").exists()
    assert (results_dir / "hybrid" / "keyword.jsonl").exists()
    assert "winner" not in report
