from openpyxl import Workbook

from ticbot_chunking.experiments.common import ParsedDoc
from ticbot_chunking.experiments.hybrid import chunk_hybrid
from ticbot_chunking.parsers.ir import (
    BoundingBox,
    LayoutDocument,
    Page,
    Paragraph,
    ROLE_SECTION_HEADING,
    ROLE_TITLE,
    Table,
    TableCell,
)


def _bbox(page: int) -> BoundingBox:
    return BoundingBox(page_number=page)


def test_hybrid_reuses_chunk_regulation_and_tags_strategy():
    paragraphs = [
        Paragraph("FSS Regulations, 2011", role=ROLE_TITLE, bounding_boxes=[_bbox(1)]),
        Paragraph("CHAPTER 2 – Contaminants", role=ROLE_SECTION_HEADING, bounding_boxes=[_bbox(5)]),
        Paragraph("2.3 Residues", role=ROLE_SECTION_HEADING, bounding_boxes=[_bbox(5)]),
        Paragraph("Some narrative text describing the residue limits in detail for this section.",
                  bounding_boxes=[_bbox(5)]),
    ]
    doc = LayoutDocument(source_file="Contaminants_Regulations.pdf", pages=[Page(5)], paragraphs=paragraphs,
                          tables=[])
    parsed = ParsedDoc(source_file="Contaminants_Regulations.pdf", local_path="Contaminants_Regulations.pdf",
                        doc_type="regulation", kind="pdf", layout_doc=doc)

    chunks = chunk_hybrid(parsed)

    assert chunks
    assert all(c.metadata.strategy == "hybrid" for c in chunks)
    # this is exactly chunk_regulation's own output shape (section_path present) —
    # confirming hybrid.py calls the real function rather than reimplementing it
    assert chunks[0].metadata.section_path is not None
    assert chunks[0].metadata.authority == "FSSAI"


def test_hybrid_reuses_chunk_workbook_and_tags_strategy(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Key Contacts"
    ws.append(["S. No.", "Name", "Email"])
    ws.append([1, "Contact 001", "contact001@example.com"])
    ws.append([2, "Contact 002", "contact002@example.com"])
    path = tmp_path / "HN_Food_Testing_India_Key_Contacts.xlsx"
    wb.save(path)

    parsed = ParsedDoc(source_file="HN_Food_Testing_India_Key_Contacts.xlsx", local_path=str(path),
                        doc_type="contact_directory", kind="excel")

    chunks = chunk_hybrid(parsed)

    assert chunks
    assert all(c.metadata.strategy == "hybrid" for c in chunks)
    assert all(c.metadata.chunk_type in ("sheet_table", "sheet_lists", "sheet_kv", "sheet_chart") for c in chunks)
    # confirms the pipeline's own contact_directory -> internal/PII default rule ran
    assert all(c.metadata.access_class == "internal" for c in chunks)
    assert all(c.metadata.contains_pii for c in chunks)
