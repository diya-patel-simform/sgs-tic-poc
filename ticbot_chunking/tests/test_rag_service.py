"""Tests for the RAG service (ticbot_chunking/rag/rag_service.py).
`search_fn` and `chat_fn` are both injected — no real Azure AI Search or
Azure OpenAI service is contacted anywhere in this file.
"""
from __future__ import annotations

from ticbot_chunking.rag.prompt import NO_CONTEXT_ANSWER
from ticbot_chunking.rag.rag_service import answer
from ticbot_chunking.search.retrieval_client import RetrievalQueryResult, RetrievalResult


def _result(rank=1, **overrides):
    defaults = dict(
        rank=rank, score=1.0, reranker_score=None, chunk_id=f"c{rank}", text=f"chunk {rank} text",
        chunking_strategy="hybrid", source_file="a.pdf", blob_path="a.pdf", parser_used="local_pdf",
        pages=None, section_path=None, section_number=None, chunk_type="text", document_type="regulation",
        sheet=None, cell_range=None, authority=None, lab_location=None, certificate_no=None,
        discipline=None, material=None, facility=None,
    )
    defaults.update(overrides)
    return RetrievalResult(**defaults)


def _query_result(results, strategy="hybrid", mode="hybrid", latency=0.1):
    return RetrievalQueryResult(query="q", strategy=strategy, index_name=f"ticbot-chunks-{strategy}", mode=mode,
                                 top_k=5, filter=None, latency_seconds=latency, results=results)


def _search_fn_returning(query_result):
    calls = []

    def fn(strategy, mode, question, top_k=5, filter=None, index_name=None):
        calls.append((strategy, mode, question, top_k, filter, index_name))
        return query_result

    fn.calls = calls
    return fn


def _chat_fn_returning(text):
    calls = []

    def fn(messages):
        calls.append(messages)
        return text

    fn.calls = calls
    return fn


def test_defaults_to_hybrid_strategy_and_vector_mode():
    # "vector" is config.SEARCH.retrieval_mode's default — manual testing
    # found it far more reliable than keyword mode, and hybrid is kept
    # available behind that same config flag rather than as the default.
    search_fn = _search_fn_returning(_query_result([_result()]))
    chat_fn = _chat_fn_returning("Answer text [1]")

    answer("What is the certificate number?", search_fn=search_fn, chat_fn=chat_fn)

    strategy, mode, question, top_k, filter_, index_name = search_fn.calls[0]
    assert strategy == "hybrid"
    assert mode == "vector"


def test_keyword_and_vector_modes_can_be_selected():
    for mode in ("keyword", "vector"):
        search_fn = _search_fn_returning(_query_result([_result()]))
        chat_fn = _chat_fn_returning("Answer [1]")
        answer("q", mode=mode, search_fn=search_fn, chat_fn=chat_fn)
        assert search_fn.calls[0][1] == mode


# ---------------------------------------------------------------------------
# Citation deduplication — two [N] markers pointing at the same
# source_file+section collapse into one Citation carrying both source
# numbers, instead of rendering as two redundant citation blocks.
# ---------------------------------------------------------------------------

def test_two_citations_of_the_same_source_and_section_are_merged():
    result = _result(rank=1, chunk_id="c1", source_file="reg.pdf", section_path="Chapter 2 > 2.1")
    search_fn = _search_fn_returning(_query_result([result]))
    # The model cites the SAME source twice ([1][1]) — a degenerate but
    # real-enough case to exercise the merge path directly.
    chat_fn = _chat_fn_returning("Copper limit is 15.0 ppm [1]. See also [1] for the qualifier.")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert len(response.citations) == 1
    assert response.citations[0].source_numbers == [1]


def test_two_different_chunk_ids_same_source_and_section_merge_and_keep_both_numbers():
    results = [
        _result(rank=1, chunk_id="c1", source_file="reg.pdf", section_path="Chapter 2 > 2.1"),
        _result(rank=2, chunk_id="c2", source_file="reg.pdf", section_path="Chapter 2 > 2.1"),
    ]
    search_fn = _search_fn_returning(_query_result(results))
    chat_fn = _chat_fn_returning("Copper limit is 15.0 ppm [1][2].")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert len(response.citations) == 1
    assert response.citations[0].source_numbers == [1, 2]
    assert response.citations[0].source_file == "reg.pdf"


def test_same_source_file_different_sections_are_not_merged():
    results = [
        _result(rank=1, chunk_id="c1", source_file="reg.pdf", section_path="Chapter 2 > 2.1"),
        _result(rank=2, chunk_id="c2", source_file="reg.pdf", section_path="Chapter 2 > 2.2"),
    ]
    search_fn = _search_fn_returning(_query_result(results))
    chat_fn = _chat_fn_returning("Copper is in 2.1 [1]; Arsenic is in 2.2 [2].")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert len(response.citations) == 2
    assert {c.section for c in response.citations} == {"Chapter 2 > 2.1", "Chapter 2 > 2.2"}


def test_strategy_top_k_and_filter_are_forwarded_to_retrieval():
    search_fn = _search_fn_returning(_query_result([_result()]))
    chat_fn = _chat_fn_returning("Answer [1]")

    answer("q", strategy="fixed", top_k=10, filter="document_type eq 'regulation'",
           search_fn=search_fn, chat_fn=chat_fn)

    strategy, mode, question, top_k, filter_, index_name = search_fn.calls[0]
    assert strategy == "fixed"
    assert top_k == 10
    assert filter_ == "document_type eq 'regulation'"


def test_index_name_override_is_forwarded_to_retrieval():
    search_fn = _search_fn_returning(_query_result([_result()]))
    chat_fn = _chat_fn_returning("Answer [1]")

    answer("q", index_name="ticbot-chunks-hybrid-updated", search_fn=search_fn, chat_fn=chat_fn)

    assert search_fn.calls[0][5] == "ticbot-chunks-hybrid-updated"


def test_question_flows_through_retrieval_context_and_llm():
    result = _result(text="Arsenic limit in milk is 0.1 mg/kg", source_file="reg.pdf")
    search_fn = _search_fn_returning(_query_result([result]))
    chat_fn = _chat_fn_returning("The limit is 0.1 mg/kg [1].")

    response = answer("What is the arsenic limit in milk?", search_fn=search_fn, chat_fn=chat_fn)

    assert response.answer == "The limit is 0.1 mg/kg [1]."
    # the context passed to the LLM included the real retrieved chunk text
    messages = chat_fn.calls[0]
    user_message = messages[-1]["content"]
    assert "Arsenic limit in milk is 0.1 mg/kg" in user_message
    assert "reg.pdf" in user_message


def test_retrieved_metadata_is_preserved_on_the_response():
    result = _result(source_file="a.pdf", pages=[3], section_path="Chapter 1")
    search_fn = _search_fn_returning(_query_result([result]))
    chat_fn = _chat_fn_returning("Answer [1]")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert len(response.retrieved_chunks) == 1
    assert response.retrieved_chunks[0].source_file == "a.pdf"
    assert response.retrieved_chunks[0].pages == [3]
    assert response.retrieved_chunks[0].section_path == "Chapter 1"


def test_citation_metadata_comes_from_the_retrieved_chunk_not_the_llm():
    result = _result(chunk_id="real-chunk-id", source_file="reg.pdf", pages=[5])
    search_fn = _search_fn_returning(_query_result([result]))
    chat_fn = _chat_fn_returning("The answer is X [1].")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert len(response.citations) == 1
    assert response.citations[0].chunk_id == "real-chunk-id"
    assert response.citations[0].source_file == "reg.pdf"
    assert response.citations[0].page == "5"


def test_llm_cannot_introduce_a_citation_for_a_source_it_was_not_given():
    result = _result(chunk_id="only-real-chunk")
    search_fn = _search_fn_returning(_query_result([result]))
    # The model hallucinates a reference to source [99], which was never given to it.
    chat_fn = _chat_fn_returning("According to source [99], the answer is X.")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert response.citations == []  # [99] is out of range and must be dropped, not fabricated


def test_llm_citing_a_valid_and_an_invalid_source_keeps_only_the_valid_one():
    results = [_result(rank=1, chunk_id="c1"), _result(rank=2, chunk_id="c2")]
    search_fn = _search_fn_returning(_query_result(results))
    chat_fn = _chat_fn_returning("Per [1] and [7], the answer is X.")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert [c.chunk_id for c in response.citations] == ["c1"]


def test_no_citation_markers_defaults_to_citing_every_supplied_source():
    results = [_result(rank=1, chunk_id="c1"), _result(rank=2, chunk_id="c2")]
    search_fn = _search_fn_returning(_query_result(results))
    chat_fn = _chat_fn_returning("The answer is X, based on the documents.")  # no [N] markers

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert {c.chunk_id for c in response.citations} == {"c1", "c2"}


def test_empty_retrieval_is_handled_safely_without_calling_the_llm():
    search_fn = _search_fn_returning(_query_result([]))
    chat_fn = _chat_fn_returning("should never be called")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert response.answer == NO_CONTEXT_ANSWER
    assert response.citations == []
    assert response.retrieved_chunks == []
    assert response.context_used is False
    assert response.llm_latency_seconds is None
    assert chat_fn.calls == []  # never called — no cost incurred for an empty retrieval


def test_llm_declining_due_to_insufficient_context_produces_no_citations():
    result = _result(source_file="irrelevant.pdf")
    search_fn = _search_fn_returning(_query_result([result]))
    chat_fn = _chat_fn_returning(NO_CONTEXT_ANSWER)

    response = answer("an unrelated question", search_fn=search_fn, chat_fn=chat_fn)

    assert response.answer == NO_CONTEXT_ANSWER
    assert response.citations == []
    assert response.context_used is True  # retrieval did return something; the LLM chose not to use it
    assert len(response.retrieved_chunks) == 1  # kept available for debugging


def test_excel_citation_preserves_sheet_and_cell_range():
    result = _result(source_file="book.xlsx", sheet="Key Contacts", cell_range="A5:H10", pages=None)
    search_fn = _search_fn_returning(_query_result([result]))
    chat_fn = _chat_fn_returning("Answer [1]")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert response.citations[0].sheet == "Key Contacts"
    assert response.citations[0].cell_range == "A5:H10"
    assert response.citations[0].page is None


def test_pdf_citation_preserves_page_information():
    result = _result(source_file="reg.pdf", pages=[1, 2, 3])
    search_fn = _search_fn_returning(_query_result([result]))
    chat_fn = _chat_fn_returning("Answer [1]")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert response.citations[0].page == "1, 2, 3"


def test_nabl_citation_preserves_certificate_lab_and_scope_metadata():
    result = _result(
        source_file="nabl.pdf", document_type="accreditation_scope", certificate_no="TC-5378",
        lab_location="SGS INDIA PVT. LTD.", discipline="BIOLOGICAL- ANIMAL FOOD & FEED",
        material="Corn gluten, Soybean",
    )
    search_fn = _search_fn_returning(_query_result([result]))
    chat_fn = _chat_fn_returning("Answer [1]")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    c = response.citations[0]
    assert c.certificate_no == "TC-5378"
    assert c.lab_location == "SGS INDIA PVT. LTD."
    assert c.discipline == "BIOLOGICAL- ANIMAL FOOD & FEED"
    assert c.material == "Corn gluten, Soybean"


def test_response_reports_retrieval_and_llm_latency():
    search_fn = _search_fn_returning(_query_result([_result()], latency=0.42))
    chat_fn = _chat_fn_returning("Answer [1]")

    response = answer("q", search_fn=search_fn, chat_fn=chat_fn)

    assert response.retrieval_latency_seconds == 0.42
    assert response.llm_latency_seconds is not None
    assert response.total_latency_seconds >= 0.42
