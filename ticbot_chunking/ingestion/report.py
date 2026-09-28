"""Processing statistics and the human-readable (processing_report.md) /
machine-readable (processing_report.json) reports for the end-to-end
ingestion step.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

from ticbot_chunking.ingestion.orchestrator import (
    PARSER_DOCUMENT_INTELLIGENCE,
    PARSER_LOCAL_PDF,
    PARSER_MIXED,
    IngestedDocument,
    ProcessingFailure,
)
from ticbot_chunking.ingestion.representative_checks import RepresentativeCheck
from ticbot_chunking.ingestion.source import SourceFile


def compute_processing_stats(source_kind: str, source_files: list[SourceFile], ingested_docs: list[IngestedDocument],
                              failures: list[ProcessingFailure],
                              chunks_by_strategy: dict[str, list[dict]],
                              excluded_files: list[SourceFile] | None = None) -> dict[str, Any]:
    excluded_files = excluded_files or []
    pdfs = [f for f in source_files if f.is_pdf]
    excels = [f for f in source_files if f.is_excel]
    pdf_docs = [d for d in ingested_docs if d.kind == "pdf"]
    excel_docs = [d for d in ingested_docs if d.kind == "excel"]
    text_based = [d for d in pdf_docs if d.text_classification == "text-based"]
    scanned = [d for d in pdf_docs if d.text_classification != "text-based"]
    local_parsed = [d for d in pdf_docs if d.parser == PARSER_LOCAL_PDF]
    di_parsed = [d for d in pdf_docs if d.parser == PARSER_DOCUMENT_INTELLIGENCE]
    mixed_parsed = [d for d in pdf_docs if d.parser == PARSER_MIXED]

    by_strategy = {}
    for strategy, rows in chunks_by_strategy.items():
        by_strategy[strategy] = {
            "total_chunks": len(rows),
            "chunks_by_doc_type": dict(Counter(r["metadata"].get("doc_type") for r in rows)),
            "chunks_by_parser": dict(Counter(r["metadata"].get("parser") for r in rows)),
        }

    return {
        "source_kind": source_kind,
        "total_files_in_source": len(source_files) + len(excluded_files),
        "total_files": len(source_files),
        "excluded_file_count": len(excluded_files),
        "excluded_files": [f.name for f in excluded_files],
        "pdfs": len(pdfs),
        "excel_workbooks": len(excels),
        "text_based_pdfs": len(text_based),
        "scanned_pdfs": len(scanned),
        "pdfs_processed_locally": len(local_parsed),
        "pdfs_processed_via_document_intelligence": len(di_parsed),
        "pdfs_processed_with_mixed_page_routing": len(mixed_parsed),
        "excel_sheets_processed": sum(len(d.sheets) for d in excel_docs),
        "total_pages": sum(d.total_pages for d in pdf_docs),
        "successfully_ingested": len(ingested_docs),
        "processing_failures": len(failures),
        "by_strategy": by_strategy,
    }


def build_processing_report_json(stats: dict[str, Any], ingested_docs: list[IngestedDocument],
                                  failures: list[ProcessingFailure],
                                  representative_checks: list[RepresentativeCheck]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "documents": [
            {
                "source_name": d.source_name, "filename": d.filename, "doc_type": d.doc_type, "kind": d.kind,
                "parser": d.parser, "total_pages": d.total_pages, "text_layer_fraction": d.text_layer_fraction,
                "text_classification": d.text_classification, "sheets": d.sheets, "figure_count": d.figure_count,
            }
            for d in ingested_docs
        ],
        "failures": [
            {
                "filename": f.source_name, "reason": f.reason, "parser_attempted": f.parser_attempted,
                "error": f.error, "retry_recommended": f.retry_recommended,
            }
            for f in failures
        ],
        "representative_document_validation": [
            {"topic": c.topic, "status": c.status, "finding": c.finding} for c in representative_checks
        ],
    }


def build_processing_report_markdown(report: dict[str, Any]) -> str:
    stats = report["stats"]
    lines = [
        "# TICBot Ingestion Processing Report",
        "",
        f"Generated: {report['generated_at']}",
        f"Source: `{stats['source_kind']}` (Azure Blob Storage — the sole ingestion source)",
        "",
        "## Processing statistics",
        "",
        f"- Total files found in source: {stats['total_files_in_source']}",
        f"- Files considered in this run (after exclusions): {stats['total_files']}",
        f"- Files intentionally excluded from this run: {stats['excluded_file_count']}",
        f"- PDFs: {stats['pdfs']}",
        f"- Excel workbooks: {stats['excel_workbooks']}",
        f"- Text-based PDFs: {stats['text_based_pdfs']}",
        f"- Scanned/image-based PDFs: {stats['scanned_pdfs']}",
        f"- PDFs processed locally (`local_pdf`): {stats['pdfs_processed_locally']}",
        f"- PDFs processed via Document Intelligence: {stats['pdfs_processed_via_document_intelligence']}",
        f"- PDFs processed with mixed page-level routing (`{PARSER_MIXED}`): "
        f"{stats['pdfs_processed_with_mixed_page_routing']}",
        f"- Excel sheets processed: {stats['excel_sheets_processed']}",
        f"- Total PDF pages: {stats['total_pages']}",
        f"- Successfully ingested: {stats['successfully_ingested']}",
        f"- Processing failures: {stats['processing_failures']}",
        "",
        "### Chunks by strategy",
        "",
        "| Strategy | Total chunks | By doc_type | By parser |",
        "|---|---|---|---|",
    ]
    for strategy, s in stats["by_strategy"].items():
        lines.append(f"| {strategy} | {s['total_chunks']} | {s['chunks_by_doc_type']} | {s['chunks_by_parser']} |")

    lines += ["", "## Documents processed", "", "| Source | doc_type | parser | pages | classification |", "|---|---|---|---|---|"]
    for d in report["documents"]:
        cls = d["text_classification"] or ("—" if d["kind"] == "excel" else "")
        lines.append(f"| {d['source_name']} | {d['doc_type']} | {d['parser']} | {d['total_pages'] or ''} | {cls} |")

    lines += ["", "## Processing failures", ""]
    if report["failures"]:
        lines.append("| Filename | Reason | Parser attempted | Error | Retry recommended |")
        lines.append("|---|---|---|---|---|")
        for f in report["failures"]:
            lines.append(f"| {f['filename']} | {f['reason']} | {f['parser_attempted']} | {f['error']} | {f['retry_recommended']} |")
    else:
        lines.append("None.")

    lines += ["", "## Representative document validation", ""]
    lines.append("| Topic | Status | Finding |")
    lines.append("|---|---|---|")
    for c in report["representative_document_validation"]:
        lines.append(f"| {c['topic']} | {c['status']} | {c['finding']} |")

    if stats["excluded_files"]:
        lines += [
            "", "## Intentionally excluded files", "",
            "**This dataset is NOT fully validated** — the file(s) below were deliberately left "
            "out of this run (via `--exclude-file`) and were not downloaded, parsed, or chunked. "
            "Nothing in this report — including the representative-document validation section — "
            "reflects their content.",
            "",
        ]
        for name in stats["excluded_files"]:
            lines.append(f"- `{name}`")

    return "\n".join(lines)
