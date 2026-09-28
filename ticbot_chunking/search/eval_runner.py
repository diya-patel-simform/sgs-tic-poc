"""Orchestrates the retrieval evaluation matrix: every question x every
strategy x every retrieval mode, at a fixed top_k, saving raw results and
computing metrics. `search_fn` is injectable so this is fully unit-testable
without a live Azure service.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ticbot_chunking.search.eval_metrics import (
    AggregateMetrics,
    Question,
    aggregate,
    aggregate_by_category,
    score_query_result,
)
from ticbot_chunking.search.retrieval_client import RetrievalQueryResult, search as default_search_fn

SearchFn = Callable[..., Any]
RunResult = tuple[list[AggregateMetrics], list[AggregateMetrics], list[dict[str, Any]]]


def _missing_ground_truth(questions: list[Question]) -> list[dict[str, Any]]:
    return [
        {"question_id": q.question_id, "category": q.category, "reason": q.notes}
        for q in questions if not q.has_ground_truth
    ]


def _summarize(outcomes_by_combo: dict[tuple[str, str], list], strategies: list[str], modes: list[str],
               top_k: int) -> tuple[list[AggregateMetrics], list[AggregateMetrics]]:
    all_metrics = [aggregate(outcomes_by_combo[(s, m)], s, m, top_k) for s in strategies for m in modes]
    by_category = [
        cat_metrics
        for s in strategies for m in modes
        for cat_metrics in aggregate_by_category(outcomes_by_combo[(s, m)], s, m, top_k)
    ]
    return all_metrics, by_category


def run_evaluation(questions: list[Question], strategies: list[str], modes: list[str], *, top_k: int = 5,
                    results_dir: str | Path = "evaluation/results",
                    search_fn: SearchFn = default_search_fn) -> RunResult:
    """Runs every question against every (strategy, mode) combination,
    saving one JSONL file per (strategy, mode) under `results_dir`
    (results_dir/<strategy>/<mode>.jsonl, one line per question). Returns
    (all_metrics, by_category_metrics, missing_ground_truth) — the same
    question set and top_k are used for every combination; nothing changes
    between strategies."""
    results_dir = Path(results_dir)
    outcomes_by_combo: dict[tuple[str, str], list] = {(s, m): [] for s in strategies for m in modes}

    for strategy in strategies:
        for mode in modes:
            out_path = results_dir / strategy / f"{mode}.jsonl"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                for question in questions:
                    query_result = search_fn(strategy, mode, question.question, top_k=top_k,
                                              filter=question.suggested_filter)

                    record = query_result.to_dict()
                    record["question_id"] = question.question_id
                    record["category"] = question.category
                    record["ground_truth_status"] = question.ground_truth_status
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

                    outcomes_by_combo[(strategy, mode)].append(score_query_result(query_result, question))

    all_metrics, by_category = _summarize(outcomes_by_combo, strategies, modes, top_k)
    return all_metrics, by_category, _missing_ground_truth(questions)


def recompute_from_saved_results(questions: list[Question], strategies: list[str], modes: list[str], *,
                                  top_k: int = 5, results_dir: str | Path = "evaluation/results") -> RunResult:
    """Re-scores and re-aggregates metrics from previously-saved raw results
    (results_dir/<strategy>/<mode>.jsonl) without querying Azure again —
    e.g. to regenerate a report after a metrics-calculation change, or when
    the underlying index hasn't changed since the results were saved. Raises
    FileNotFoundError if a combination's results file is missing."""
    results_dir = Path(results_dir)
    questions_by_id = {q.question_id: q for q in questions}
    outcomes_by_combo: dict[tuple[str, str], list] = {(s, m): [] for s in strategies for m in modes}

    for strategy in strategies:
        for mode in modes:
            path = results_dir / strategy / f"{mode}.jsonl"
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    record = json.loads(line)
                    question = questions_by_id[record["question_id"]]
                    query_result = RetrievalQueryResult.from_dict(record)
                    outcomes_by_combo[(strategy, mode)].append(score_query_result(query_result, question))

    all_metrics, by_category = _summarize(outcomes_by_combo, strategies, modes, top_k)
    return all_metrics, by_category, _missing_ground_truth(questions)
