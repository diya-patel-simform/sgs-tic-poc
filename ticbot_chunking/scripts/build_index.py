#!/usr/bin/env python3
"""CLI: create/update the Azure AI Search index and upload chunks.jsonl to it.

Usage:
    python -m ticbot_chunking.scripts.build_index output/chunks.jsonl
"""
from __future__ import annotations

import json
import sys

from ticbot_chunking.metadata.schema import Chunk, ChunkMetadata
from ticbot_chunking.retrieval.azure_search_index import create_or_update_index, upload_chunks


def _load_chunks(path: str) -> list[Chunk]:
    chunks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            chunks.append(Chunk(text=row["text"], metadata=ChunkMetadata(**row["metadata"])))
    return chunks


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <chunks_jsonl_path>", file=sys.stderr)
        raise SystemExit(1)

    chunks = _load_chunks(sys.argv[1])
    print(f"Loaded {len(chunks)} chunks from {sys.argv[1]}")

    print("Creating/updating Azure AI Search index...")
    create_or_update_index()

    print("Embedding + uploading chunks...")
    upload_chunks(chunks)
    print("Done.")


if __name__ == "__main__":
    main()
