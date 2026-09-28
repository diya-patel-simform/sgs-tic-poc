from openpyxl import Workbook

from ticbot_chunking.experiments.common import ParsedDoc, build_doc_metadata
from ticbot_chunking.experiments.fixed_size import chunk_fixed_size
from ticbot_chunking.parsers.ir import BoundingBox, LayoutDocument, Page, Paragraph, ROLE_SECTION_HEADING, ROLE_TITLE
from ticbot_chunking.tokenizer import count_tokens


def _bbox(page: int) -> BoundingBox:
    return BoundingBox(page_number=page)


def _pdf_doc() -> LayoutDocument:
    paragraphs = [
        Paragraph("Some Catalog", role=ROLE_TITLE, bounding_boxes=[_bbox(1)]),
        Paragraph("Section One", role=ROLE_SECTION_HEADING, bounding_boxes=[_bbox(1)]),
        Paragraph("This is the first sentence of a paragraph on page one. " * 20, bounding_boxes=[_bbox(1)]),
        Paragraph("This is a second paragraph, still on page one, quite long as well. " * 20,
                  bounding_boxes=[_bbox(1)]),
        Paragraph("This paragraph is entirely on page two instead. " * 20, bounding_boxes=[_bbox(2)]),
    ]
    return LayoutDocument(source_file="catalog.pdf", pages=[Page(1), Page(2)], paragraphs=paragraphs, tables=[])


def _parsed_pdf() -> ParsedDoc:
    return ParsedDoc(source_file="catalog.pdf", local_path="catalog.pdf", doc_type="brochure", kind="pdf",
                      layout_doc=_pdf_doc())


def test_fixed_size_windows_respect_chunk_size_and_overlap_on_pdf():
    parsed = _parsed_pdf()
    doc_meta = build_doc_metadata(parsed)
    chunks = chunk_fixed_size(parsed, doc_meta, chunk_size=80, overlap=20, max_chunk_size=80)

    assert len(chunks) > 1
    for c in chunks[:-1]:  # every window except possibly the last should be near the requested size
        assert c.metadata.tokens <= 80 + count_tokens("[Fixed-size] Some Catalog\n")
    assert all(c.metadata.strategy == "fixed" for c in chunks)
    assert all(c.metadata.chunk_type == "text" for c in chunks)


def test_fixed_size_cuts_regardless_of_paragraph_boundaries():
    # With a small enough window, a fixed-size chunk must land in the middle
    # of the long first paragraph rather than stopping at its boundary —
    # this is the defining (and, compared to recursive/structure-aware,
    # weaker) characteristic of the strategy.
    parsed = _parsed_pdf()
    doc_meta = build_doc_metadata(parsed)
    chunks = chunk_fixed_size(parsed, doc_meta, chunk_size=30, overlap=5, max_chunk_size=30)

    first_para_text = _pdf_doc().paragraphs[2].text
    assert not any(c.text.strip().endswith(first_para_text.strip()) for c in chunks[:2])


def test_fixed_size_tracks_pages_across_a_window_that_spans_two_paragraphs():
    parsed = _parsed_pdf()
    doc_meta = build_doc_metadata(parsed)
    # A large window covering most/all of the document, spanning both pages.
    chunks = chunk_fixed_size(parsed, doc_meta, chunk_size=2000, overlap=0, max_chunk_size=2000)

    assert len(chunks) == 1
    assert chunks[0].metadata.pages == [1, 2]


def test_fixed_size_on_excel_stays_within_one_sheet_and_reports_cell_range(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for i in range(1, 6):
        ws.append([f"Row{i}A", f"Row{i}B"])
    ws2 = wb.create_sheet("Sheet2")
    ws2.append(["OtherSheetRow"])
    path = tmp_path / "book.xlsx"
    wb.save(path)

    parsed = ParsedDoc(source_file="book.xlsx", local_path=str(path), doc_type="reference_register", kind="excel")
    doc_meta = build_doc_metadata(parsed)
    chunks = chunk_fixed_size(parsed, doc_meta, chunk_size=400, overlap=20, max_chunk_size=400)

    sheets = {c.metadata.sheet for c in chunks}
    assert sheets == {"Sheet1", "Sheet2"}
    for c in chunks:
        assert c.metadata.cell_range is not None
        assert c.metadata.cell_range.startswith("A")
