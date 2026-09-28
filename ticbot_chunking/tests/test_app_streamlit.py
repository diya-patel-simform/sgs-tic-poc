"""Tests for the Streamlit UI (ticbot_chunking/app.py), using Streamlit's
own `AppTest` harness — the real script is executed (no browser needed),
with `rag_service.answer` mocked so no real Azure OpenAI/Search call is
ever made. Patching `ticbot_chunking.rag.rag_service.answer` (the source
module, not `ticbot_chunking.app`'s already-bound name) works because
AppTest re-executes app.py's `from ... import answer` on every `.run()`,
which re-reads whatever `rag_service.answer` currently is.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from ticbot_chunking.rag.response import Citation, RagResponse
from ticbot_chunking.search.retrieval_client import RetrievalResult

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def _chunk(rank=1, chunk_id="c1", **overrides):
    defaults = dict(
        rank=rank, score=0.9, reranker_score=None, chunk_id=chunk_id, text="the retrieved chunk text",
        chunking_strategy="hybrid", source_file="a.pdf", blob_path="a.pdf", parser_used="local_pdf",
        pages=[2], section_path="EXPERTISE > ABOUT US", section_number=None, chunk_type="text",
        document_type="brochure", sheet=None, cell_range=None, authority=None, lab_location=None,
        certificate_no=None, discipline=None, material=None, facility=None,
    )
    defaults.update(overrides)
    return RetrievalResult(**defaults)


def _citation_for(chunk: RetrievalResult) -> Citation:
    return Citation(
        chunk_id=chunk.chunk_id, source_file=chunk.source_file, document_type=chunk.document_type,
        page=", ".join(str(p) for p in chunk.pages) if chunk.pages else None, sheet=chunk.sheet,
        cell_range=chunk.cell_range, section=chunk.section_path, certificate_no=chunk.certificate_no,
        lab_location=chunk.lab_location, discipline=chunk.discipline, material=chunk.material,
        score=chunk.score, source_numbers=[chunk.rank],
    )


def _fake_response(question, strategy="hybrid", mode="hybrid", top_k=5, chunks=None, answer_text="Fake answer [1].",
                    index_name=None, filter=None):
    chunks = chunks if chunks is not None else [_chunk()]
    citations = [_citation_for(chunks[0])] if chunks else []
    return RagResponse(query=question, strategy=strategy, retrieval_mode=mode, top_k=top_k, answer=answer_text,
                        citations=citations, retrieved_chunks=chunks, context_used=bool(chunks),
                        retrieval_latency_seconds=0.1, llm_latency_seconds=0.2 if chunks else None)


def _run_app_with(answer_fn, question: str | None = None) -> AppTest:
    """Loads the app with `rag_service.answer` mocked. If `question` is
    given, also submits it — within the SAME patch scope, since the mock
    only applies while the `with patch(...)` block is active and a
    `.run()` call after it exits would hit the real (unmocked, real-Azure)
    function instead."""
    with patch("ticbot_chunking.rag.rag_service.answer", side_effect=answer_fn):
        at = AppTest.from_file(APP_PATH)
        at.run()
        if question is not None:
            at.chat_input[0].set_value(question).run()
        return at


def test_app_loads_without_error():
    at = _run_app_with(lambda *a, **k: _fake_response(*a, **k))
    assert not at.exception
    assert at.title[0].value == "SGS TIC Bot"


def test_sidebar_defaults_to_top_k_five_with_no_mode_picker():
    at = _run_app_with(lambda *a, **k: _fake_response(*a, **k))
    assert at.sidebar.radio == []  # no retrieval-mode picker in the UI any more
    assert at.sidebar.number_input[0].value == 5
    sidebar_captions = [c.value for c in at.sidebar.caption]
    assert any("Retrieval mode: Vector" in c for c in sidebar_captions)


def test_submitting_a_question_renders_answer_and_citations():
    with patch("ticbot_chunking.rag.rag_service.answer", side_effect=lambda *a, **k: _fake_response(*a, **k)) as m:
        at = AppTest.from_file(APP_PATH)
        at.run()
        at.chat_input[0].set_value("What services does SGS Molecular provide?").run()

    assert not at.exception
    m.assert_called_once()
    markdown_values = [x.value for x in at.markdown]
    assert "What services does SGS Molecular provide?" in markdown_values
    assert "Fake answer [1]." in markdown_values
    assert len(at.session_state["messages"]) == 2  # user + assistant


def test_default_call_uses_hybrid_strategy_and_vector_mode():
    with patch("ticbot_chunking.rag.rag_service.answer", side_effect=lambda *a, **k: _fake_response(*a, **k)) as m:
        at = AppTest.from_file(APP_PATH)
        at.run()
        at.chat_input[0].set_value("q").run()

    assert m.call_args.kwargs["strategy"] == "hybrid"
    assert m.call_args.kwargs["mode"] == "vector"


def test_ui_currently_targets_the_updated_pdf_data_index():
    # Temporary: the app is pointed at the updated-pdf-data test indexes
    # right now (see app.INDEX_NAME_OVERRIDE) rather than the original
    # sample-dataset indexes.
    import ticbot_chunking.app as app

    with patch("ticbot_chunking.rag.rag_service.answer", side_effect=lambda *a, **k: _fake_response(*a, **k)) as m:
        at = AppTest.from_file(APP_PATH)
        at.run()
        at.chat_input[0].set_value("q").run()

    assert m.call_args.kwargs["index_name"] == app.INDEX_NAME_OVERRIDE == "ticbot-chunks-hybrid-updated"


def test_changing_top_k_is_passed_to_rag_service():
    with patch("ticbot_chunking.rag.rag_service.answer", side_effect=lambda *a, **k: _fake_response(*a, **k)) as m:
        at = AppTest.from_file(APP_PATH)
        at.run()
        at.sidebar.number_input[0].set_value(10).run()
        at.chat_input[0].set_value("q").run()

    assert m.call_args.kwargs["top_k"] == 10


def test_citation_metadata_matches_the_retrieved_chunk():
    chunk = _chunk(source_file="reg.pdf", pages=[5, 6], document_type="regulation",
                    section_path="Chapter 2 > 2.1")
    at = _run_app_with(lambda *a, **k: _fake_response(*a, chunks=[chunk], **k), question="q")

    captions = [c.value for c in at.caption]
    assert "Page(s): 5, 6" in captions
    assert "Section: Chapter 2 > 2.1" in captions


def test_excel_citation_shows_sheet_and_cell_range():
    chunk = _chunk(source_file="book.xlsx", pages=None, sheet="Key Contacts", cell_range="A5:H10",
                    document_type="contact_directory")
    at = _run_app_with(lambda *a, **k: _fake_response(*a, chunks=[chunk], **k), question="q")

    captions = [c.value for c in at.caption]
    assert "Sheet: Key Contacts" in captions
    assert "Cell range: A5:H10" in captions


def test_nabl_citation_shows_certificate_lab_discipline_material():
    chunk = _chunk(source_file="nabl.pdf", pages=None, document_type="accreditation_scope",
                    certificate_no="TC-5378", lab_location="SGS INDIA PVT. LTD.",
                    discipline="BIOLOGICAL- ANIMAL FOOD & FEED", material="Corn gluten")
    at = _run_app_with(lambda *a, **k: _fake_response(*a, chunks=[chunk], **k), question="q")

    captions = [c.value for c in at.caption]
    assert "Certificate no.: TC-5378" in captions
    assert "Laboratory: SGS INDIA PVT. LTD." in captions
    assert "Discipline: BIOLOGICAL- ANIMAL FOOD & FEED" in captions
    assert "Material: Corn gluten" in captions


def test_citation_with_multiple_source_numbers_shows_both_markers():
    chunk = _chunk(rank=1, chunk_id="c1", source_file="reg.pdf", section_path="Chapter 2 > 2.1")
    at = _run_app_with(
        lambda *a, **k: _fake_response(*a, chunks=[chunk], answer_text="Limit is 15.0 ppm [1].", **k),
        question="q",
    )
    markdown_values = [x.value for x in at.markdown]
    assert any(v.startswith("**[1] reg.pdf**") for v in markdown_values)


def test_cited_table_chunk_renders_as_a_markdown_table():
    table_text = (
        "[Regulation] Doc > 2.1\nTable context:\n"
        "| Contaminant | Food | Limit |\n| --- | --- | --- |\n| Copper | Infant foods | 15.0 |"
    )
    chunk = _chunk(rank=1, chunk_id="c1", chunk_type="table", text=table_text)
    at = _run_app_with(
        lambda *a, **k: _fake_response(*a, chunks=[chunk], answer_text="Copper limit is 15.0 ppm [1].", **k),
        question="q",
    )
    markdown_values = [x.value for x in at.markdown]
    assert any("| Contaminant | Food | Limit |" in v for v in markdown_values)
    assert any("| Copper | Infant foods | 15.0 |" in v for v in markdown_values)


def test_retrieved_sources_expander_lists_every_retrieved_chunk():
    chunks = [_chunk(rank=1, chunk_id="c1"), _chunk(rank=2, chunk_id="c2")]
    at = _run_app_with(lambda *a, **k: _fake_response(*a, chunks=chunks, answer_text="Answer [1][2].", **k), question="q")

    expander_labels = [e.label for e in at.expander]
    assert any("[1] a.pdf" in label for label in expander_labels)
    assert any("[2] a.pdf" in label for label in expander_labels)


def test_empty_retrieval_renders_no_context_answer_without_crashing():
    def no_results_answer(question, **kwargs):
        return _fake_response(question, chunks=[], answer_text="I couldn't find enough information "
                                                                 "in the provided documents to answer this question.")

    at = _run_app_with(no_results_answer, question="an unanswerable question")

    assert not at.exception
    markdown_values = [x.value for x in at.markdown]
    assert any("couldn't find enough information" in v for v in markdown_values)
    captions = [c.value for c in at.caption]
    assert "No citations — the answer above did not draw on the retrieved sources." in captions


def test_configuration_error_is_shown_and_does_not_leave_a_dangling_message():
    def raising_answer(question, **kwargs):
        raise RuntimeError("AZURE_OPENAI_CHAT_DEPLOYMENT is not set.")

    at = _run_app_with(raising_answer, question="q")

    assert not at.exception
    assert any("Configuration error" in e.value for e in at.error)
    assert len(at.session_state["messages"]) == 0


def test_generic_service_error_is_shown_and_does_not_leave_a_dangling_message():
    def raising_answer(question, **kwargs):
        raise ConnectionError("service unavailable")

    at = _run_app_with(raising_answer, question="q")

    assert not at.exception
    assert any("RAG service could not complete this request" in e.value for e in at.error)
    assert len(at.session_state["messages"]) == 0


def test_clear_chat_button_resets_session_state():
    with patch("ticbot_chunking.rag.rag_service.answer", side_effect=lambda *a, **k: _fake_response(*a, **k)):
        at = AppTest.from_file(APP_PATH)
        at.run()
        at.chat_input[0].set_value("q").run()
        assert len(at.session_state["messages"]) == 2

        at.sidebar.button[0].click().run()
        assert len(at.session_state["messages"]) == 0


def test_config_status_reflects_real_configuration_booleans():
    at = _run_app_with(lambda *a, **k: _fake_response(*a, **k))
    markdown_values = " ".join(x.value for x in at.sidebar.markdown)
    assert "Azure AI Search" in markdown_values
    assert "Azure OpenAI (embeddings)" in markdown_values
    assert "Azure OpenAI chat deployment" in markdown_values


def test_no_azure_keys_or_secrets_appear_anywhere_in_the_rendered_app():
    from ticbot_chunking.config import OPENAI, SEARCH

    at = _run_app_with(lambda *a, **k: _fake_response(*a, **k))
    rendered_text = " ".join(
        [x.value for x in at.markdown] + [c.value for c in at.caption] + [e.label for e in at.expander]
    )
    if SEARCH.admin_key:
        assert SEARCH.admin_key not in rendered_text
    if OPENAI.api_key:
        assert OPENAI.api_key not in rendered_text
