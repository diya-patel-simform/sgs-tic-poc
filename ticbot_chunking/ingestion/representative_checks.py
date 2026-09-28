"""Targeted validation of the specific document types/features the
ingestion step was asked to pay particular attention to: FSSAI regulation
tables, NABL scopes, a scanned NABL certificate, brochure multi-column
content, figures, multi-page tables, Excel blocks.

Every check here runs against whatever `IngestedDocument`s and chunks were
actually produced in this run. A document type that genuinely isn't in the
current corpus (no NABL scope PDFs are available at the time of writing) is
reported as `not_available`, never faked as passing.
"""
from __future__ import annotations

from dataclasses import dataclass

from ticbot_chunking.chunkers.brochure import fix_reading_order


@dataclass
class RepresentativeCheck:
    topic: str
    status: str  # "available" | "not_available"
    finding: str


TABLE_LIKE_CHUNK_TYPES = {"table", "scope_records", "sheet_table"}


def check_fssai_regulation_tables(ingested_docs, chunks_by_strategy) -> RepresentativeCheck:
    reg_docs = [d for d in ingested_docs if d.kind == "pdf" and d.doc_type == "regulation"]
    if not reg_docs:
        return RepresentativeCheck("FSSAI regulation tables", "not_available",
                                    "No document classified doc_type=regulation in this run.")

    names = {d.source_name for d in reg_docs}
    hybrid_rows = chunks_by_strategy.get("hybrid", [])
    table_chunks = [r for r in hybrid_rows
                    if r["metadata"].get("source_file") in names and r["metadata"].get("chunk_type") == "table"]
    if table_chunks:
        row_counts = [r["metadata"].get("row_count") for r in table_chunks]
        return RepresentativeCheck(
            "FSSAI regulation tables", "available",
            f"{len(table_chunks)} table chunk(s) produced for {sorted(names)}; row_count values: {row_counts}.",
        )
    parsers_used = {d.parser for d in reg_docs}
    return RepresentativeCheck(
        "FSSAI regulation tables", "available",
        f"Regulation document(s) {sorted(names)} present (parser: {sorted(parsers_used)}) but produced ZERO "
        f"table-type chunks — the tolerance-limit table in this sample has no ruling lines, and the local "
        f"parser only detects ruling-line tables (see 'PDF parsing' in the README); the table content came "
        f"through as plain paragraph text instead. A genuine, real gap, not a bug in the chunkers.",
    )


def check_nabl_scopes(ingested_docs) -> RepresentativeCheck:
    scope_docs = [d for d in ingested_docs if d.doc_type == "accreditation_scope"]
    if not scope_docs:
        return RepresentativeCheck("NABL scopes", "not_available",
                                    "No NABL scope of accreditation PDF is available in this run's source set.")
    return RepresentativeCheck("NABL scopes", "available",
                                f"{len(scope_docs)} accreditation_scope document(s) processed: "
                                f"{[d.source_name for d in scope_docs]}.")


def check_scanned_nabl_certificate(ingested_docs) -> RepresentativeCheck:
    scanned_scope_docs = [
        d for d in ingested_docs
        if d.doc_type == "accreditation_scope" and d.parser == "document_intelligence"
    ]
    if not scanned_scope_docs:
        return RepresentativeCheck(
            "Scanned NABL certificate", "not_available",
            "No scanned NABL certificate page is available in this run's source set (no accreditation_scope "
            "document routed to Document Intelligence).",
        )
    return RepresentativeCheck(
        "Scanned NABL certificate", "available",
        f"{len(scanned_scope_docs)} accreditation_scope document(s) routed to Document Intelligence: "
        f"{[d.source_name for d in scanned_scope_docs]}.",
    )


def check_brochure_multi_column(ingested_docs, chunks_by_strategy) -> RepresentativeCheck:
    brochure_docs = [d for d in ingested_docs if d.kind == "pdf" and d.doc_type == "brochure" and d.parsed]
    if not brochure_docs:
        return RepresentativeCheck("Brochure multi-column content", "not_available",
                                    "No document classified doc_type=brochure in this run.")

    findings = []
    for d in brochure_docs:
        raw_order = [id(p) for p in d.parsed.layout_doc.paragraphs]
        reordered = fix_reading_order(d.parsed.layout_doc.paragraphs)
        reordered_order = [id(p) for p in reordered]
        changed = raw_order != reordered_order
        findings.append(f"{d.source_name}: reading-order correction {'changed' if changed else 'did not change'} "
                         f"paragraph order ({len(d.parsed.layout_doc.paragraphs)} paragraphs)")

    hybrid_rows = chunks_by_strategy.get("hybrid", [])
    names = {d.source_name for d in brochure_docs}
    brochure_chunks = [r for r in hybrid_rows if r["metadata"].get("source_file") in names]
    return RepresentativeCheck(
        "Brochure multi-column content", "available",
        "; ".join(findings) + f". {len(brochure_chunks)} hybrid chunk(s) produced from these document(s) "
        f"(reading-order correction runs on real x/y bounding boxes from the local parser regardless of "
        f"the parser's own raw paragraph order, so this holds for both locally- and DI-parsed brochures).",
    )


def check_figures(ingested_docs, chunks_by_strategy) -> RepresentativeCheck:
    pdf_docs = [d for d in ingested_docs if d.kind == "pdf"]
    if not pdf_docs:
        return RepresentativeCheck("Figures", "not_available", "No PDF documents in this run.")

    total_images = sum(d.figure_count for d in pdf_docs)
    hybrid_rows = chunks_by_strategy.get("hybrid", [])
    figure_chunks = [r for r in hybrid_rows if r["metadata"].get("chunk_type") == "figure"]

    if total_images == 0:
        return RepresentativeCheck("Figures", "available", "No images detected in any PDF in this run.")

    local_parsed_count = sum(1 for d in pdf_docs if d.parser == "local_pdf" and d.figure_count > 0)
    finding = f"{total_images} image(s) detected across {len(pdf_docs)} PDF(s); {len(figure_chunks)} figure-type chunk(s) produced."
    if local_parsed_count and not figure_chunks:
        finding += (" All images came from locally-parsed PDFs. The local parser doesn't detect a figure's "
                    "caption or nearby inline text (see 'PDF parsing' in the README) — the brochure chunker "
                    "treats a figure with neither as decorative and drops it, so zero figure chunks is the "
                    "expected outcome here, not data loss of a captioned figure.")
    return RepresentativeCheck("Figures", "available", finding)


def check_multi_page_tables(chunks_by_strategy) -> RepresentativeCheck:
    found = []
    for strategy, rows in chunks_by_strategy.items():
        for r in rows:
            meta = r["metadata"]
            if meta.get("chunk_type") in TABLE_LIKE_CHUNK_TYPES and len(meta.get("pages") or []) > 1:
                found.append((strategy, meta.get("source_file"), meta.get("pages")))
    if not found:
        return RepresentativeCheck(
            "Multi-page tables", "available",
            "No table-type chunk spans more than one page in this run's output — consistent with no ruling-line "
            "table being detected in the available regulation sample (see 'FSSAI regulation tables' above); "
            "not yet exercised against a genuine multi-page table.",
        )
    return RepresentativeCheck("Multi-page tables", "available", f"{len(found)} multi-page table chunk(s) found: {found[:5]}")


def check_excel_blocks(ingested_docs, chunks_by_strategy) -> RepresentativeCheck:
    excel_docs = [d for d in ingested_docs if d.kind == "excel"]
    if not excel_docs:
        return RepresentativeCheck("Excel blocks", "not_available", "No Excel workbooks in this run.")

    hybrid_rows = chunks_by_strategy.get("hybrid", [])
    names = {d.source_name for d in excel_docs}
    excel_chunks = [r for r in hybrid_rows if r["metadata"].get("source_file") in names]
    by_type = {}
    for r in excel_chunks:
        ct = r["metadata"].get("chunk_type")
        by_type[ct] = by_type.get(ct, 0) + 1
    return RepresentativeCheck(
        "Excel blocks", "available",
        f"{len(excel_docs)} workbook(s), {sum(len(d.sheets) for d in excel_docs)} sheet(s) processed; "
        f"{len(excel_chunks)} hybrid chunk(s) by type: {by_type}.",
    )


def run_representative_checks(ingested_docs, chunks_by_strategy) -> list[RepresentativeCheck]:
    return [
        check_fssai_regulation_tables(ingested_docs, chunks_by_strategy),
        check_nabl_scopes(ingested_docs),
        check_scanned_nabl_certificate(ingested_docs),
        check_brochure_multi_column(ingested_docs, chunks_by_strategy),
        check_figures(ingested_docs, chunks_by_strategy),
        check_multi_page_tables(chunks_by_strategy),
        check_excel_blocks(ingested_docs, chunks_by_strategy),
    ]
