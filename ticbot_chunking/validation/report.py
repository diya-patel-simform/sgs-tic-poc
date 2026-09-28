"""Renders EdgeCaseResult rows as the "Edge Case | Expected | Actual |
Pass/Fail" report, and builds a human-readable chunk inspection report
(source document, page, section, chunk type, token count, metadata, chunk
text) from a strategy's chunks.jsonl rows.
"""
from __future__ import annotations

import json
from typing import Any

from ticbot_chunking.validation.edge_cases import EdgeCaseResult

STRATEGIES = ("fixed", "recursive", "structure_aware", "hybrid")


def _escape_md(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def format_edge_case_table(results: list[EdgeCaseResult], strategy: str) -> str:
    rows = [r for r in results if r.strategy == strategy]
    lines = ["| Edge Case | Expected | Actual | Pass/Fail |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {_escape_md(r.edge_case)} | {_escape_md(r.expected)} | {_escape_md(r.actual)} | {r.status} |")
    return "\n".join(lines)


def build_edge_case_report_markdown(results: list[EdgeCaseResult]) -> str:
    lines = [
        "# Chunk-Quality / Edge-Case Validation Report",
        "",
        "One table per strategy, in the format `Edge Case | Expected | Actual | Pass/Fail`. "
        "This report presents findings only — it does not declare a best strategy.",
        "",
    ]
    for strategy in STRATEGIES:
        strategy_rows = [r for r in results if r.strategy == strategy]
        if not strategy_rows:
            continue
        n_pass = sum(1 for r in strategy_rows if r.passed is True)
        n_fail = sum(1 for r in strategy_rows if r.passed is False)
        n_na = sum(1 for r in strategy_rows if r.passed is None)
        lines.append(f"## {strategy}")
        lines.append("")
        lines.append(f"{n_pass} pass, {n_fail} fail, {n_na} not applicable")
        lines.append("")
        lines.append(format_edge_case_table(results, strategy))
        lines.append("")
    return "\n".join(lines)


def results_to_dicts(results: list[EdgeCaseResult]) -> list[dict[str, Any]]:
    return [
        {"edge_case": r.edge_case, "strategy": r.strategy, "expected": r.expected, "actual": r.actual,
         "status": r.status, "details": r.details}
        for r in results
    ]


def format_console_summary(results: list[EdgeCaseResult]) -> str:
    lines = []
    for strategy in STRATEGIES:
        strategy_rows = [r for r in results if r.strategy == strategy]
        if not strategy_rows:
            continue
        n_pass = sum(1 for r in strategy_rows if r.passed is True)
        n_fail = sum(1 for r in strategy_rows if r.passed is False)
        n_na = sum(1 for r in strategy_rows if r.passed is None)
        lines.append(f"{strategy:<16} pass={n_pass:<3} fail={n_fail:<3} n/a={n_na:<3}")
        for r in strategy_rows:
            if r.passed is False:
                lines.append(f"    FAIL: {r.edge_case} — {r.actual}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Human-readable chunk inspection report
# ---------------------------------------------------------------------------

def format_chunk_inspection_entry(row: dict[str, Any], index: int) -> str:
    meta = row["metadata"]
    location = meta.get("sheet") or ""
    if meta.get("cell_range"):
        location = f"{location} {meta['cell_range']}".strip()
    lines = [
        f"### Chunk #{index}",
        "",
        f"- **Source document:** {meta.get('source_file', '—')}",
        f"- **Page(s):** {meta.get('pages') or '—'}",
        f"- **Section:** {meta.get('section_path') or '—'}",
        f"- **Sheet / cell range:** {location or '—'}",
        f"- **Chunk type:** {meta.get('chunk_type', '—')}",
        f"- **Token count:** {meta.get('tokens', 0)}",
        f"- **Strategy:** {meta.get('strategy') or '—'}",
        "",
        "**Metadata:**",
        "```json",
        json.dumps(meta, indent=2, ensure_ascii=False),
        "```",
        "",
        "**Chunk text:**",
        "```",
        row["text"],
        "```",
        "",
    ]
    return "\n".join(lines)


def _anchor(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")


def build_chunk_inspection_report_markdown(rows: list[dict[str, Any]], strategy: str) -> str:
    lines = [f"# Chunk Inspection Report — {strategy}", "", f"{len(rows)} chunk(s)", ""]

    by_source: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for i, row in enumerate(rows):
        by_source.setdefault(row["metadata"].get("source_file", "(unknown)"), []).append((i, row))

    lines.append("## Table of contents")
    for source, entries in by_source.items():
        lines.append(f"- [{source}](#{_anchor(source)}) ({len(entries)} chunks)")
    lines.append("")

    for source, entries in by_source.items():
        lines.append(f"## {source}")
        lines.append("")
        for i, row in entries:
            lines.append(format_chunk_inspection_entry(row, i))
    return "\n".join(lines)
