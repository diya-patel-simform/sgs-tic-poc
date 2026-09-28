from ticbot_chunking.search.eval_metrics import (
    Question,
    aggregate,
    aggregate_by_category,
    is_relevant,
    load_questions,
    score_query_result,
)
from ticbot_chunking.search.retrieval_client import RetrievalQueryResult, RetrievalResult


def _question(**overrides):
    defaults = dict(
        question_id="Q001", category="A", question="What?", expected_source_file="a.pdf",
        expected_pages=[3], expected_sheet=None, expected_cell_range=None, expected_metadata=None,
        suggested_filter=None, ground_truth_status="available", notes="verified",
    )
    defaults.update(overrides)
    return Question(**defaults)


def _result(rank, source_file="a.pdf", pages=None, sheet=None, score=1.0):
    return RetrievalResult(
        rank=rank, score=score, reranker_score=None, chunk_id=f"c{rank}", text="text",
        chunking_strategy="fixed", source_file=source_file, blob_path=source_file, parser_used="local_pdf",
        pages=pages or [], section_path=None, section_number=None, chunk_type="text", document_type="regulation",
        sheet=sheet, cell_range=None, authority=None, lab_location=None, certificate_no=None,
        discipline=None, material=None, facility=None,
    )


def _query_result(results, strategy="fixed", mode="keyword", latency=0.1):
    return RetrievalQueryResult(query="What?", strategy=strategy, index_name="ticbot-chunks-fixed", mode=mode,
                                 top_k=5, filter=None, latency_seconds=latency, results=results)


def test_load_questions_parses_jsonl(tmp_path):
    path = tmp_path / "q.jsonl"
    path.write_text(
        '{"question_id": "Q001", "category": "A", "question": "x", "expected_source_file": "a.pdf", '
        '"expected_pages": [1], "expected_sheet": null, "expected_cell_range": null, '
        '"expected_metadata": null, "suggested_filter": null, "ground_truth_status": "available", '
        '"notes": "n"}\n'
    )
    questions = load_questions(path)
    assert len(questions) == 1
    assert questions[0].question_id == "Q001"
    assert questions[0].has_ground_truth is True


def test_has_ground_truth_false_for_not_available():
    q = _question(ground_truth_status="not_available", expected_source_file=None)
    assert q.has_ground_truth is False


def test_has_ground_truth_true_for_partial():
    q = _question(ground_truth_status="partial")
    assert q.has_ground_truth is True


def test_is_relevant_matches_on_source_file_and_page_overlap():
    q = _question(expected_pages=[3, 4])
    assert is_relevant(_result(1, source_file="a.pdf", pages=[4, 5]), q) is True
    assert is_relevant(_result(1, source_file="a.pdf", pages=[9]), q) is False
    assert is_relevant(_result(1, source_file="b.pdf", pages=[3]), q) is False


def test_is_relevant_ignores_page_check_when_question_has_no_expected_pages():
    q = _question(expected_pages=None)
    assert is_relevant(_result(1, source_file="a.pdf", pages=[999]), q) is True


def test_is_relevant_checks_sheet_when_specified():
    q = _question(expected_pages=None, expected_sheet="Sheet1")
    assert is_relevant(_result(1, source_file="a.pdf", sheet="Sheet1"), q) is True
    assert is_relevant(_result(1, source_file="a.pdf", sheet="Sheet2"), q) is False


def test_is_relevant_false_when_question_has_no_expected_source_file():
    q = _question(expected_source_file=None)
    assert is_relevant(_result(1, source_file="a.pdf"), q) is False


def test_score_query_result_hit_at_1_when_relevant_result_is_first():
    q = _question()
    qr = _query_result([_result(1, pages=[3]), _result(2, source_file="other.pdf")])
    outcome = score_query_result(qr, q)
    assert outcome.hit_at_1 is True
    assert outcome.hit_at_3 is True
    assert outcome.hit_at_5 is True
    assert outcome.first_relevant_rank == 1


def test_score_query_result_hit_at_1_false_when_relevant_result_is_third():
    q = _question()
    qr = _query_result([_result(1, source_file="x.pdf"), _result(2, source_file="y.pdf"),
                         _result(3, pages=[3])])
    outcome = score_query_result(qr, q)
    assert outcome.hit_at_1 is False
    assert outcome.hit_at_3 is True
    assert outcome.first_relevant_rank == 3


def test_score_query_result_no_hits_at_any_k():
    q = _question()
    qr = _query_result([_result(1, source_file="other.pdf")])
    outcome = score_query_result(qr, q)
    assert outcome.hit_at_1 is False
    assert outcome.hit_at_3 is False
    assert outcome.hit_at_5 is False
    assert outcome.first_relevant_rank is None


def test_score_query_result_none_hits_for_a_question_without_ground_truth():
    q = _question(ground_truth_status="not_available", expected_source_file=None)
    qr = _query_result([_result(1, source_file="a.pdf", pages=[3])])
    outcome = score_query_result(qr, q)
    assert outcome.hit_at_1 is None
    assert outcome.hit_at_3 is None
    assert outcome.hit_at_5 is None
    assert outcome.has_ground_truth is False


def test_score_query_result_empty_flag_and_num_results():
    q = _question()
    qr = _query_result([])
    outcome = score_query_result(qr, q)
    assert outcome.empty is True
    assert outcome.num_results == 0


def test_score_query_result_avg_score():
    q = _question()
    qr = _query_result([_result(1, pages=[3], score=2.0), _result(2, source_file="x.pdf", score=4.0)])
    outcome = score_query_result(qr, q)
    assert outcome.avg_score == 3.0


def test_aggregate_computes_rates_over_scored_questions_only():
    q1 = _question(question_id="Q001")
    q2 = _question(question_id="Q002", ground_truth_status="not_available", expected_source_file=None)
    outcomes = [
        score_query_result(_query_result([_result(1, pages=[3])]), q1),   # hit
        score_query_result(_query_result([_result(1, source_file="z.pdf")]), q2),  # not scored
    ]
    metrics = aggregate(outcomes, "fixed", "keyword", top_k=5)
    assert metrics.num_questions == 2
    assert metrics.num_scored_questions == 1
    assert metrics.hit_at_1 == 1.0
    assert metrics.source_recall == 1.0


def test_aggregate_source_recall_zero_when_no_scored_hits():
    q = _question()
    outcomes = [score_query_result(_query_result([_result(1, source_file="other.pdf")]), q)]
    metrics = aggregate(outcomes, "fixed", "vector", top_k=5)
    assert metrics.source_recall == 0.0
    assert metrics.hit_at_1 == 0.0


def test_aggregate_handles_no_scored_questions_without_crashing():
    q = _question(ground_truth_status="not_available", expected_source_file=None)
    outcomes = [score_query_result(_query_result([]), q)]
    metrics = aggregate(outcomes, "fixed", "keyword", top_k=5)
    assert metrics.num_scored_questions == 0
    assert metrics.hit_at_1 is None
    assert metrics.source_recall is None


def test_aggregate_by_category_splits_outcomes_by_category_preserving_order():
    q_a1 = _question(question_id="Q001", category="A")
    q_a2 = _question(question_id="Q002", category="A")
    q_b1 = _question(question_id="Q003", category="B", expected_source_file="b.pdf", expected_pages=None)
    outcomes = [
        score_query_result(_query_result([_result(1, pages=[3])]), q_a1),  # hit
        score_query_result(_query_result([_result(1, source_file="x.pdf")]), q_a2),  # miss
        score_query_result(_query_result([_result(1, source_file="b.pdf")]), q_b1),  # hit (no page check)
    ]

    per_category = aggregate_by_category(outcomes, "fixed", "keyword", top_k=5)

    assert [m.category for m in per_category] == ["A", "B"]
    a_metrics = per_category[0]
    assert a_metrics.num_questions == 2
    assert a_metrics.hit_at_1 == 0.5
    b_metrics = per_category[1]
    assert b_metrics.num_questions == 1
    assert b_metrics.hit_at_1 == 1.0


def test_aggregate_sets_category_none_by_default():
    q = _question()
    outcomes = [score_query_result(_query_result([_result(1, pages=[3])]), q)]
    metrics = aggregate(outcomes, "fixed", "keyword", top_k=5)
    assert metrics.category is None


def test_aggregate_counts_empty_retrievals_and_latency():
    q = _question()
    outcomes = [
        score_query_result(_query_result([], latency=0.5), q),
        score_query_result(_query_result([_result(1, pages=[3])], latency=1.5), q),
    ]
    metrics = aggregate(outcomes, "fixed", "keyword", top_k=5)
    assert metrics.empty_retrieval_count == 1
    assert metrics.avg_latency_seconds == 1.0
