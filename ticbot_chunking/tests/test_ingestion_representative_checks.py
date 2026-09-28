from ticbot_chunking.experiments.common import ParsedDoc
from ticbot_chunking.ingestion.orchestrator import IngestedDocument
from ticbot_chunking.ingestion.representative_checks import (
    check_excel_blocks,
    check_figures,
    check_fssai_regulation_tables,
    check_multi_page_tables,
    check_nabl_scopes,
    check_scanned_nabl_certificate,
    run_representative_checks,
)
from ticbot_chunking.parsers.ir import BoundingBox, Figure, LayoutDocument, Page, Paragraph, ROLE_TITLE


def _row(chunk_type, source_file, tokens=100, pages=None, row_count=None):
    meta = {"chunk_type": chunk_type, "source_file": source_file, "tokens": tokens}
    if pages is not None:
        meta["pages"] = pages
    if row_count is not None:
        meta["row_count"] = row_count
    return {"text": "x", "metadata": meta}


def test_fssai_check_is_not_available_when_no_regulation_doc():
    result = check_fssai_regulation_tables([], {"hybrid": []})
    assert result.status == "not_available"


def test_fssai_check_reports_zero_table_chunks_honestly():
    layout_doc = LayoutDocument(source_file="a.pdf", pages=[Page(1)], paragraphs=[], tables=[])
    parsed = ParsedDoc(source_file="a.pdf", local_path="a.pdf", doc_type="regulation", kind="pdf",
                        layout_doc=layout_doc)
    doc = IngestedDocument(source_name="a.pdf", filename="a.pdf", doc_type="regulation", kind="pdf",
                            parser="local_pdf", local_path="a.pdf", parsed=parsed)

    result = check_fssai_regulation_tables([doc], {"hybrid": [_row("text", "a.pdf")]})

    assert result.status == "available"
    assert "ZERO table-type chunks" in result.finding


def test_fssai_check_reports_table_chunks_when_present():
    layout_doc = LayoutDocument(source_file="a.pdf", pages=[Page(1)], paragraphs=[], tables=[])
    parsed = ParsedDoc(source_file="a.pdf", local_path="a.pdf", doc_type="regulation", kind="pdf",
                        layout_doc=layout_doc)
    doc = IngestedDocument(source_name="a.pdf", filename="a.pdf", doc_type="regulation", kind="pdf",
                            parser="local_pdf", local_path="a.pdf", parsed=parsed)

    result = check_fssai_regulation_tables([doc], {"hybrid": [_row("table", "a.pdf", row_count=5)]})

    assert result.status == "available"
    assert "1 table chunk(s)" in result.finding


def test_nabl_scopes_not_available_when_absent():
    result = check_nabl_scopes([])
    assert result.status == "not_available"


def test_nabl_scopes_available_when_present():
    doc = IngestedDocument(source_name="scope.pdf", filename="scope.pdf", doc_type="accreditation_scope",
                            kind="pdf", parser="document_intelligence", local_path="scope.pdf")
    result = check_nabl_scopes([doc])
    assert result.status == "available"


def test_scanned_nabl_certificate_not_available_without_di_routed_scope_doc():
    doc = IngestedDocument(source_name="scope.pdf", filename="scope.pdf", doc_type="accreditation_scope",
                            kind="pdf", parser="local_pdf", local_path="scope.pdf")  # not DI-routed
    result = check_scanned_nabl_certificate([doc])
    assert result.status == "not_available"


def test_scanned_nabl_certificate_available_when_di_routed():
    doc = IngestedDocument(source_name="scope.pdf", filename="scope.pdf", doc_type="accreditation_scope",
                            kind="pdf", parser="document_intelligence", local_path="scope.pdf")
    result = check_scanned_nabl_certificate([doc])
    assert result.status == "available"


def test_figures_reports_decorative_drop_when_local_parser_found_images_but_no_figure_chunks():
    layout_doc = LayoutDocument(
        source_file="b.pdf", pages=[Page(1)], paragraphs=[],
        tables=[], figures=[Figure(caption=None, page_number=1, bounding_box=BoundingBox(1))],
    )
    parsed = ParsedDoc(source_file="b.pdf", local_path="b.pdf", doc_type="brochure", kind="pdf",
                        layout_doc=layout_doc)
    doc = IngestedDocument(source_name="b.pdf", filename="b.pdf", doc_type="brochure", kind="pdf",
                            parser="local_pdf", local_path="b.pdf", figure_count=1, parsed=parsed)

    result = check_figures([doc], {"hybrid": [_row("text", "b.pdf")]})

    assert result.status == "available"
    assert "0 figure-type chunk(s)" in result.finding
    assert "doesn't detect a figure's caption" in result.finding


def test_multi_page_tables_reports_absence_honestly():
    result = check_multi_page_tables({"hybrid": [_row("table", "a.pdf", pages=[5])]})
    assert "No table-type chunk spans more than one page" in result.finding


def test_multi_page_tables_finds_real_multi_page_chunk():
    result = check_multi_page_tables({"hybrid": [_row("table", "a.pdf", pages=[5, 6])]})
    assert "1 multi-page table chunk(s)" in result.finding


def test_excel_blocks_not_available_without_excel_docs():
    result = check_excel_blocks([], {"hybrid": []})
    assert result.status == "not_available"


def test_excel_blocks_available_and_summarizes_by_type():
    doc = IngestedDocument(source_name="book.xlsx", filename="book.xlsx", doc_type="capability_matrix",
                            kind="excel", parser="excel_parser", local_path="book.xlsx", sheets=["Sheet1"])
    rows = [_row("sheet_table", "book.xlsx"), _row("sheet_table", "book.xlsx"), _row("sheet_kv", "book.xlsx")]
    result = check_excel_blocks([doc], {"hybrid": rows})
    assert result.status == "available"
    assert "sheet_table" in result.finding


def test_run_representative_checks_returns_all_seven_topics(tmp_path):
    results = run_representative_checks([], {"hybrid": []})
    topics = {r.topic for r in results}
    assert topics == {
        "FSSAI regulation tables", "NABL scopes", "Scanned NABL certificate",
        "Brochure multi-column content", "Figures", "Multi-page tables", "Excel blocks",
    }
