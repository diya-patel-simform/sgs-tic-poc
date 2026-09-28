#!/usr/bin/env python3
"""CLI: inspect individual chunks from a chunks.jsonl file, with full text
and metadata, for debugging the chunking pipeline. Pure local analysis — no
Azure credentials needed.

Usage:
    # Show one chunk by its line index in the file
    python -m ticbot_chunking.scripts.inspect_chunk output/chunks.jsonl --index 42

    # Show every chunk of a given type (or doc_type / source_file), full text
    python -m ticbot_chunking.scripts.inspect_chunk output/chunks.jsonl --chunk-type table

    python -m ticbot_chunking.scripts.inspect_chunk output/chunks.jsonl --doc-type accreditation_scope

    python -m ticbot_chunking.scripts.inspect_chunk output/chunks.jsonl --source-file Contaminants_Regulations_pages_1-5.pdf

    # Full-text search (case-insensitive substring match)
    python -m ticbot_chunking.scripts.inspect_chunk output/chunks.jsonl --contains Carbaryl

    # Just list matches (index, type, tokens, pages/sheet) without full text
    python -m ticbot_chunking.scripts.inspect_chunk output/chunks.jsonl --chunk-type figure --list

Filters can be combined (AND'd together); --limit caps how many are printed.
"""
from __future__ import annotations

import argparse
import json
from typing import Any


def load_chunks(path: str) -> list[dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def matches(row: dict[str, Any], args: argparse.Namespace) -> bool:
    meta = row["metadata"]
    if args.chunk_type and meta.get("chunk_type") != args.chunk_type:
        return False
    if args.doc_type and meta.get("doc_type") != args.doc_type:
        return False
    if args.source_file and meta.get("source_file") != args.source_file:
        return False
    if args.contains and args.contains.lower() not in row["text"].lower():
        return False
    return True


def _location(meta: dict[str, Any]) -> str:
    parts = []
    if meta.get("pages"):
        parts.append(f"pages={meta['pages']}")
    if meta.get("sheet"):
        parts.append(f"sheet={meta['sheet']!r}")
    if meta.get("cell_range"):
        parts.append(f"cell_range={meta['cell_range']}")
    return " ".join(parts)


def print_summary_line(idx: int, row: dict[str, Any]) -> None:
    meta = row["metadata"]
    print(f"#{idx:<5} {meta.get('chunk_type', '?'):<14} {meta.get('tokens', 0):>5} tok  "
          f"{_location(meta):<28} {meta.get('source_file', '')}")


def print_full_chunk(idx: int, row: dict[str, Any]) -> None:
    print("=" * 80)
    print(f"chunk #{idx}")
    print("-" * 80)
    print("metadata:")
    print(json.dumps(row["metadata"], indent=2, ensure_ascii=False))
    print("-" * 80)
    print("text:")
    print(row["text"])
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("chunks_path", help="Path to chunks.jsonl")
    parser.add_argument("--index", type=int, help="Show the chunk at this line index (0-based)")
    parser.add_argument("--chunk-type", help="Filter by metadata.chunk_type (text, table, scope_records, ...)")
    parser.add_argument("--doc-type", help="Filter by metadata.doc_type")
    parser.add_argument("--source-file", help="Filter by metadata.source_file (exact match)")
    parser.add_argument("--contains", help="Case-insensitive substring match against the chunk text")
    parser.add_argument("--limit", type=int, default=10, help="Max chunks to print (default 10, 0 = no limit)")
    parser.add_argument("--list", action="store_true", help="Print one summary line per match instead of full text")
    args = parser.parse_args()

    rows = load_chunks(args.chunks_path)

    if args.index is not None:
        if not (0 <= args.index < len(rows)):
            raise SystemExit(f"Index {args.index} out of range (0..{len(rows) - 1})")
        print_full_chunk(args.index, rows[args.index])
        return

    matched = [(i, r) for i, r in enumerate(rows) if matches(r, args)]
    print(f"{len(matched)} chunk(s) matched out of {len(rows)} total.\n")

    shown = matched if args.limit == 0 else matched[: args.limit]
    for idx, row in shown:
        if args.list:
            print_summary_line(idx, row)
        else:
            print_full_chunk(idx, row)

    if args.limit and len(matched) > args.limit:
        print(f"... {len(matched) - args.limit} more not shown (raise --limit or add --list)")


if __name__ == "__main__":
    main()
