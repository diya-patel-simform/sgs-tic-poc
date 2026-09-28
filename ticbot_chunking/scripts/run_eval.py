#!/usr/bin/env python3
"""CLI: run the retrieval/citation-accuracy QA suite against the Azure AI
Search index (section 8 of TICbot_Chunking_Strategy_Answers.md).

Usage:
    python -m ticbot_chunking.scripts.run_eval qa_questions.json
"""
from __future__ import annotations

import json
import sys

from ticbot_chunking.retrieval.qa_eval import run_eval


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <qa_questions.json>", file=sys.stderr)
        raise SystemExit(1)

    result = run_eval(sys.argv[1])

    print(f"{'Area':<20}{'Qs':>5}{'Hit@1':>10}{'Hit@5':>10}{'MRR@10':>10}")
    for area, stats in result["by_area"].items():
        print(f"{area:<20}{stats['questions']:>5}{stats['hit@1_pct']:>9}%{stats['hit@5_pct']:>9}%{stats['mrr@10']:>10}")
    total = result["total"]
    print(f"{'TOTAL':<20}{total['questions']:>5}{total['hit@1_pct']:>9}%{total['hit@5_pct']:>9}%{total['mrr@10']:>10}")

    with open("eval_results.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print("\nFull results written to eval_results.json")


if __name__ == "__main__":
    main()
