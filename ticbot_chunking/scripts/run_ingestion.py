#!/usr/bin/env python3
"""CLI: end-to-end ingestion — Azure Blob Storage -> parser routing
(local PDF parser / Document Intelligence / Excel parser) -> the four
existing chunking strategies (unmodified) -> a processing report.

    Blob Storage -> PDF/Excel detection -> PDF: classify each page
                                                 TEXT pages       -> local parser
                                                 SCANNED/AMBIGUOUS -> Document Intelligence
                                                 (only those page numbers, e.g. "41,81-82" —
                                                  never the whole document)
                                                 -> merge by original page number
                                            Excel: existing Excel parser
                 -> common parsed representation -> chunking strategies
                 -> processing report (+ chunks.jsonl per strategy)

PDF routing is page-level (called via `ingestion.orchestrator.ingest_document`,
which uses `parsers.page_router.parse_pdf_paged`) — see that module for why:
a document that's mostly text-based with a minority of scanned pages sends
only those pages to Document Intelligence, and vice versa. Unchanged:
`chunkers.excel_blocks` (via the existing `hybrid` strategy), and all four
chunking strategies via `scripts.run_chunking_experiments.run_strategy`.
Does not create an Azure AI Search index, generate embeddings, or touch
Streamlit.

Azure Blob Storage (`storage/blob_store.py`) is the sole ingestion source —
there is no local-directory fallback. If it isn't configured, inaccessible,
or returns no files, this fails clearly (a RuntimeError naming the missing
AZURE_STORAGE_* env vars) instead of silently reading local files.

Usage:
    python -m ticbot_chunking.scripts.run_ingestion --output-dir experiments
    python -m ticbot_chunking.scripts.run_ingestion --output-dir experiments --prefix "FSSAI Regulation/"
    # Skip one or more specific source files for this run only (e.g. a very
    # large file, to validate the rest of the pipeline first). Excluded
    # files are recorded in the processing report — this is never silently
    # treated as a complete-dataset run:
    python -m ticbot_chunking.scripts.run_ingestion --output-dir experiments \\
        --exclude-file "ISOIEC 17025 Certiificate and Scope of Accreditation- Validity up to 19-11-2027.pdf"
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from ticbot_chunking.experiments import fixed_size, recursive, structure_aware, stats as experiment_stats
from ticbot_chunking.experiments import hybrid as hybrid_strategy
from ticbot_chunking.experiments.common import build_doc_metadata
from ticbot_chunking.ingestion import report as ingestion_report
from ticbot_chunking.ingestion.orchestrator import IngestedDocument, ProcessingFailure, _classify_retry, ingest_document
from ticbot_chunking.ingestion.representative_checks import run_representative_checks
from ticbot_chunking.ingestion.source import fetch_to_local, list_source_files
from ticbot_chunking.scripts import run_chunking_experiments as rce

STRATEGIES = rce.STRATEGIES


def _run_strategy_for_doc(strategy: str, doc: IngestedDocument, chunk_size: int, overlap: int,
                           max_chunk_size: int) -> list:
    parsed = doc.parsed
    if strategy == "fixed":
        chunks = fixed_size.chunk_fixed_size(parsed, build_doc_metadata(parsed), chunk_size, overlap, max_chunk_size)
    elif strategy == "recursive":
        chunks = recursive.chunk_recursive(parsed, build_doc_metadata(parsed), chunk_size, overlap, max_chunk_size)
    elif strategy == "structure_aware":
        chunks = structure_aware.chunk_structure_aware(parsed, build_doc_metadata(parsed), chunk_size, overlap,
                                                         max_chunk_size)
    elif strategy == "hybrid":
        chunks = hybrid_strategy.chunk_hybrid(parsed)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    # Force-correct provenance regardless of what the underlying chunker
    # set internally: at least one existing chunker (chunk_regulation)
    # builds a chunk's source_file from the parsed LayoutDocument's own
    # `source_file` (the local temp file path used during this run's
    # download/parse step) rather than from DocumentMetadata.source_file
    # (the real blob path) — which would otherwise silently leak the
    # ingestion temp directory path into citation metadata. Corrected here
    # at the orchestration layer, not by modifying any of the four
    # chunking strategies (or the chunkers they call) themselves.
    for c in chunks:
        c.metadata.source_file = doc.source_name
        c.metadata.parser = doc.parser
    return chunks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output-dir", default="experiments", help="Where <strategy>/chunks.jsonl is written")
    parser.add_argument("--prefix", default=None, help="Only ingest blobs whose name starts with this prefix")
    parser.add_argument("--container", default=None,
                         help="Restrict to this one Blob Storage container for this run only (e.g. to test "
                              "against a different document set) — overrides AZURE_STORAGE_CONTAINER_NAME "
                              "without needing to edit .env")
    parser.add_argument("--exclude-file", action="append", default=[], dest="exclude_files",
                         help="Skip this source file for this run only (matched against the full source name, "
                              "the raw blob name, or the basename — case-sensitive). Repeatable. The file is "
                              "NOT deleted from Blob Storage and is recorded in the processing report as an "
                              "intentional exclusion, so the report is never presented as a complete-dataset run.")
    parser.add_argument("--chunk-size", type=int, default=rce.DEFAULT_CHUNK_SIZE)
    parser.add_argument("--overlap", type=int, default=rce.DEFAULT_OVERLAP)
    parser.add_argument("--max-chunk-size", type=int, default=rce.DEFAULT_MAX_CHUNK_SIZE)
    args = parser.parse_args()

    def _match_candidates(sf) -> set[str]:
        candidates = {sf.name, Path(sf.name).name}
        if sf.blob_name:
            candidates.add(sf.blob_name)
            candidates.add(Path(sf.blob_name).name)
        return candidates

    source_kind, all_source_files = list_source_files(prefix=args.prefix, container=args.container)

    exclude_set = set(args.exclude_files)
    source_files = []
    excluded_files = []
    matched_excludes = set()
    for sf in all_source_files:
        candidates = _match_candidates(sf)
        hit = candidates & exclude_set
        if hit:
            matched_excludes |= hit
            excluded_files.append(sf)
        else:
            source_files.append(sf)

    print(f"Source: {source_kind} — {len(all_source_files)} file(s) found "
          f"({sum(f.is_pdf for f in all_source_files)} PDF, {sum(f.is_excel for f in all_source_files)} Excel)")
    if excluded_files:
        print(f"Excluding {len(excluded_files)} file(s) from this run (not deleted from source):")
        for sf in excluded_files:
            print(f"  EXCLUDED: {sf.name}")
    unmatched = exclude_set - matched_excludes
    if unmatched:
        print(f"WARNING: --exclude-file value(s) matched no discovered source file: {sorted(unmatched)}")
    print(f"Processing {len(source_files)} file(s) in this run.")

    output_root = Path(args.output_dir)
    ingested_docs = []
    failures: list[ProcessingFailure] = []

    with tempfile.TemporaryDirectory(prefix="ticbot_ingestion_") as tmp_dir:
        for sf in source_files:
            try:
                local_path = fetch_to_local(source_kind, sf.name, tmp_dir,
                                             container=sf.container, blob_name=sf.blob_name)
            except Exception as e:
                failures.append(ProcessingFailure(
                    source_name=sf.name, reason="download failed", parser_attempted=None,
                    error=f"{type(e).__name__}: {e}", retry_recommended=_classify_retry(e),
                ))
                print(f"  FAILED (download): {sf.name}: {e}")
                continue

            try:
                doc = ingest_document(sf.name, local_path)
            except Exception as e:
                parser_attempted = "document_intelligence" if "document intelligence" in str(e).lower() else "unknown"
                failures.append(ProcessingFailure(
                    source_name=sf.name, reason="parsing failed", parser_attempted=parser_attempted,
                    error=f"{type(e).__name__}: {e}", retry_recommended=_classify_retry(e),
                ))
                print(f"  FAILED (parse): {sf.name}: {e}")
                continue

            ingested_docs.append(doc)
            print(f"  OK: {doc.source_name} — kind={doc.kind} parser={doc.parser} doc_type={doc.doc_type}"
                  + (f" pages={doc.total_pages} ({doc.text_classification})" if doc.kind == "pdf" else
                     f" sheets={len(doc.sheets)}"))

        chunks_by_strategy: dict[str, list[dict]] = {}
        for strategy in STRATEGIES:
            print(f"\n=== {strategy} ===")
            chunks = []
            for doc in ingested_docs:
                chunks.extend(_run_strategy_for_doc(strategy, doc, args.chunk_size, args.overlap, args.max_chunk_size))

            strategy_dir = output_root / strategy
            rce.write_jsonl(chunks, strategy_dir / "chunks.jsonl")
            rows = [c.to_dict() for c in chunks]
            chunks_by_strategy[strategy] = rows

            strategy_stats = experiment_stats.compute_strategy_stats(rows, strategy, args.chunk_size, args.max_chunk_size)
            with open(strategy_dir / "stats.json", "w", encoding="utf-8") as f:
                json.dump(strategy_stats, f, indent=2)
            print(f"Wrote {len(chunks)} chunks to {strategy_dir / 'chunks.jsonl'}")

        all_stats = experiment_stats.load_all_stats(output_root)
        if all_stats:
            comparison = experiment_stats.build_comparison_report(all_stats)
            with open(output_root / "comparison_report.json", "w", encoding="utf-8") as f:
                json.dump(comparison, f, indent=2)

        representative_checks = run_representative_checks(ingested_docs, chunks_by_strategy)

    # (temp dir cleaned up here — everything needing the downloaded files is done above)

    proc_stats = ingestion_report.compute_processing_stats(source_kind, source_files, ingested_docs, failures,
                                                             chunks_by_strategy, excluded_files=excluded_files)
    report_data = ingestion_report.build_processing_report_json(proc_stats, ingested_docs, failures,
                                                                  representative_checks)
    output_root.mkdir(parents=True, exist_ok=True)
    with open(output_root / "processing_report.json", "w", encoding="utf-8") as f:
        json.dump(report_data, f, indent=2)
    (output_root / "processing_report.md").write_text(
        ingestion_report.build_processing_report_markdown(report_data), encoding="utf-8"
    )

    print(f"\n{'=' * 60}")
    print(f"Processed {proc_stats['successfully_ingested']}/{proc_stats['total_files']} file(s) considered "
          f"in this run, {proc_stats['processing_failures']} failure(s)")
    if proc_stats["excluded_file_count"]:
        print(f"({proc_stats['excluded_file_count']} of {proc_stats['total_files_in_source']} files in the "
              f"source were intentionally excluded — this is NOT a complete-dataset run)")
    print(f"Processing report written to {output_root / 'processing_report.md'} (+ .json)")


if __name__ == "__main__":
    main()
