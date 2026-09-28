#!/usr/bin/env python3
"""CLI: inspect one evaluation question's retrieved chunks across all four
chunking strategies and all three retrieval modes, side by side.

Usage:
    python -m ticbot_chunking.scripts.evaluate_retrieval --question-id Q001

    # A single mode instead of all three:
    python -m ticbot_chunking.scripts.evaluate_retrieval --question-id Q014 --mode hybrid

    # Reads previously-saved raw results instead of querying Azure again
    # (fast, free, reflects exactly what run_retrieval_eval.py last saved):
    python -m ticbot_chunking.scripts.evaluate_retrieval --question-id Q001 --from-results-dir evaluation/results
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ticbot_chunking.scripts.run_chunking_experiments import STRATEGIES
from ticbot_chunking.search.eval_metrics import load_questions
from ticbot_chunking.search.retrieval_client import MODES, search


def _print_result_block(strategy: str, mode: str, record: dict) -> None:
    print(f"\n--- {strategy} / {mode} "
          f"(latency={record.get('latency_seconds', 0):.3f}s, results={len(record.get('results', []))}) ---")
    for r in record.get("results", []):
        print(f"  [{r['rank']}] score={r['score']} reranker_score={r['reranker_score']} "
              f"chunk_id={r['chunk_id']}")
        print(f"      source_file={r['source_file']}  pages={r['pages']}  sheet={r['sheet']}  "
              f"cell_range={r['cell_range']}")
        print(f"      document_type={r['document_type']}  chunk_type={r['chunk_type']}  "
              f"section_path={r['section_path']}")
        print(f"      text: {(r['text'] or '')[:200]!r}")
    if not record.get("results"):
        print("  (no results)")


def _load_saved_record(results_dir: str, strategy: str, mode: str, question_id: str) -> dict | None:
    path = Path(results_dir) / strategy / f"{mode}.jsonl"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("question_id") == question_id:
                return record
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--question-id", required=True)
    parser.add_argument("--questions", default="evaluation/questions.jsonl")
    parser.add_argument("--mode", choices=MODES, default=None, help="Limit to one mode (default: all three)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--from-results-dir", default=None,
                         help="Read previously-saved raw results from this directory instead of querying "
                              "Azure AI Search again")
    args = parser.parse_args()

    questions = {q.question_id: q for q in load_questions(args.questions)}
    question = questions.get(args.question_id)
    if question is None:
        raise SystemExit(f"Unknown question_id: {args.question_id!r} (not found in {args.questions})")

    print(f"Question [{question.question_id}] ({question.category}): {question.question}")
    print(f"Expected source_file: {question.expected_source_file}")
    print(f"Expected pages: {question.expected_pages}  Expected sheet: {question.expected_sheet}")
    print(f"Ground truth status: {question.ground_truth_status}")
    print(f"Notes: {question.notes}")
    if question.suggested_filter:
        print(f"Suggested filter (applied): {question.suggested_filter}")

    modes = [args.mode] if args.mode else list(MODES)

    for strategy in STRATEGIES:
        print(f"\n{'=' * 70}\n{strategy.upper()}\n{'=' * 70}")
        for mode in modes:
            if args.from_results_dir:
                record = _load_saved_record(args.from_results_dir, strategy, mode, question.question_id)
                if record is None:
                    print(f"\n--- {strategy} / {mode} --- (no saved result found under {args.from_results_dir})")
                    continue
            else:
                query_result = search(strategy, mode, question.question, top_k=args.top_k,
                                       filter=question.suggested_filter)
                record = query_result.to_dict()
            _print_result_block(strategy, mode, record)


if __name__ == "__main__":
    main()
