"""End-to-end orchestration: routes each input file to the right parser and
chunker based on its detected document type, and writes out chunks.jsonl.

PDFs go through `parsers.page_router.parse_pdf_paged`, which classifies each
page individually and parses TEXT pages locally (no Azure call) while
sending only the SCANNED/AMBIGUOUS pages to Document Intelligence's
page-selection API — never the whole document just because one page is
scanned (see `parsers/page_router.py`). A PDF with no scanned/ambiguous
pages at all never touches Azure, exactly as before. Excel workbooks are
handled entirely locally via openpyxl. Document Intelligence credentials
are therefore only needed when at least one input PDF page turns out to
need OCR.
"""
from __future__ import annotations

import json
from pathlib import Path

from ticbot_chunking.chunkers.brochure import chunk_brochure
from ticbot_chunking.chunkers.excel_blocks import chunk_workbook
from ticbot_chunking.chunkers.nabl_scope import chunk_nabl_scope
from ticbot_chunking.chunkers.regulation import chunk_regulation
from ticbot_chunking.metadata.classifier import (
    extract_accreditation_standard,
    extract_certificate_no,
    extract_lab_location,
    extract_last_amended,
    extract_validity,
    guess_doc_type_from_filename,
)
from ticbot_chunking.metadata.schema import Chunk, DocumentMetadata
from ticbot_chunking.parsers.ir import ROLE_TITLE
from ticbot_chunking.parsers.page_router import parse_pdf_paged


def _first_page_text(doc) -> str:
    return "\n".join(p.text for p in doc.paragraphs if 1 in p.page_numbers)


def _document_title(doc) -> str:
    return next((p.text.strip() for p in doc.paragraphs if p.role == ROLE_TITLE), Path(doc.source_file).stem)


def _build_doc_metadata(doc, source_file: str, doc_type: str) -> DocumentMetadata:
    first_page = _first_page_text(doc)
    meta = DocumentMetadata(doc_type=doc_type, source_file=source_file)
    if doc_type == "accreditation_scope":
        meta.certificate_no = extract_certificate_no(first_page)
        meta.validity = extract_validity(first_page)
        meta.last_amended = extract_last_amended(first_page)
        meta.accreditation_standard = extract_accreditation_standard(first_page)
        meta.lab_location = extract_lab_location(first_page)
        meta.authority = "NABL"
    elif doc_type == "regulation":
        meta.authority = "FSSAI"
    return meta


def process_pdf(file_path: str) -> list[Chunk]:
    doc_type = guess_doc_type_from_filename(Path(file_path).name) or "brochure"
    doc = parse_pdf_paged(file_path)
    doc_meta = _build_doc_metadata(doc, Path(file_path).name, doc_type)
    document_title = _document_title(doc)

    if doc_type == "regulation":
        return chunk_regulation(doc, doc_meta)
    if doc_type == "accreditation_scope":
        return chunk_nabl_scope(doc, doc_meta, document_title)
    return chunk_brochure(doc, doc_meta)


def process_excel(file_path: str) -> list[Chunk]:
    doc_type = guess_doc_type_from_filename(Path(file_path).name) or "reference_register"
    doc_meta = DocumentMetadata(doc_type=doc_type, source_file=Path(file_path).name)
    # Section 7 access-control rule: the contacts workbook carries personal
    # data (names, direct emails) and is not public by default.
    if doc_type == "contact_directory":
        doc_meta.access_class = "internal"
        doc_meta.contains_pii = True
    workbook_title = Path(file_path).stem.replace("_", " ")
    return chunk_workbook(file_path, doc_meta, workbook_title)


def run_pipeline(input_dir: str, output_path: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(Path(input_dir).iterdir()):
        if path.suffix.lower() == ".pdf":
            chunks.extend(process_pdf(str(path)))
        elif path.suffix.lower() in (".xlsx", ".xlsm"):
            chunks.extend(process_excel(str(path)))

    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")

    return chunks
