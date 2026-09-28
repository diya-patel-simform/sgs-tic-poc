"""Builds evaluation/retrieval_comparison.json and .md — one row per
(strategy, mode) combination, in the fixed order they were run, never
sorted or filtered by any metric. No overall winner is computed anywhere
in this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ticbot_chunking.search.eval_metrics import AggregateMetrics

# Category codes as assigned in evaluation/questions.jsonl (section 5 of the
# retrieval-evaluation task: "cover different document/data characteristics").
CATEGORY_LABELS = {
    "A": "Normal prose/content",
    "B": "Headings and sections",
    "C": "Multi-page tables",
    "D": "NABL scope information",
    "E": "Certificate/lab information",
    "F": "Excel contact information",
    "G": "Excel structured blocks",
    "H": "Page-specific questions",
    "I": "Metadata-filter questions",
    "J": "Long-context questions",
}


def build_comparison_report_json(all_metrics: list[AggregateMetrics], strategies: list[str], modes: list[str],
                                  num_questions: int, top_k: int, missing_ground_truth: list[dict[str, Any]],
                                  by_category: list[AggregateMetrics] | None = None) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "num_questions": num_questions,
        "top_k": top_k,
        "strategies": strategies,
        "modes": modes,
        "num_combinations_tested": len(all_metrics),
        "results": [m.to_dict() for m in all_metrics],
        "by_category": [m.to_dict() for m in (by_category or [])],
        "category_labels": CATEGORY_LABELS,
        "missing_ground_truth": missing_ground_truth,
        "note": "No overall winner is computed or implied. These are measurements only, per "
                "(strategy, mode) combination, for the same question set and the same top_k.",
    }


def _fmt(value, digits: int = 3) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def build_comparison_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Retrieval Strategy Comparison Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Questions: {report['num_questions']}  |  top_k: {report['top_k']}  |  "
        f"Strategy/mode combinations tested: {report['num_combinations_tested']}",
        "",
        "**No strategy is automatically ranked or declared a winner.** The table below reports "
        "measurements only, per (strategy, mode) combination, run against the identical question "
        "set and top_k.",
        "",
        "| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Citation Precision | "
        "Avg Score | Avg Results | Empty | Avg Latency (s) |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in report["results"]:
        lines.append(
            f"| {m['strategy']} | {m['mode']} | {_fmt(m['hit_at_1'])} | {_fmt(m['hit_at_3'])} | "
            f"{_fmt(m['hit_at_5'])} | {_fmt(m['source_recall'])} | {_fmt(m['citation_precision'])} | "
            f"{_fmt(m['avg_score'])} | {_fmt(m['avg_num_results'])} | {m['empty_retrieval_count']} | "
            f"{_fmt(m['avg_latency_seconds'])} |"
        )

    scored = report["results"][0]["num_scored_questions"] if report["results"] else 0
    lines += [
        "",
        f"Hit@K / Source Recall / Citation Precision are computed over {scored} of "
        f"{report['num_questions']} questions that have verifiable ground truth (the rest have "
        "`ground_truth_status: not_available` and are excluded from these metrics — but were still "
        "run; see the raw per-question results under evaluation/results/).",
    ]

    if report["missing_ground_truth"]:
        lines += ["", "## Questions without verifiable ground truth", "",
                  "| Question ID | Category | Reason |", "|---|---|---|"]
        for q in report["missing_ground_truth"]:
            lines.append(f"| {q['question_id']} | {q['category']} | {q['reason']} |")

    if report.get("by_category"):
        lines += _build_category_breakdown_section(report["by_category"], report.get("category_labels", {}))

    return "\n".join(lines)


def _build_category_breakdown_section(by_category: list[dict[str, Any]], labels: dict[str, str]) -> list[str]:
    lines = [
        "", "## Document-type / category breakdown", "",
        "The same measurements as above, split by question category, so a strategy's behavior on "
        "(for example) NABL scope data can be compared against its behavior on Excel blocks or "
        "page-specific PDF questions. Each category's questions are the same across every "
        "strategy/mode — only the underlying data characteristic differs. No winner is computed "
        "here either.",
    ]
    categories_seen: list[str] = []
    rows_by_category: dict[str, list[dict[str, Any]]] = {}
    for row in by_category:
        cat = row["category"]
        if cat not in rows_by_category:
            categories_seen.append(cat)
            rows_by_category[cat] = []
        rows_by_category[cat].append(row)

    for cat in categories_seen:
        label = labels.get(cat, cat)
        rows = rows_by_category[cat]
        n = rows[0]["num_questions"] if rows else 0
        lines += ["", f"### Category {cat} — {label} ({n} question(s))", "",
                  "| Strategy | Mode | Hit@1 | Hit@3 | Hit@5 | Source Recall | Avg Score | Avg Latency (s) |",
                  "|---|---|---|---|---|---|---|---|"]
        for m in rows:
            lines.append(
                f"| {m['strategy']} | {m['mode']} | {_fmt(m['hit_at_1'])} | {_fmt(m['hit_at_3'])} | "
                f"{_fmt(m['hit_at_5'])} | {_fmt(m['source_recall'])} | {_fmt(m['avg_score'])} | "
                f"{_fmt(m['avg_latency_seconds'])} |"
            )
    return lines
