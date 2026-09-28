#!/usr/bin/env python3
"""CLI: run and compare chunking strategies on exactly the same parsed
documents.

Four strategies:
  fixed             naive fixed-size token-window chunking, ignores structure
  recursive         recursive/semantic packing: paragraph/sentence/word aware
  structure_aware   generic heading/table/block structure, no doc-type rules
  hybrid            the existing document-type-aware pipeline, reused as-is

Every input file is parsed exactly once (PDFs via the existing Azure
Document Intelligence adapter; Excel files read locally with no Azure
dependency) and every selected strategy runs against that same parsed
representation, so the comparison is on chunking logic alone, not on
parsing variance.

Usage:
    python -m ticbot_chunking.scripts.run_chunking_experiments --input upadated_data_sgs
    python -m ticbot_chunking.scripts.run_chunking_experiments --input upadated_data_sgs --strategy hybrid
    python -m ticbot_chunking.scripts.run_chunking_experiments --input upadated_data_sgs \\
        --output-dir experiments_400 --chunk-size 400 --overlap 60 --max-chunk-size 700
    python -m ticbot_chunking.scripts.run_chunking_experiments --input upadated_data_sgs \\
        --output-dir experiments_800 --chunk-size 800 --overlap 100 --max-chunk-size 1200

Output layout (matches --output-dir, default "experiments"):
    experiments/fixed/chunks.jsonl            experiments/fixed/stats.json
    experiments/recursive/chunks.jsonl        experiments/recursive/stats.json
    experiments/structure_aware/chunks.jsonl  experiments/structure_aware/stats.json
    experiments/hybrid/chunks.jsonl           experiments/hybrid/stats.json
    experiments/comparison_report.json        (regenerated from every stats.json found,
                                                so it reflects whichever strategies have
                                                been run into --output-dir so far)
"""
from __future__ import annotations

import argparse
import os

# --- chunk-size overrides must reach the environment before any
# ticbot_chunking import happens ------------------------------------------
#
# config.py's NARRATIVE / REGULATION_TABLE / NABL_SCOPE / EXCEL_BLOCK
# singletons (which the *reused, unmodified* hybrid chunkers read from
# directly) are frozen dataclasses populated once, at import time, from
# CHUNK_*_TOKENS environment variables (see the chunking-stabilization
# step). Setting them here — before the `from ticbot_chunking...` imports
# below — is what lets a single invocation's
# --chunk-size/--overlap/--max-chunk-size apply uniformly to every strategy
# selected in that invocation, hybrid included, without touching the
# existing hybrid chunkers at all. To compare multiple token-limit
# configurations, run this script again with different values and a
# different --output-dir.
_pre_parser = argparse.ArgumentParser(add_help=False)
_pre_parser.add_argument("--chunk-size", type=int, default=None)
_pre_parser.add_argument("--overlap", type=int, default=None)
_pre_parser.add_argument("--max-chunk-size", type=int, default=None)
_pre_args, _ = _pre_parser.parse_known_args()

if _pre_args.chunk_size is not None:
    os.environ["CHUNK_NARRATIVE_TARGET_TOKENS"] = str(_pre_args.chunk_size)
if _pre_args.max_chunk_size is not None:
    os.environ["CHUNK_NARRATIVE_MAX_TOKENS"] = str(_pre_args.max_chunk_size)
    os.environ["CHUNK_TABLE_MAX_TOKENS"] = str(_pre_args.max_chunk_size)
    os.environ["CHUNK_NABL_MAX_TOKENS"] = str(_pre_args.max_chunk_size)
    os.environ["CHUNK_EXCEL_MAX_TOKENS"] = str(_pre_args.max_chunk_size)
if _pre_args.overlap is not None:
    os.environ["CHUNK_NARRATIVE_OVERLAP_MAX_TOKENS"] = str(_pre_args.overlap)

import json  # noqa: E402
from pathlib import Path  # noqa: E402

from ticbot_chunking.experiments import fixed_size, hybrid, recursive, stats, structure_aware  # noqa: E402
from ticbot_chunking.experiments.common import ParsedDoc, build_doc_metadata, parse_input_dir  # noqa: E402
from ticbot_chunking.metadata.schema import Chunk  # noqa: E402

STRATEGIES = ("fixed", "recursive", "structure_aware", "hybrid")

DEFAULT_CHUNK_SIZE = 400       # matches NARRATIVE.target_tokens's own default
DEFAULT_MAX_CHUNK_SIZE = 700   # matches NARRATIVE.max_tokens's own default
DEFAULT_OVERLAP = 60           # matches NARRATIVE.overlap_max_tokens's own default


def run_strategy(strategy: str, parsed_docs: list[ParsedDoc], chunk_size: int, overlap: int,
                  max_chunk_size: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    for parsed in parsed_docs:
        if strategy == "fixed":
            doc_meta = build_doc_metadata(parsed)
            chunks.extend(fixed_size.chunk_fixed_size(parsed, doc_meta, chunk_size, overlap, max_chunk_size))
        elif strategy == "recursive":
            doc_meta = build_doc_metadata(parsed)
            chunks.extend(recursive.chunk_recursive(parsed, doc_meta, chunk_size, overlap, max_chunk_size))
        elif strategy == "structure_aware":
            doc_meta = build_doc_metadata(parsed)
            chunks.extend(structure_aware.chunk_structure_aware(parsed, doc_meta, chunk_size, overlap, max_chunk_size))
        elif strategy == "hybrid":
            chunks.extend(hybrid.chunk_hybrid(parsed))
        else:
            raise ValueError(f"Unknown strategy: {strategy}")
    return chunks


def write_jsonl(chunks: list[Chunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, help="Input directory, scanned recursively for .pdf/.xlsx/.xlsm")
    parser.add_argument("--strategy", choices=(*STRATEGIES, "all"), default="all",
                         help="Which strategy to run (default: all four)")
    parser.add_argument("--output-dir", default="experiments", help="Where <strategy>/chunks.jsonl is written")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                         help=f"Target chunk size in tokens (default {DEFAULT_CHUNK_SIZE})")
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP,
                         help=f"Overlap in tokens between adjacent chunks (default {DEFAULT_OVERLAP})")
    parser.add_argument("--max-chunk-size", type=int, default=DEFAULT_MAX_CHUNK_SIZE,
                         help=f"Maximum chunk size in tokens (default {DEFAULT_MAX_CHUNK_SIZE})")
    args = parser.parse_args()

    parsed_docs = parse_input_dir(args.input)
    print(f"Parsed {len(parsed_docs)} document(s) from {args.input}")
    if not parsed_docs:
        print("No .pdf/.xlsx/.xlsm files found — nothing to do.")
        return

    selected = list(STRATEGIES) if args.strategy == "all" else [args.strategy]
    output_root = Path(args.output_dir)

    for strategy in selected:
        print(f"\n=== {strategy} ===")
        chunks = run_strategy(strategy, parsed_docs, args.chunk_size, args.overlap, args.max_chunk_size)
        strategy_dir = output_root / strategy
        write_jsonl(chunks, strategy_dir / "chunks.jsonl")

        rows = [c.to_dict() for c in chunks]
        strategy_stats = stats.compute_strategy_stats(rows, strategy, args.chunk_size, args.max_chunk_size)
        with open(strategy_dir / "stats.json", "w", encoding="utf-8") as f:
            json.dump(strategy_stats, f, indent=2)

        print(f"Wrote {len(chunks)} chunks to {strategy_dir / 'chunks.jsonl'}")
        print(stats.format_strategy_summary(strategy_stats))

    all_stats = stats.load_all_stats(output_root)
    if all_stats:
        report = stats.build_comparison_report(all_stats)
        with open(output_root / "comparison_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print("\n=== Comparison across strategies (statistics only — no strategy is judged \"best\") ===")
        print(stats.format_comparison_table(all_stats))
        print(f"\nFull comparison report written to {output_root / 'comparison_report.json'}")


if __name__ == "__main__":
    main()
