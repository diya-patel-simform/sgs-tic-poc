#!/usr/bin/env python3
"""CLI: parse + chunk every PDF/Excel file in an input directory.

Usage:
    python -m ticbot_chunking.scripts.run_pipeline upadated_data_sgs output/chunks.jsonl
"""
from __future__ import annotations

import sys
from pathlib import Path

from ticbot_chunking.pipeline import run_pipeline


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input_dir> <output_jsonl_path>", file=sys.stderr)
        raise SystemExit(1)

    input_dir, output_path = sys.argv[1], sys.argv[2]
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    chunks = run_pipeline(input_dir, output_path)

    by_type: dict[str, int] = {}
    for c in chunks:
        by_type[c.metadata.chunk_type] = by_type.get(c.metadata.chunk_type, 0) + 1

    print(f"Wrote {len(chunks)} chunks to {output_path}")
    for chunk_type, count in sorted(by_type.items()):
        print(f"  {chunk_type}: {count}")


if __name__ == "__main__":
    main()
