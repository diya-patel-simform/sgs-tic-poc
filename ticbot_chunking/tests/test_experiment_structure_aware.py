from openpyxl import Workbook

from ticbot_chunking.experiments.common import ParsedDoc, build_doc_metadata
from ticbot_chunking.experiments.structure_aware import chunk_structure_aware
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


def test_structure_aware_narrative_chunks_carry_a_section_path():
    # This is the key differentiator from fixed/recursive: structure-aware
    # knows which heading a paragraph falls under.
    paragraphs = [
        Paragraph("Some Catalog", role=ROLE_TITLE, bounding_boxes=[_bbox(1)]),
        Paragraph("Species Identification", role=ROLE_SECTION_HEADING, bounding_boxes=[_bbox(1)]),
        Paragraph("Our DNA barcoding service identifies species present in a sample.",
                  bounding_boxes=[_bbox(1)]),
    ]
    doc = LayoutDocument(source_file="catalog.pdf", pages=[Page(1)], paragraphs=paragraphs, tables=[])
    parsed = ParsedDoc(source_file="catalog.pdf", local_path="catalog.pdf", doc_type="brochure", kind="pdf",
                        layout_doc=doc)
    doc_meta = build_doc_metadata(parsed)

    chunks = chunk_structure_aware(parsed, doc_meta, chunk_size=400, overlap=60, max_chunk_size=700)

    text_chunks = [c for c in chunks if c.metadata.chunk_type == "text"]
    assert len(text_chunks) == 1
    assert text_chunks[0].metadata.section_path == "Some Catalog › Species Identification"
    assert text_chunks[0].metadata.strategy == "structure_aware"
    assert "Species Identification" in text_chunks[0].text
    assert text_chunks[0].text.startswith("[Structure-aware]")


def test_structure_aware_table_uses_generic_formatting_not_domain_grouping():
    paragraphs = [
        Paragraph("Regs", role=ROLE_TITLE, bounding_boxes=[_bbox(1)]),
        Paragraph("Table intro sentence.", bounding_boxes=[_bbox(1)]),
    ]
    cells = [
        TableCell(0, 0, "Name", kind="columnHeader"),
        TableCell(0, 1, "Value", kind="columnHeader"),
        TableCell(1, 0, "Carbaryl"), TableCell(1, 1, "0.2"),
        TableCell(2, 0, "Carbaryl"), TableCell(2, 1, "1.5"),
        TableCell(3, 0, "Chlordane"), TableCell(3, 1, "0.3"),
    ]
    table = Table(row_count=4, column_count=2, cells=cells, page_numbers=[1], preceding_paragraph_index=1)
    doc = LayoutDocument(source_file="regs.pdf", pages=[Page(1)], paragraphs=paragraphs, tables=[table])
    parsed = ParsedDoc(source_file="regs.pdf", local_path="regs.pdf", doc_type="regulation", kind="pdf",
                        layout_doc=doc)
    doc_meta = build_doc_metadata(parsed)

    chunks = chunk_structure_aware(parsed, doc_meta, chunk_size=400, overlap=0, max_chunk_size=700)
    table_chunks = [c for c in chunks if c.metadata.chunk_type == "table"]

    assert len(table_chunks) == 1
    # no group boundaries, no carried-forward entity list, no method-code
    # extraction — those are hybrid-only specializations
    assert table_chunks[0].metadata.entities is None
    assert table_chunks[0].metadata.row_count == 3
    assert "| Carbaryl | 0.2 |" in table_chunks[0].text
    assert "| Name | Value |" in table_chunks[0].text


def test_structure_aware_on_excel_uses_generic_block_detection(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Category", "Count"])
    ws.append(["A", 1])
    ws.append(["B", 2])
    path = tmp_path / "book.xlsx"
    wb.save(path)

    parsed = ParsedDoc(source_file="book.xlsx", local_path=str(path), doc_type="reference_register", kind="excel")
    doc_meta = build_doc_metadata(parsed)

    chunks = chunk_structure_aware(parsed, doc_meta, chunk_size=400, overlap=0, max_chunk_size=700)

    assert len(chunks) == 1
    assert chunks[0].metadata.chunk_type == "table"
    assert chunks[0].metadata.sheet == "Sheet1"
    assert chunks[0].metadata.strategy == "structure_aware"
    assert "Category: A" in chunks[0].text
    assert "Count: 1" in chunks[0].text


def test_structure_aware_does_not_apply_excel_block_type_classification(tmp_path):
    # A block that the hybrid excel_blocks.classify_block would call
    # "sheet_kv" or "column_lists" should still just be a generic "table"
    # chunk_type here — structure-aware has no notion of block-type
    # classification, only block *detection*.
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Label:", "Other:"])
    ws.append(["x1", "y1"])
    path = tmp_path / "book.xlsx"
    wb.save(path)

    parsed = ParsedDoc(source_file="book.xlsx", local_path=str(path), doc_type="reference_register", kind="excel")
    doc_meta = build_doc_metadata(parsed)

    chunks = chunk_structure_aware(parsed, doc_meta, chunk_size=400, overlap=0, max_chunk_size=700)

    assert all(c.metadata.chunk_type == "table" for c in chunks)
