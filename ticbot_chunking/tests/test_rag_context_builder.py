from ticbot_chunking.rag.context_builder import build_context
from ticbot_chunking.search.retrieval_client import RetrievalResult


def _result(**overrides):
    defaults = dict(
        rank=1, score=1.0, reranker_score=None, chunk_id="c1", text="chunk body text",
        chunking_strategy="hybrid", source_file="a.pdf", blob_path="a.pdf", parser_used="local_pdf",
        pages=None, section_path=None, section_number=None, chunk_type="text", document_type="regulation",
        sheet=None, cell_range=None, authority=None, lab_location=None, certificate_no=None,
        discipline=None, material=None, facility=None,
    )
    defaults.update(overrides)
    return RetrievalResult(**defaults)


def test_context_numbers_sources_starting_at_one():
    results = [_result(chunk_id="c1"), _result(chunk_id="c2"), _result(chunk_id="c3")]
    context = build_context(results)
    assert "Source [1]" in context
    assert "Source [2]" in context
    assert "Source [3]" in context
    assert context.index("Source [1]") < context.index("Source [2]") < context.index("Source [3]")


def test_context_includes_pdf_page_and_section():
    result = _result(source_file="reg.pdf", pages=[3, 4], section_path="Chapter 2 > 2.1")
    context = build_context([result])
    assert "File: reg.pdf" in context
    assert "Page(s): 3, 4" in context
    assert "Section: Chapter 2 > 2.1" in context


def test_context_includes_excel_sheet_and_cell_range():
    result = _result(source_file="book.xlsx", sheet="Sheet1", cell_range="A1:D10", pages=None)
    context = build_context([result])
    assert "Sheet: Sheet1" in context
    assert "Cell range: A1:D10" in context
    assert "Page(s):" not in context  # no pages on an Excel chunk


def test_context_includes_nabl_metadata_when_present():
    result = _result(certificate_no="TC-5378", lab_location="SGS INDIA PVT. LTD.", discipline="Chemical",
                      material="Water")
    context = build_context([result])
    assert "Certificate number: TC-5378" in context
    assert "Laboratory: SGS INDIA PVT. LTD." in context
    assert "Discipline: Chemical" in context
    assert "Material: Water" in context


def test_context_omits_fields_that_are_none():
    result = _result()
    context = build_context([result])
    assert "Sheet:" not in context
    assert "Cell range:" not in context
    assert "Certificate number:" not in context
    assert "Laboratory:" not in context


def test_context_includes_the_chunk_text():
    result = _result(text="the actual retrieved content goes here")
    context = build_context([result])
    assert "the actual retrieved content goes here" in context


def test_context_empty_for_no_results():
    assert build_context([]) == ""
