#!/usr/bin/env python3
"""CLI: chunk-quality / edge-case validation across all chunking strategies.

Runs two kinds of checks:
  - Generic checks (missing metadata, empty/tiny chunks, duplication,
    token-limit violations, missing table headers, missing section
    hierarchy, multi-page continuity) against whatever
    <experiments-dir>/<strategy>/chunks.jsonl files already exist (produced
    by scripts/run_chunking_experiments.py).
  - Fixture-based checks (row splitting, rowspan carry-forward, NABL
    grouping, brochure reading order, Excel block separation) that build
    their own small known-correct scenarios and run every strategy fresh —
    these always run, independent of what's in --experiments-dir, and need
    no Azure credentials.

Writes:
  <experiments-dir>/edge_case_report.md    "Edge Case | Expected | Actual | Pass/Fail", one table per strategy
  <experiments-dir>/edge_case_report.json  the same, as data
  <experiments-dir>/<strategy>/inspection_report.md   human-readable per-chunk report

Does not declare a best strategy.

Usage:
    python -m ticbot_chunking.scripts.run_validation --experiments-dir experiments
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from ticbot_chunking.scripts.chunk_stats import LIMIT_BY_CHUNK_TYPE as HYBRID_LIMIT_BY_CHUNK_TYPE
from ticbot_chunking.validation import fixture_checks, generic_checks, report
from ticbot_chunking.validation.edge_cases import EdgeCaseResult

STRATEGIES = ("fixed", "recursive", "structure_aware", "hybrid")
FALLBACK_MAX_CHUNK_SIZE = 700  # matches run_chunking_experiments.py's own default


def load_chunks(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def limit_fn_for(strategy: str, strategy_stats: dict | None):
    if strategy == "hybrid":
        return lambda chunk_type: HYBRID_LIMIT_BY_CHUNK_TYPE.get(chunk_type)
    max_chunk_size = (strategy_stats or {}).get("max_chunk_size", FALLBACK_MAX_CHUNK_SIZE)
    return lambda chunk_type: max_chunk_size


def run_generic_checks_for_experiments_dir(experiments_dir: Path) -> tuple[list[EdgeCaseResult], dict[str, list[dict]]]:
    results: list[EdgeCaseResult] = []
    rows_by_strategy: dict[str, list[dict]] = {}
    for strategy in STRATEGIES:
        chunks_path = experiments_dir / strategy / "chunks.jsonl"
        if not chunks_path.exists():
            continue
        rows = load_chunks(chunks_path)
        rows_by_strategy[strategy] = rows

        stats_path = experiments_dir / strategy / "stats.json"
        strategy_stats = json.loads(stats_path.read_text()) if stats_path.exists() else None

        results.extend(generic_checks.run_all_generic_checks(rows, strategy, limit_fn_for(strategy, strategy_stats)))
    return results, rows_by_strategy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--experiments-dir", default="experiments",
                         help="Directory containing <strategy>/chunks.jsonl (default: experiments)")
    args = parser.parse_args()

    experiments_dir = Path(args.experiments_dir)

    print(f"Scanning {experiments_dir} for existing strategy output...")
    generic_results, rows_by_strategy = run_generic_checks_for_experiments_dir(experiments_dir)
    for strategy in STRATEGIES:
        if strategy in rows_by_strategy:
            print(f"  {strategy}: {len(rows_by_strategy[strategy])} chunks found")
        else:
            print(f"  {strategy}: no chunks.jsonl found, generic checks skipped for this strategy")

    print("\nRunning fixture-based checks (row splitting, rowspan carry-forward, "
          "NABL grouping, brochure reading order, Excel block separation)...")
    with tempfile.TemporaryDirectory(prefix="ticbot_validation_") as tmp_dir:
        fixture_results = fixture_checks.run_all_fixture_checks(Path(tmp_dir))

    all_results = generic_results + fixture_results

    experiments_dir.mkdir(parents=True, exist_ok=True)
    report_md = report.build_edge_case_report_markdown(all_results)
    (experiments_dir / "edge_case_report.md").write_text(report_md, encoding="utf-8")
    (experiments_dir / "edge_case_report.json").write_text(
        json.dumps(report.results_to_dicts(all_results), indent=2), encoding="utf-8"
    )

    for strategy, rows in rows_by_strategy.items():
        inspection_md = report.build_chunk_inspection_report_markdown(rows, strategy)
        (experiments_dir / strategy / "inspection_report.md").write_text(inspection_md, encoding="utf-8")

    print(f"\n{report.format_console_summary(all_results)}")
    print(f"\nEdge-case report written to {experiments_dir / 'edge_case_report.md'} "
          f"(+ .json)")
    for strategy in rows_by_strategy:
        print(f"Chunk inspection report written to {experiments_dir / strategy / 'inspection_report.md'}")


if __name__ == "__main__":
    main()
