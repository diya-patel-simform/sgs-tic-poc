#!/usr/bin/env python3
"""CLI: compute a chunk statistics report from a chunks.jsonl file.

Pure local analysis — no Azure credentials needed.

Usage:
    python -m ticbot_chunking.scripts.chunk_stats output/chunks.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from typing import Any

from ticbot_chunking.chunkers.text_utils import MIN_CONTENT_TOKENS
from ticbot_chunking.config import EXCEL_BLOCK, NABL_SCOPE, NARRATIVE, REGULATION_TABLE

# chunk_type -> the configured max-token limit that applies to it (None = no
# fixed ceiling for that type). A chunk over its limit isn't necessarily a
# bug: table/NABL/Excel chunks may run slightly over once the breadcrumb
# header is added on top of the row-integrity-bounded body (see section 2
# footnote of TICbot_Chunking_Strategy_Answers.md) — this report surfaces it
# for review, not as a hard failure.
LIMIT_BY_CHUNK_TYPE: dict[str, int | None] = {
    "text": NARRATIVE.max_tokens,
    "table": REGULATION_TABLE.max_tokens,
    "scope_records": NABL_SCOPE.max_tokens,
    "certificate": None,
    "figure": None,
    "sheet_table": EXCEL_BLOCK.max_tokens,
    "sheet_lists": EXCEL_BLOCK.max_tokens,
    "sheet_kv": EXCEL_BLOCK.max_tokens,
    "sheet_chart": None,
}

# Only narrative ("text") chunks have a documented minimum (section 2: small
# neighbouring sections are merged below NARRATIVE.min_tokens). Table/NABL/
# Excel chunks are explicitly allowed to be "whole [block] if small", so they
# aren't judged against this threshold.
TINY_CHUNK_TYPES = {"text"}


def load_chunks(path: str) -> list[dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def compute_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    docs = {r["metadata"].get("source_file") for r in rows}
    by_doc_type = Counter(r["metadata"].get("doc_type") for r in rows)
    by_chunk_type = Counter(r["metadata"].get("chunk_type") for r in rows)
    tokens = [r["metadata"].get("tokens", 0) for r in rows]

    exceeding = []
    tiny = []
    empty = []
    for i, r in enumerate(rows):
        meta = r["metadata"]
        ctype = meta.get("chunk_type")
        tok = meta.get("tokens", 0)
        limit = LIMIT_BY_CHUNK_TYPE.get(ctype)

        if limit and tok > limit:
            exceeding.append({"index": i, "chunk_type": ctype, "tokens": tok, "limit": limit,
                               "preview": r["text"][:80]})

        if tok < MIN_CONTENT_TOKENS or not r["text"].strip():
            empty.append({"index": i, "chunk_type": ctype, "tokens": tok, "preview": r["text"][:80]})
        elif ctype in TINY_CHUNK_TYPES and tok < NARRATIVE.min_tokens:
            tiny.append({"index": i, "chunk_type": ctype, "tokens": tok, "preview": r["text"][:80]})

    return {
        "documents": len(docs),
        "chunks": n,
        "by_doc_type": dict(sorted(by_doc_type.items(), key=lambda kv: -kv[1])),
        "by_chunk_type": dict(sorted(by_chunk_type.items(), key=lambda kv: -kv[1])),
        "tokens_min": min(tokens) if tokens else 0,
        "tokens_avg": round(sum(tokens) / n, 1) if n else 0,
        "tokens_max": max(tokens) if tokens else 0,
        "exceeding_limits": exceeding,
        "tiny_chunks": tiny,
        "empty_chunks": empty,
    }


def print_report(stats: dict[str, Any]) -> None:
    print(f"Documents: {stats['documents']}")
    print(f"Chunks: {stats['chunks']}")
    print()
    print("Chunks by doc_type:")
    for k, v in stats["by_doc_type"].items():
        print(f"  {k}: {v}")
    print()
    print("Chunks by chunk_type:")
    for k, v in stats["by_chunk_type"].items():
        print(f"  {k}: {v}")
    print()
    print(f"Tokens — min: {stats['tokens_min']}  avg: {stats['tokens_avg']}  max: {stats['tokens_max']}")
    print()
    print(f"Chunks exceeding their configured limit (informational — see section 2 footnote): "
          f"{len(stats['exceeding_limits'])}")
    for row in stats["exceeding_limits"][:20]:
        print(f"  #{row['index']} [{row['chunk_type']}] {row['tokens']} > {row['limit']}: {row['preview']}...")
    print()
    print(f"Tiny narrative chunks (< {NARRATIVE.min_tokens} tokens): {len(stats['tiny_chunks'])}")
    for row in stats["tiny_chunks"][:20]:
        print(f"  #{row['index']} [{row['chunk_type']}] {row['tokens']} tokens: {row['preview']}...")
    print()
    print(f"Empty / near-empty chunks (< {MIN_CONTENT_TOKENS} tokens): {len(stats['empty_chunks'])}")
    for row in stats["empty_chunks"][:20]:
        print(f"  #{row['index']} [{row['chunk_type']}] {row['tokens']} tokens: {row['preview']}...")


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <chunks_jsonl_path>", file=sys.stderr)
        raise SystemExit(1)

    rows = load_chunks(sys.argv[1])
    stats = compute_stats(rows)
    print_report(stats)

    with open("chunk_stats.json", "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    print("\nFull report written to chunk_stats.json")


if __name__ == "__main__":
    main()
