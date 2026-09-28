#!/usr/bin/env python3
"""CLI: generate embeddings for a strategy's chunks.jsonl and upload them
(as Azure AI Search documents, keyed by a stable chunk_id) to that
strategy's index.

    Validated chunks (experiments/<strategy>/chunks.jsonl)
                 -> Azure OpenAI embeddings
                 -> Azure AI Search document (chunk_id, text, metadata, vector)
                 -> upload to the strategy's index (create, or update in
                    place if that chunk_id already exists — never a
                    duplicate)

Does not implement retrieval, RAG, or Streamlit — see the project README.
Cost/safety: never processes all four strategies unless --all is given
explicitly; a single --strategy run is the way to test this against one
index (e.g. hybrid) before a full run.

Usage:
    # One strategy at a time (recommended before --all):
    python -m ticbot_chunking.scripts.index_chunks --strategy hybrid

    # Explicit index name override (single-strategy only):
    python -m ticbot_chunking.scripts.index_chunks --strategy fixed --index ticbot-chunks-fixed

    # All four strategies — must be requested explicitly:
    python -m ticbot_chunking.scripts.index_chunks --all

    # Schema-only dry run: fetches and validates the target index's live
    # schema and reports how many chunks would be processed, without
    # calling Azure OpenAI or uploading anything:
    python -m ticbot_chunking.scripts.index_chunks --strategy hybrid --dry-run

    # Where chunks.jsonl lives, and batching (used for both embedding
    # requests and Search uploads):
    python -m ticbot_chunking.scripts.index_chunks --strategy hybrid \\
        --chunks-dir experiments_blob --batch-size 16
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ticbot_chunking.config import OPENAI, SEARCH
from ticbot_chunking.scripts.run_chunking_experiments import STRATEGIES
from ticbot_chunking.search.embedding_client import DEFAULT_MAX_RETRIES, DEFAULT_RETRY_BACKOFF_SECONDS
from ticbot_chunking.search.index_content_validation import validate_indexed_content
from ticbot_chunking.search.index_manager import get_index
from ticbot_chunking.search.indexer import index_chunks_file, load_chunks_jsonl, require_search_client
from ticbot_chunking.search.schema import STRATEGY_INDEX_NAMES
from ticbot_chunking.search.validate import validate_index_schema


def _process_one(strategy: str, index_name: str, chunks_dir: str, batch_size: int, max_retries: int,
                  retry_backoff_seconds: float, dry_run: bool) -> bool:
    print(f"\n=== {strategy} -> {index_name} ===")
    chunks_path = Path(chunks_dir) / strategy / "chunks.jsonl"
    if not chunks_path.exists():
        print(f"  ERROR: {chunks_path} does not exist.")
        return False

    rows = load_chunks_jsonl(chunks_path)
    print(f"  Chunks read: {len(rows)} (from {chunks_path})")

    if not SEARCH.is_configured:
        print("  ERROR: Azure AI Search is not configured (AZURE_SEARCH_ENDPOINT / "
              "AZURE_SEARCH_ADMIN_KEY missing — see .env.example).")
        return False

    try:
        live_index = get_index(index_name)
    except Exception as e:
        print(f"  ERROR: could not fetch index '{index_name}': {type(e).__name__}: {e}")
        return False

    vector_dimensions = OPENAI.embedding_dimensions
    if not vector_dimensions:
        print("  ERROR: could not determine the expected embedding vector dimension "
              "(config.OPENAI.embedding_dimensions).")
        return False

    schema_problems = validate_index_schema(live_index, vector_dimensions)
    if schema_problems:
        print(f"  SCHEMA PROBLEM(S) on live index '{index_name}' — not indexing:")
        for p in schema_problems:
            print(f"    - {p}")
        return False
    print(f"  Schema OK: '{index_name}' matches the expected schema ({len(live_index.fields)} fields, "
          f"vector dimension {vector_dimensions}).")

    if dry_run:
        print(f"  --dry-run given: would generate embeddings for {len(rows)} chunk(s) and upload them to "
              f"'{index_name}'. Not calling Azure OpenAI or uploading anything.")
        return True

    if not OPENAI.is_configured:
        print("  ERROR: Azure OpenAI is not configured (AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY / "
              "AZURE_OPENAI_EMBEDDING_DEPLOYMENT missing — see .env.example).")
        return False

    result = index_chunks_file(chunks_path, strategy, index_name, batch_size=batch_size,
                                max_retries=max_retries, retry_backoff_seconds=retry_backoff_seconds)

    print(f"  Chunks read:                  {result.chunks_read}")
    print(f"  Embeddings generated:         {result.embeddings_generated}")
    print(f"  Documents uploaded (new):     {result.documents_uploaded}")
    print(f"  Documents updated (existing): {result.documents_updated}")
    print(f"  Embedding failures:           {len(result.embedding_failures)}")
    for f in result.embedding_failures:
        print(f"    - index {f['index_in_file']} ({f['source_file']}): {f['error']}")
    print(f"  Upload failures:              {len(result.upload_failures)}")
    for f in result.upload_failures:
        print(f"    - chunk_id {f['chunk_id']}: {f['error']}")

    print(f"  Validating indexed content in '{index_name}'...")
    client = require_search_client(index_name)
    content_report = validate_indexed_content(client, expected_chunk_count=result.chunks_read, index_name=index_name)
    print(f"  Expected chunk count (from chunks.jsonl): {content_report.expected_chunk_count}")
    print(f"  Azure AI Search document count:           {content_report.live_document_count}")
    print(f"  Count matches:                            {content_report.count_matches}")
    print(f"  Vector field populated (sample of {content_report.sampled_documents}): "
          f"{content_report.vector_field_populated}")
    print(f"  Text field populated:                     {content_report.text_field_populated}")
    print(f"  Source metadata populated:                {content_report.source_metadata_populated}")
    print(f"  Chunk IDs unique in sample:                {content_report.chunk_ids_unique_in_sample}")
    if content_report.problems:
        print("  CONTENT VALIDATION PROBLEM(S):")
        for p in content_report.problems:
            print(f"    - {p}")

    return result.total_failures == 0 and content_report.ok


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strategy", choices=STRATEGIES, default=None, help="Index this one strategy")
    parser.add_argument("--all", action="store_true",
                         help="Index all four strategies. Must be given explicitly — never the default.")
    parser.add_argument("--index", default=None,
                         help="Explicit index name (overrides the default ticbot-chunks-<strategy> name). "
                              "Only valid with a single --strategy, not with --all.")
    parser.add_argument("--chunks-dir", default="experiments",
                         help="Base directory containing <strategy>/chunks.jsonl (default: experiments)")
    parser.add_argument("--batch-size", type=int, default=16,
                         help="Batch size for both embedding requests and Search uploads (default: 16)")
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES,
                         help=f"Max retries for a transient embedding-batch error (default: {DEFAULT_MAX_RETRIES})")
    parser.add_argument("--retry-backoff-seconds", type=float, default=DEFAULT_RETRY_BACKOFF_SECONDS,
                         help="Base backoff (doubled per retry) for a transient embedding-batch error "
                              f"(default: {DEFAULT_RETRY_BACKOFF_SECONDS})")
    parser.add_argument("--dry-run", action="store_true",
                         help="Validate the target index's live schema and report chunk counts; "
                              "never calls Azure OpenAI or uploads anything")
    args = parser.parse_args()

    if bool(args.strategy) == bool(args.all):
        parser.error("specify exactly one of --strategy <name> or --all")
    if args.index and args.all:
        parser.error("--index cannot be used with --all (each strategy needs its own index name)")

    strategies = list(STRATEGIES) if args.all else [args.strategy]

    results = {}
    for strategy in strategies:
        index_name = args.index or STRATEGY_INDEX_NAMES[strategy]
        results[index_name] = _process_one(strategy, index_name, args.chunks_dir, args.batch_size,
                                            args.max_retries, args.retry_backoff_seconds, args.dry_run)

    print(f"\n{'=' * 60}")
    for index_name, ok in results.items():
        print(f"{'OK  ' if ok else 'FAIL'}  {index_name}")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
