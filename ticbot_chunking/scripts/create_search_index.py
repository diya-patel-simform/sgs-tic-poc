#!/usr/bin/env python3
"""CLI: create (or validate) the Azure AI Search index schema for one or
all four chunking strategies.

    Validated chunks (experiments/<strategy>/chunks.jsonl)
                 -> Azure AI Search index schema (this script)
                 -> index created and validated

This step is schema-only: it does not read chunks.jsonl, generate
embeddings, upload documents, or run a query. It exists so the four
strategies can be compared later in separate, identically-shaped indexes —
see `ticbot_chunking/search/schema.py` for the field list and
`ticbot_chunking/search/index_manager.py` for index create/exists/recreate.

Usage:
    # One strategy, using its default index name (ticbot-chunks-<strategy>):
    python -m ticbot_chunking.scripts.create_search_index --strategy fixed

    # One strategy, explicit index name:
    python -m ticbot_chunking.scripts.create_search_index \\
        --strategy structure_aware --index ticbot-chunks-structure

    # All four strategies at once, each into its own default-named index:
    python -m ticbot_chunking.scripts.create_search_index --strategy all

    # Build + validate the schema locally without calling Azure AI Search
    # at all (useful when AZURE_SEARCH_ADMIN_KEY isn't configured yet):
    python -m ticbot_chunking.scripts.create_search_index --strategy all --dry-run

    # Only if you explicitly want to drop and rebuild an index that already
    # exists (never happens by default — an existing index is left alone
    # and reported as such):
    python -m ticbot_chunking.scripts.create_search_index --strategy fixed --recreate

Azure AI Search is configured via AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_ADMIN_KEY
(see .env.example). The vector field's dimension comes from
AZURE_OPENAI_EMBEDDING_DIMENSIONS if set, else a known default for
AZURE_OPENAI_EMBEDDING_DEPLOYMENT (3072 for text-embedding-3-large) — see
config.OPENAI.embedding_dimensions. It is never guessed silently: an
unresolvable dimension is a hard error.
"""
from __future__ import annotations

import argparse
import sys

from ticbot_chunking.config import OPENAI, SEARCH
from ticbot_chunking.scripts.run_chunking_experiments import STRATEGIES
from ticbot_chunking.search.index_manager import create_index, get_index
from ticbot_chunking.search.schema import STRATEGY_INDEX_NAMES, build_index
from ticbot_chunking.search.validate import validate_index_schema


def _process_one(strategy: str, index_name: str, vector_dimensions: int, recreate: bool, dry_run: bool) -> bool:
    """Returns True if this index is in a valid, expected state by the end
    (built successfully and, unless dry-run/not-configured, live-validated
    against the real service)."""
    print(f"\n=== {strategy} -> {index_name} ===")

    index = build_index(index_name, strategy, vector_dimensions)
    problems = validate_index_schema(index, vector_dimensions)
    if problems:
        print(f"  SCHEMA PROBLEM(S) building the index definition (nothing sent to Azure):")
        for p in problems:
            print(f"    - {p}")
        return False
    print(f"  Schema OK: {len(index.fields)} fields, vector dimension {vector_dimensions}.")

    if dry_run:
        print("  --dry-run given: not connecting to Azure AI Search.")
        return True
    if not SEARCH.is_configured:
        print("  Azure AI Search is not configured (AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_ADMIN_KEY "
              "missing — see .env.example). Schema validated locally only; nothing was created.")
        return True

    result = create_index(index, recreate=recreate)
    if result == "exists":
        print(f"  Index '{index_name}' already exists — left untouched (pass --recreate to rebuild it).")
    elif result == "recreated":
        print(f"  Index '{index_name}' already existed and was recreated (--recreate given).")
    else:
        print(f"  Index '{index_name}' created.")

    live = get_index(index_name)
    live_problems = validate_index_schema(live, vector_dimensions)
    if live_problems:
        print(f"  LIVE VALIDATION FAILED for '{index_name}':")
        for p in live_problems:
            print(f"    - {p}")
        return False
    print(f"  Live validation OK: '{index_name}' matches the expected schema.")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strategy", required=True, choices=(*STRATEGIES, "all"),
                         help="Which strategy's index to create/validate, or 'all' for all four")
    parser.add_argument("--index", default=None,
                         help="Explicit index name (overrides the default ticbot-chunks-<strategy> name). "
                              "Only valid with a single --strategy, not with --strategy all.")
    parser.add_argument("--vector-dimensions", type=int, default=None,
                         help="Override the vector field's dimension (default: config.OPENAI.embedding_dimensions)")
    parser.add_argument("--recreate", action="store_true",
                         help="If the index already exists, delete and recreate it. Without this flag, an "
                              "existing index is always left untouched and reported as already existing.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Build and validate the schema locally; never connect to Azure AI Search")
    args = parser.parse_args()

    if args.index and args.strategy == "all":
        parser.error("--index cannot be used with --strategy all (each strategy needs its own index name)")

    vector_dimensions = args.vector_dimensions or OPENAI.embedding_dimensions
    if not vector_dimensions:
        parser.error(
            "Could not determine the embedding vector dimension. Set AZURE_OPENAI_EMBEDDING_DIMENSIONS "
            "explicitly, use a recognized AZURE_OPENAI_EMBEDDING_DEPLOYMENT name, or pass --vector-dimensions."
        )

    strategies = list(STRATEGIES) if args.strategy == "all" else [args.strategy]

    results = {}
    for strategy in strategies:
        index_name = args.index or STRATEGY_INDEX_NAMES[strategy]
        results[index_name] = _process_one(strategy, index_name, vector_dimensions, args.recreate, args.dry_run)

    print(f"\n{'=' * 60}")
    for index_name, ok in results.items():
        print(f"{'OK  ' if ok else 'FAIL'}  {index_name}")

    if not all(results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
