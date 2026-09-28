#!/usr/bin/env python3
"""CLI: manually test the RAG backend end to end.

    question -> existing retrieval client -> top-K chunks -> context
             -> Azure OpenAI chat model -> grounded answer + citations

Usage:
    python -m ticbot_chunking.scripts.ask_rag --question "What services are provided by SGS Molecular?"

    python -m ticbot_chunking.scripts.ask_rag --question "..." --mode vector --top-k 10

    python -m ticbot_chunking.scripts.ask_rag --question "..." --strategy fixed

    # Machine-readable output (the full RagResponse, including every
    # retrieved chunk — useful for debugging low-confidence answers):
    python -m ticbot_chunking.scripts.ask_rag --question "..." --json
"""
from __future__ import annotations

import argparse
import json

from ticbot_chunking.rag.rag_service import answer
from ticbot_chunking.scripts.run_chunking_experiments import STRATEGIES
from ticbot_chunking.search.retrieval_client import MODES


def _print_human(response) -> None:
    print("Answer:")
    print(response.answer)
    print()
    print("Citations:")
    if response.citations:
        for i, c in enumerate(response.citations, start=1):
            location = ", ".join(
                f"{label}: {value}" for label, value in [
                    ("page", c.page), ("sheet", c.sheet), ("cell range", c.cell_range), ("section", c.section),
                ] if value
            )
            extra = ", ".join(
                f"{label}: {value}" for label, value in [
                    ("certificate", c.certificate_no), ("lab", c.lab_location),
                    ("discipline", c.discipline), ("material", c.material),
                ] if value
            )
            line = f"  {i}. {c.source_file}"
            if location:
                line += f" ({location})"
            print(line)
            if extra:
                print(f"     {extra}")
    else:
        print("  (none)")
    print()
    print(f"Retrieved sources ({len(response.retrieved_chunks)}, strategy={response.strategy}, "
          f"mode={response.retrieval_mode}, top_k={response.top_k}):")
    for r in response.retrieved_chunks:
        print(f"  [{r.rank}] score={r.score}  {r.source_file}  pages={r.pages}  sheet={r.sheet}  "
              f"cell_range={r.cell_range}")
    print()
    print(f"Retrieval latency: {response.retrieval_latency_seconds:.3f}s  "
          f"LLM latency: {response.llm_latency_seconds}  Total: {response.total_latency_seconds:.3f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--question", required=True)
    parser.add_argument("--strategy", choices=STRATEGIES, default="hybrid",
                         help="Which chunking strategy's index to retrieve from (default: hybrid)")
    parser.add_argument("--mode", choices=MODES, default="hybrid", help="Retrieval mode (default: hybrid)")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--filter", default=None, help="Raw Azure AI Search OData filter")
    parser.add_argument("--index", default=None,
                         help="Explicit index name override (e.g. to test against an index built from a "
                              "different document set instead of the default ticbot-chunks-<strategy>)")
    parser.add_argument("--json", action="store_true", help="Print the full RagResponse as JSON")
    args = parser.parse_args()

    response = answer(args.question, strategy=args.strategy, mode=args.mode, top_k=args.top_k, filter=args.filter,
                       index_name=args.index)

    if args.json:
        print(json.dumps(response.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_human(response)


if __name__ == "__main__":
    main()
