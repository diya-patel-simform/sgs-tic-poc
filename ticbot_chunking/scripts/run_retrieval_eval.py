#!/usr/bin/env python3
"""CLI: run the full retrieval evaluation matrix — every question in
evaluation/questions.jsonl x every chunking strategy x every retrieval
mode, at a fixed top_k — and write the comparison report.

    evaluation/questions.jsonl
                 -> Azure AI Search (per strategy's index, per mode)
                 -> evaluation/results/<strategy>/<mode>.jsonl (raw results)
                 -> evaluation/retrieval_comparison.json / .md (metrics)

Never computes or reports an overall "winner" — see eval_report.py.

Usage:
    python -m ticbot_chunking.scripts.run_retrieval_eval

    python -m ticbot_chunking.scripts.run_retrieval_eval --top-k 10 \\
        --results-dir evaluation/results_top10 \\
        --report-json evaluation/retrieval_comparison_top10.json \\
        --report-md evaluation/retrieval_comparison_top10.md

    # Regenerate the report from previously-saved raw results without
    # querying Azure again (e.g. the index hasn't changed since the last
    # real run, or only the metrics/report logic changed):
    python -m ticbot_chunking.scripts.run_retrieval_eval --from-saved
"""
from __future__ import annotations

import argparse
import json

from ticbot_chunking.scripts.run_chunking_experiments import STRATEGIES
from ticbot_chunking.search.eval_metrics import load_questions
from ticbot_chunking.search.eval_report import build_comparison_report_json, build_comparison_report_markdown
from ticbot_chunking.search.eval_runner import recompute_from_saved_results, run_evaluation
from ticbot_chunking.search.retrieval_client import MODES, search


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", default="evaluation/questions.jsonl")
    parser.add_argument("--results-dir", default="evaluation/results")
    parser.add_argument("--report-json", default="evaluation/retrieval_comparison.json")
    parser.add_argument("--report-md", default="evaluation/retrieval_comparison.md")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--strategy", action="append", choices=STRATEGIES, dest="strategies",
                         help="Limit to one or more strategies (repeatable). Default: all four.")
    parser.add_argument("--mode", action="append", choices=MODES, dest="modes",
                         help="Limit to one or more retrieval modes (repeatable). Default: all three.")
    parser.add_argument("--from-saved", action="store_true",
                         help="Recompute metrics from previously-saved raw results under --results-dir "
                              "instead of querying Azure AI Search again")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    strategies = args.strategies or list(STRATEGIES)
    modes = args.modes or list(MODES)

    if args.from_saved:
        print(f"Recomputing from saved results under {args.results_dir} (no live queries) — "
              f"Questions: {len(questions)}  Strategies: {strategies}  Modes: {modes}  top_k={args.top_k}")
        all_metrics, by_category, missing_ground_truth = recompute_from_saved_results(
            questions, strategies, modes, top_k=args.top_k, results_dir=args.results_dir,
        )
    else:
        print(f"Questions: {len(questions)}  Strategies: {strategies}  Modes: {modes}  top_k={args.top_k}")
        print(f"Running {len(questions) * len(strategies) * len(modes)} queries...")
        all_metrics, by_category, missing_ground_truth = run_evaluation(
            questions, strategies, modes, top_k=args.top_k, results_dir=args.results_dir, search_fn=search,
        )

    report = build_comparison_report_json(all_metrics, strategies, modes, len(questions), args.top_k,
                                           missing_ground_truth, by_category=by_category)
    with open(args.report_json, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    with open(args.report_md, "w", encoding="utf-8") as f:
        f.write(build_comparison_report_markdown(report))

    print(f"\nWrote raw results under {args.results_dir}/<strategy>/<mode>.jsonl")
    print(f"Wrote comparison report to {args.report_json} and {args.report_md}")
    print(f"\n{len(missing_ground_truth)} question(s) have no verifiable ground truth (see report).")


if __name__ == "__main__":
    main()
