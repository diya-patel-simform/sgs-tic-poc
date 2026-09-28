#!/usr/bin/env python3
"""CLI: ingest documents from Azure Blob Storage through the existing local
parsing/chunking pipeline (`pipeline.process_pdf` / `pipeline.process_excel`
— unchanged).

This is a separate command from `run_pipeline.py` (which reads a local
directory): it lists matching blobs, downloads each to a local temp
directory, runs it through the same chunkers, then overwrites every
resulting chunk's `source_file` metadata with the blob's full path (not the
local temp filename) — so citations point back to where the document
actually lives in blob storage.

Does not touch embeddings or indexing — that's `build_index.py`.

Usage:
    python -m ticbot_chunking.scripts.ingest_from_blob output/chunks_from_blob.jsonl
    python -m ticbot_chunking.scripts.ingest_from_blob output/chunks_from_blob.jsonl --prefix "FSSAI Regulation/"
    python -m ticbot_chunking.scripts.ingest_from_blob output/chunks_from_blob.jsonl --limit 5

    # Just see what would be ingested, without downloading/parsing anything:
    python -m ticbot_chunking.scripts.ingest_from_blob --list-only --prefix "Brochures/"
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from ticbot_chunking.metadata.schema import Chunk
from ticbot_chunking.pipeline import process_excel, process_pdf
from ticbot_chunking.storage import blob_store


def ingest(prefix: str | None = None, limit: int | None = None) -> tuple[list[Chunk], list[tuple[str, str]]]:
    """Returns (chunks, skipped) where `skipped` is a list of
    (blob_name, error_message) for blobs that failed to download or parse —
    e.g. Document Intelligence not being configured for a PDF blob."""
    blobs = [b for b in blob_store.list_blobs(prefix=prefix) if b.is_pdf or b.is_excel]
    if limit is not None:
        blobs = blobs[:limit]

    chunks: list[Chunk] = []
    skipped: list[tuple[str, str]] = []

    with tempfile.TemporaryDirectory(prefix="ticbot_blob_") as tmp_dir:
        for blob in blobs:
            display_name = f"{blob.container}/{blob.name}" if blob.container else blob.name
            try:
                local_path = blob_store.download_blob_to_file(blob.name, tmp_dir, container=blob.container)
                blob_chunks = process_pdf(str(local_path)) if blob.is_pdf else process_excel(str(local_path))
                for c in blob_chunks:
                    c.metadata.source_file = display_name  # preserve full blob path as source metadata
                chunks.extend(blob_chunks)
            except Exception as e:
                skipped.append((display_name, f"{type(e).__name__}: {e}"))

    return chunks, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("output_path", nargs="?", help="Where to write chunks.jsonl (omit with --list-only)")
    parser.add_argument("--prefix", default=None, help="Only consider blobs whose name starts with this prefix")
    parser.add_argument("--limit", type=int, default=None, help="Ingest at most N matching blobs")
    parser.add_argument("--list-only", action="store_true",
                         help="List matching PDF/Excel blobs and exit, without downloading or parsing")
    args = parser.parse_args()

    if args.list_only:
        blobs = [b for b in blob_store.list_blobs(prefix=args.prefix) if b.is_pdf or b.is_excel]
        if args.limit is not None:
            blobs = blobs[: args.limit]
        print(f"{len(blobs)} PDF/Excel blob(s) found:")
        for b in blobs:
            kind = "pdf" if b.is_pdf else "excel"
            print(f"  [{kind}] {b.container}/{b.name} ({b.size} bytes)")
        return

    if not args.output_path:
        parser.error("output_path is required unless --list-only is given")

    chunks, skipped = ingest(prefix=args.prefix, limit=args.limit)

    Path(args.output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_path, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")

    print(f"Wrote {len(chunks)} chunks from blob storage to {args.output_path}")
    if skipped:
        print(f"\nSkipped {len(skipped)} blob(s):")
        for name, err in skipped:
            print(f"  {name}: {err}")


if __name__ == "__main__":
    main()
