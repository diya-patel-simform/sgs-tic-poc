from ticbot_chunking.chunkers.regulation import chunk_regulation
from ticbot_chunking.metadata.schema import DocumentMetadata
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


def _build_doc() -> LayoutDocument:
    paragraphs = [
        Paragraph("FSS (Contaminants, Toxins and Residues) Regulations, 2011", role=ROLE_TITLE,
                  bounding_boxes=[_bbox(1)]),
        Paragraph("CHAPTER 2 – Contaminants, Toxins And Residues", role=ROLE_SECTION_HEADING,
                  bounding_boxes=[_bbox(5)]),
        Paragraph("2.3 Residues", role=ROLE_SECTION_HEADING, bounding_boxes=[_bbox(5)]),
        Paragraph("2.3.1 Restriction on the use of insecticides", role=ROLE_SECTION_HEADING,
                  bounding_boxes=[_bbox(5)]),
        Paragraph(
            "The amount of insecticide mentioned in Column 2 on the foods mentioned in column 3, "
            "shall not exceed the tolerance limit prescribed in column 4 of the Table given below :",
            bounding_boxes=[_bbox(5)],
        ),
    ]

    cells = [
        TableCell(0, 0, "Sl.No.", kind="columnHeader", page_number=5),
        TableCell(0, 1, "Name of Insecticides", kind="columnHeader", page_number=5),
        TableCell(0, 2, "Food", kind="columnHeader", page_number=5),
        TableCell(0, 3, "Tolerance limit mg/kg (ppm)", kind="columnHeader", page_number=5),
        TableCell(1, 0, "2", row_span=3, page_number=5),
        TableCell(1, 1, "Carbaryl", row_span=3, page_number=5),
        TableCell(1, 2, "Fish", page_number=5),
        TableCell(1, 3, "0.2", page_number=5),
        TableCell(2, 2, "Foodgrains", page_number=5),
        TableCell(2, 3, "1.5", page_number=5),
        TableCell(3, 2, "Okra and leafy vegetables", page_number=6),
        TableCell(3, 3, "10.0", page_number=6),
        TableCell(4, 0, "3", page_number=6),
        TableCell(4, 1, "Chlordane (residue to be measured as cis plus trans chlordane)", page_number=6),
        TableCell(4, 2, "Sugar beet", page_number=6),
        TableCell(4, 3, "0.3", page_number=6),
    ]
    table = Table(row_count=5, column_count=4, cells=cells, page_numbers=[5, 6], preceding_paragraph_index=4)

    pages = [Page(page_number=n) for n in range(1, 7)]
    return LayoutDocument(
        source_file="Contaminants_Regulations_pages_1-5.pdf",
        pages=pages,
        paragraphs=paragraphs,
        tables=[table],
    )


def _doc_meta() -> DocumentMetadata:
    return DocumentMetadata(
        doc_type="regulation",
        source_file="Contaminants_Regulations_pages_1-5.pdf",
        authority="FSSAI",
        effective="2011-08-05",
    )


def test_table_chunk_carries_section_breadcrumb_and_row_labels():
    chunks = chunk_regulation(_build_doc(), _doc_meta())
    table_chunks = [c for c in chunks if c.metadata.chunk_type == "table"]

    assert len(table_chunks) >= 1
    table_chunk = table_chunks[0]
    assert table_chunk.metadata.section_number == "2.3.1"
    assert "2.3.1: Restriction on the use of insecticides" in table_chunk.metadata.section_path
    assert table_chunk.metadata.pages == [5, 6]
    assert table_chunk.metadata.row_count == 4
    assert "Carbaryl" in table_chunk.text
    # the page-6 row must show the carried-forward name, not a blank cell
    assert "Okra and leafy vegetables" in table_chunk.text
    okra_line = next(line for line in table_chunk.text.splitlines() if "Okra" in line)
    assert "Carbaryl" in okra_line


def test_table_chunk_repeats_header_and_intro_sentence():
    chunks = chunk_regulation(_build_doc(), _doc_meta())
    table_chunk = next(c for c in chunks if c.metadata.chunk_type == "table")

    assert "Table context:" in table_chunk.text
    assert "Sl.No." in table_chunk.text
    assert table_chunk.text.startswith("[Regulation]")


def test_no_rows_lost_or_duplicated_across_chunks():
    chunks = chunk_regulation(_build_doc(), _doc_meta())
    table_chunks = [c for c in chunks if c.metadata.chunk_type == "table"]
    assert sum(c.metadata.row_count for c in table_chunks) == 4


def test_table_chunk_carries_structured_rows_resolved_by_content_not_a_hardcoded_index():
    chunks = chunk_regulation(_build_doc(), _doc_meta())
    table_chunk = next(c for c in chunks if c.metadata.chunk_type == "table")

    assert table_chunk.metadata.structured_rows is not None
    carbaryl_rows = [r for r in table_chunk.metadata.structured_rows if r["contaminant"] == "Carbaryl"]
    # 3, not 2: the rowspan carries "Carbaryl" onto the page-6 "Okra" row too
    # (same carry-forward the existing row-label test above already covers).
    assert len(carbaryl_rows) == 3
    assert {r["food"] for r in carbaryl_rows} == {"Fish", "Foodgrains", "Okra and leafy vegetables"}
    assert {r["limit"] for r in carbaryl_rows} == {"0.2", "1.5", "10.0"}
    pages = {r["page"] for r in carbaryl_rows}
    assert pages == {5, 6}


def test_doc_title_and_page_start_end_are_populated():
    chunks = chunk_regulation(_build_doc(), _doc_meta())
    assert all(c.metadata.doc_title == "FSS (Contaminants, Toxins and Residues) Regulations, 2011" for c in chunks)
    table_chunk = next(c for c in chunks if c.metadata.chunk_type == "table")
    assert table_chunk.metadata.page_start == 5
    assert table_chunk.metadata.page_end == 6


def test_embed_text_uses_a_short_prefix_not_the_long_citation_breadcrumb():
    chunks = chunk_regulation(_build_doc(), _doc_meta())
    text_chunk = next(c for c in chunks if c.metadata.chunk_type == "text")
    assert text_chunk.embed_text is not None
    assert "[Regulation]" not in text_chunk.embed_text  # the long breadcrumb marker stays only in `text`
    assert "[Regulation]" in text_chunk.text
    assert "Page" in text_chunk.embed_text


def test_per_part_pages_reflect_only_that_parts_own_paragraphs():
    # A section spanning several pages, long enough to force a narrative
    # split, must give each PART its own real pages — not the whole
    # section's page range on every part (the confirmed root cause of
    # "wrong page citations").
    paragraphs = [
        Paragraph("FSS Regulations, 2011", role=ROLE_TITLE, bounding_boxes=[_bbox(1)]),
        Paragraph("CHAPTER 2 – Contaminants", role=ROLE_SECTION_HEADING, bounding_boxes=[_bbox(1)]),
        Paragraph("2.4 Long section", role=ROLE_SECTION_HEADING, bounding_boxes=[_bbox(1)]),
        Paragraph(" ".join(f"page-one-word{i}" for i in range(400)), bounding_boxes=[_bbox(1)]),
        Paragraph(" ".join(f"page-two-word{i}" for i in range(400)), bounding_boxes=[_bbox(2)]),
        Paragraph(" ".join(f"page-three-word{i}" for i in range(400)), bounding_boxes=[_bbox(3)]),
    ]
    doc = LayoutDocument(
        source_file="synthetic.pdf",
        pages=[Page(page_number=n) for n in (1, 2, 3)],
        paragraphs=paragraphs,
        tables=[],
    )
    chunks = chunk_regulation(doc, _doc_meta())
    text_chunks = [c for c in chunks if c.metadata.chunk_type == "text"]

    assert len(text_chunks) > 1
    all_pages_claimed = [tuple(c.metadata.pages) for c in text_chunks]
    assert len(set(all_pages_claimed)) > 1, "every part claiming the identical page range is the bug being fixed"

    # The very first emitted part must be page 1's own opening content, not
    # the whole section's page range — and later parts must not claim page
    # 1 once the content has genuinely moved past it.
    assert text_chunks[0].metadata.pages == [1]
    assert "page-one-word0" in text_chunks[0].text
    assert "page-three-word0" not in text_chunks[0].text

    last_chunk = text_chunks[-1]
    assert 3 in last_chunk.metadata.pages
    assert "page-three-word" in last_chunk.text
    assert "page-one-word0" not in last_chunk.text
