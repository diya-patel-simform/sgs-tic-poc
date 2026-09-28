from ticbot_chunking.search.eval_metrics import AggregateMetrics
from ticbot_chunking.search.eval_report import build_comparison_report_json, build_comparison_report_markdown


def _metrics(strategy, mode, hit_at_1=0.5):
    return AggregateMetrics(
        strategy=strategy, mode=mode, top_k=5, num_questions=4, num_scored_questions=3,
        hit_at_1=hit_at_1, hit_at_3=0.66, hit_at_5=1.0, source_recall=1.0, citation_precision=0.5,
        avg_num_results=5.0, avg_score=1.2, empty_retrieval_count=0, avg_latency_seconds=0.2,
    )


def test_report_json_includes_every_combination_and_no_winner_field():
    all_metrics = [_metrics("fixed", "keyword"), _metrics("hybrid", "vector")]
    report = build_comparison_report_json(all_metrics, ["fixed", "hybrid"], ["keyword", "vector"], 4, 5, [])

    assert report["num_combinations_tested"] == 2
    assert len(report["results"]) == 2
    assert "winner" not in report
    assert "best_strategy" not in report
    assert "no overall winner" in report["note"].lower()


def test_report_json_carries_missing_ground_truth_list_through():
    missing = [{"question_id": "Q008", "category": "E", "reason": "not indexed"}]
    report = build_comparison_report_json([_metrics("fixed", "keyword")], ["fixed"], ["keyword"], 1, 5, missing)
    assert report["missing_ground_truth"] == missing


def test_markdown_renders_a_row_per_combination():
    all_metrics = [_metrics("fixed", "keyword"), _metrics("fixed", "vector"), _metrics("hybrid", "hybrid")]
    report = build_comparison_report_json(all_metrics, ["fixed", "hybrid"], ["keyword", "vector", "hybrid"],
                                           4, 5, [])
    md = build_comparison_report_markdown(report)

    assert "| Strategy | Mode | Hit@1 |" in md
    assert "| fixed | keyword |" in md
    assert "| fixed | vector |" in md
    assert "| hybrid | hybrid |" in md
    assert "No strategy is automatically ranked" in md


def test_markdown_handles_none_metrics_as_not_applicable():
    m = AggregateMetrics(strategy="fixed", mode="keyword", top_k=5, num_questions=1, num_scored_questions=0,
                          hit_at_1=None, hit_at_3=None, hit_at_5=None, source_recall=None,
                          citation_precision=None, avg_num_results=0.0, avg_score=None,
                          empty_retrieval_count=1, avg_latency_seconds=0.1)
    report = build_comparison_report_json([m], ["fixed"], ["keyword"], 1, 5, [])
    md = build_comparison_report_markdown(report)
    assert "n/a" in md


def _category_metrics(strategy, mode, category, hit_at_1=1.0):
    return AggregateMetrics(
        strategy=strategy, mode=mode, top_k=5, num_questions=2, num_scored_questions=2,
        hit_at_1=hit_at_1, hit_at_3=1.0, hit_at_5=1.0, source_recall=1.0, citation_precision=0.5,
        avg_num_results=5.0, avg_score=1.2, empty_retrieval_count=0, avg_latency_seconds=0.2,
        category=category,
    )


def test_report_json_includes_by_category_and_labels():
    by_category = [_category_metrics("fixed", "keyword", "D"), _category_metrics("fixed", "keyword", "F")]
    report = build_comparison_report_json([_metrics("fixed", "keyword")], ["fixed"], ["keyword"], 20, 5, [],
                                           by_category=by_category)

    assert len(report["by_category"]) == 2
    assert report["by_category"][0]["category"] == "D"
    assert "NABL" in report["category_labels"]["D"]


def test_report_json_by_category_empty_when_not_given():
    report = build_comparison_report_json([_metrics("fixed", "keyword")], ["fixed"], ["keyword"], 20, 5, [])
    assert report["by_category"] == []


def test_markdown_renders_one_section_per_category():
    by_category = [
        _category_metrics("fixed", "keyword", "D"),
        _category_metrics("hybrid", "keyword", "D"),
        _category_metrics("fixed", "keyword", "F"),
    ]
    report = build_comparison_report_json([_metrics("fixed", "keyword")], ["fixed", "hybrid"], ["keyword"],
                                           20, 5, [], by_category=by_category)
    md = build_comparison_report_markdown(report)

    assert "## Document-type / category breakdown" in md
    assert "### Category D" in md
    assert "NABL scope information" in md
    assert "### Category F" in md
    assert "| fixed | keyword |" in md
    assert "| hybrid | keyword |" in md


def test_markdown_omits_category_breakdown_section_when_absent():
    report = build_comparison_report_json([_metrics("fixed", "keyword")], ["fixed"], ["keyword"], 20, 5, [])
    md = build_comparison_report_markdown(report)
    assert "Document-type / category breakdown" not in md


def test_markdown_includes_missing_ground_truth_section_only_when_present():
    report_without = build_comparison_report_json([_metrics("fixed", "keyword")], ["fixed"], ["keyword"], 1, 5, [])
    md_without = build_comparison_report_markdown(report_without)
    assert "Questions without verifiable ground truth" not in md_without

    missing = [{"question_id": "Q008", "category": "E", "reason": "not indexed"}]
    report_with = build_comparison_report_json([_metrics("fixed", "keyword")], ["fixed"], ["keyword"], 1, 5, missing)
    md_with = build_comparison_report_markdown(report_with)
    assert "Questions without verifiable ground truth" in md_with
    assert "Q008" in md_with
