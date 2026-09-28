#!/usr/bin/env python3
"""CLI: run one query against one strategy's Azure AI Search index, in one
retrieval mode. The common, reusable interface behind the retrieval
evaluation (`run_retrieval_eval.py`, `evaluate_retrieval.py`).

Usage:
    python -m ticbot_chunking.scripts.search_chunks \\
        --strategy hybrid --mode hybrid --query "arsenic limit in milk"

    python -m ticbot_chunking.scripts.search_chunks \\
        --strategy fixed --mode vector --query "NABL certificate validity" --top-k 10

    # Metadata filtering (raw Azure AI Search OData filter syntax):
    python -m ticbot_chunking.scripts.search_chunks \\
        --strategy hybrid --mode keyword --query "certificate" \\
        --filter "document_type eq 'accreditation_scope'"

    # Machine-readable output:
    python -m ticbot_chunking.scripts.search_chunks --strategy hybrid --mode hybrid \\
        --query "..." --json
"""
from __future__ import annotations

import argparse
import json

from ticbot_chunking.scripts.run_chunking_experiments import STRATEGIES
from ticbot_chunking.search.retrieval_client import MODES, search


def _print_human(result) -> None:
    print(f"Query: {result.query!r}  strategy={result.strategy}  index={result.index_name}  "
          f"mode={result.mode}  top_k={result.top_k}  filter={result.filter!r}")
    print(f"Latency: {result.latency_seconds:.3f}s  Results: {len(result.results)}")
    for r in result.results:
        print(f"\n  [{r.rank}] score={r.score} reranker_score={r.reranker_score} chunk_id={r.chunk_id}")
        print(f"      source_file={r.source_file}  pages={r.pages}  sheet={r.sheet}  cell_range={r.cell_range}")
        print(f"      document_type={r.document_type}  chunk_type={r.chunk_type}  "
              f"section_path={r.section_path}  section_number={r.section_number}")
        if any([r.authority, r.lab_location, r.certificate_no, r.discipline, r.material, r.facility]):
            print(f"      authority={r.authority}  lab_location={r.lab_location}  "
                  f"certificate_no={r.certificate_no}  discipline={r.discipline}  "
                  f"material={r.material}  facility={r.facility}")
        print(f"      text: {(r.text or '')[:200]!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--strategy", required=True, choices=STRATEGIES, help="Which strategy's index to query")
    parser.add_argument("--mode", required=True, choices=MODES, help="Retrieval mode")
    parser.add_argument("--query", required=True, help="The search query text")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to return (default: 5)")
    parser.add_argument("--filter", default=None,
                         help="Raw Azure AI Search OData filter, e.g. \"document_type eq 'regulation'\"")
    parser.add_argument("--index", default=None, help="Explicit index name override")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON instead of a human summary")
    args = parser.parse_args()

    result = search(args.strategy, args.mode, args.query, top_k=args.top_k, filter=args.filter,
                     index_name=args.index)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_human(result)


if __name__ == "__main__":
    main()
