"""Tests for the evaluation-matrix orchestrator
(ticbot_chunking/search/eval_runner.py). `search_fn` is injected — no real
Azure service is contacted.
"""
from __future__ import annotations

import json

from ticbot_chunking.search.eval_metrics import Question
from ticbot_chunking.search.eval_runner import recompute_from_saved_results, run_evaluation
from ticbot_chunking.search.retrieval_client import RetrievalQueryResult, RetrievalResult


def _question(question_id, expected_source_file="a.pdf", suggested_filter=None, ground_truth_status="available"):
    return Question(
        question_id=question_id, category="A", question=f"question for {question_id}",
        expected_source_file=expected_source_file, expected_pages=[1], expected_sheet=None,
        expected_cell_range=None, expected_metadata=None, suggested_filter=suggested_filter,
        ground_truth_status=ground_truth_status, notes="test",
    )


def _fake_search_fn(strategy, mode, query, top_k=5, filter=None):
    result = RetrievalResult(
        rank=1, score=1.0, reranker_score=None, chunk_id="c1", text="text", chunking_strategy=strategy,
        source_file="a.pdf", blob_path="a.pdf", parser_used="local_pdf", pages=[1], section_path=None,
        section_number=None, chunk_type="text", document_type="regulation", sheet=None, cell_range=None,
        authority=None, lab_location=None, certificate_no=None, discipline=None, material=None, facility=None,
    )
    return RetrievalQueryResult(query=query, strategy=strategy, index_name=f"ticbot-chunks-{strategy}",
                                 mode=mode, top_k=top_k, filter=filter, latency_seconds=0.05, results=[result])


def test_runs_every_question_against_every_strategy_and_mode(tmp_path):
    questions = [_question("Q001"), _question("Q002")]
    strategies = ["fixed", "hybrid"]
    modes = ["keyword", "vector"]

    calls = []

    def counting_search_fn(strategy, mode, query, top_k=5, filter=None):
        calls.append((strategy, mode, query))
        return _fake_search_fn(strategy, mode, query, top_k, filter)

    all_metrics, by_category, missing = run_evaluation(questions, strategies, modes, top_k=5,
                                                        results_dir=tmp_path / "results",
                                                        search_fn=counting_search_fn)

    assert len(calls) == len(questions) * len(strategies) * len(modes)
    assert len(all_metrics) == len(strategies) * len(modes)
    assert len(by_category) == len(strategies) * len(modes)  # all questions share category "A" here
    assert missing == []


def test_saves_one_jsonl_file_per_strategy_and_mode_with_one_line_per_question(tmp_path):
    questions = [_question("Q001"), _question("Q002")]
    results_dir = tmp_path / "results"

    run_evaluation(questions, ["fixed"], ["keyword"], top_k=5, results_dir=results_dir,
                    search_fn=_fake_search_fn)

    path = results_dir / "fixed" / "keyword.jsonl"
    assert path.exists()
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    assert {r["question_id"] for r in lines} == {"Q001", "Q002"}
    assert lines[0]["mode"] == "keyword"
    assert lines[0]["strategy"] == "fixed"
    assert lines[0]["results"][0]["chunk_id"] == "c1"


def test_applies_the_question_suggested_filter(tmp_path):
    captured_filters = []

    def capturing_search_fn(strategy, mode, query, top_k=5, filter=None):
        captured_filters.append(filter)
        return _fake_search_fn(strategy, mode, query, top_k, filter)

    questions = [_question("Q001", suggested_filter="document_type eq 'regulation'")]
    run_evaluation(questions, ["fixed"], ["keyword"], results_dir=tmp_path / "results",
                    search_fn=capturing_search_fn)

    assert captured_filters == ["document_type eq 'regulation'"]


def test_reports_missing_ground_truth_once_per_question_not_once_per_combination(tmp_path):
    questions = [_question("Q001", expected_source_file=None, ground_truth_status="not_available")]

    _, _, missing = run_evaluation(questions, ["fixed", "hybrid"], ["keyword", "vector"],
                                    results_dir=tmp_path / "results", search_fn=_fake_search_fn)

    assert len(missing) == 1
    assert missing[0]["question_id"] == "Q001"


def test_does_not_change_the_question_set_between_strategies(tmp_path):
    questions = [_question("Q001"), _question("Q002")]
    seen_per_strategy = {}

    def recording_search_fn(strategy, mode, query, top_k=5, filter=None):
        seen_per_strategy.setdefault(strategy, []).append(query)
        return _fake_search_fn(strategy, mode, query, top_k, filter)

    run_evaluation(questions, ["fixed", "recursive"], ["keyword"], results_dir=tmp_path / "results",
                    search_fn=recording_search_fn)

    assert seen_per_strategy["fixed"] == seen_per_strategy["recursive"]


def test_recompute_from_saved_results_matches_a_live_run_without_querying_again(tmp_path):
    questions = [_question("Q001"), _question("Q002")]
    results_dir = tmp_path / "results"

    live_metrics, live_by_category, live_missing = run_evaluation(
        questions, ["fixed"], ["keyword"], top_k=5, results_dir=results_dir, search_fn=_fake_search_fn,
    )

    # recompute_from_saved_results takes no search_fn at all — it can only
    # read from results_dir, never query live.
    recomputed_metrics, recomputed_by_category, recomputed_missing = recompute_from_saved_results(
        questions, ["fixed"], ["keyword"], top_k=5, results_dir=results_dir,
    )

    assert [m.to_dict() for m in recomputed_metrics] == [m.to_dict() for m in live_metrics]
    assert [m.to_dict() for m in recomputed_by_category] == [m.to_dict() for m in live_by_category]
    assert recomputed_missing == live_missing
