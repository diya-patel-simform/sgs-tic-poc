"""Per-document ingestion: fetches one source file, classifies and parses
it (Excel via the existing local parser; PDF via page-level routing —
see `parsers/page_router.py`), and records the provenance/parser facts the
processing report needs.

PDFs are classified page by page (TEXT/SCANNED/AMBIGUOUS) and TEXT pages
are parsed locally while SCANNED/AMBIGUOUS pages go through Document
Intelligence's page-selection API — never the whole document just because
one page is scanned. A document that turns out to need both parsers is
tagged `PARSER_MIXED` below; the underlying `LayoutDocument` already
records which parser produced each individual page (`Page.is_scanned`).

Does not run the chunking strategies itself — see
`scripts/run_ingestion.py`, which reuses
`scripts.run_chunking_experiments.run_strategy` unchanged (the four
chunking strategies are not modified for this step) and then tags each
resulting chunk's `parser` metadata from the `IngestedDocument` it came
from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import load_workbook

from ticbot_chunking.experiments.common import ParsedDoc
from ticbot_chunking.metadata.classifier import guess_doc_type_from_filename
from ticbot_chunking.parsers.page_router import parse_pdf_paged, plan_page_routing

PARSER_LOCAL_PDF = "local_pdf"
PARSER_DOCUMENT_INTELLIGENCE = "document_intelligence"
PARSER_MIXED = "mixed_local_and_document_intelligence"  # some pages local, some via Document Intelligence
PARSER_EXCEL = "excel_parser"


@dataclass
class IngestedDocument:
    source_name: str  # "<container>/<blob path>" — becomes the chunk source_file
    filename: str
    doc_type: str
    kind: str  # "pdf" | "excel"
    parser: str  # PARSER_LOCAL_PDF | PARSER_DOCUMENT_INTELLIGENCE | PARSER_MIXED | PARSER_EXCEL
    local_path: str
    total_pages: int = 0
    text_layer_fraction: float | None = None  # fraction of this PDF's pages classified TEXT
    text_classification: str | None = None  # "text-based" | "no usable text layer" | "mixed (page-level routed)"
    sheets: list[str] = field(default_factory=list)
    figure_count: int = 0  # images the local parser detected, regardless of whether a chunker kept any
    parsed: ParsedDoc | None = None


@dataclass
class ProcessingFailure:
    source_name: str
    reason: str
    parser_attempted: str | None
    error: str
    retry_recommended: bool


def _classify_retry(error: Exception) -> bool:
    """A config/connectivity problem is worth retrying once fixed; a parse
    failure on the file's actual content generally isn't, without
    intervention on the file itself."""
    msg = str(error).lower()
    transient_markers = ("not configured", "timeout", "connection", "temporarily", "throttl", "rate limit")
    return any(m in msg for m in transient_markers)


def ingest_document(source_name: str, local_path: Path) -> IngestedDocument:
    filename = Path(source_name).name
    suffix = local_path.suffix.lower()

    if suffix in (".xlsx", ".xlsm"):
        doc_type = guess_doc_type_from_filename(filename) or "reference_register"
        wb = load_workbook(str(local_path), read_only=True, data_only=True)
        sheets = list(wb.sheetnames)
        wb.close()
        parsed = ParsedDoc(source_file=source_name, local_path=str(local_path), doc_type=doc_type, kind="excel")
        return IngestedDocument(
            source_name=source_name, filename=filename, doc_type=doc_type, kind="excel",
            parser=PARSER_EXCEL, local_path=str(local_path), sheets=sheets, parsed=parsed,
        )

    # PDF: classify every page first (cheap, local, no Azure call), then
    # parse with page-level routing — TEXT pages locally, SCANNED/AMBIGUOUS
    # pages via Document Intelligence's page-selection API — so the report's
    # "parser used" always matches what actually ran, and a document needing
    # both parsers is recorded as such (see `parsers/page_router.py`).
    plan = plan_page_routing(str(local_path))
    layout_doc = parse_pdf_paged(str(local_path), plan=plan)

    if not plan.ocr_pages:
        parser = PARSER_LOCAL_PDF
        classification = "text-based"
    elif not plan.text_pages:
        parser = PARSER_DOCUMENT_INTELLIGENCE
        classification = "no usable text layer"
    else:
        parser = PARSER_MIXED
        classification = "mixed (page-level routed)"

    text_layer_fraction = (len(plan.text_pages) / plan.total_pages) if plan.total_pages else 0.0

    doc_type = guess_doc_type_from_filename(filename) or "brochure"
    parsed = ParsedDoc(source_file=source_name, local_path=str(local_path), doc_type=doc_type, kind="pdf",
                        layout_doc=layout_doc)
    return IngestedDocument(
        source_name=source_name, filename=filename, doc_type=doc_type, kind="pdf", parser=parser,
        local_path=str(local_path), total_pages=layout_doc.page_count, text_layer_fraction=text_layer_fraction,
        text_classification=classification, figure_count=len(layout_doc.figures), parsed=parsed,
    )
