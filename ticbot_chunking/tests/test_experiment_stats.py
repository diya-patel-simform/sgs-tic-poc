import json

from ticbot_chunking.experiments.stats import (
    build_comparison_report,
    compute_strategy_stats,
    format_comparison_table,
    load_all_stats,
)


def _row(tokens, doc_type="brochure", chunk_type="text", source_file="a.pdf", pages=None, sheet=None):
    meta = {"tokens": tokens, "doc_type": doc_type, "chunk_type": chunk_type, "source_file": source_file}
    if pages is not None:
        meta["pages"] = pages
    if sheet is not None:
        meta["sheet"] = sheet
    return {"text": "x", "metadata": meta}


def test_compute_strategy_stats_basic_aggregates():
    rows = [
        _row(100, pages=[1]),
        _row(200, pages=[1, 2]),
        _row(300, doc_type="regulation", chunk_type="table", pages=[3]),
    ]
    s = compute_strategy_stats(rows, strategy="fixed", chunk_size=400, max_chunk_size=700)

    assert s["strategy"] == "fixed"
    assert s["total_chunks"] == 3
    assert s["documents"] == 1
    assert s["tokens_min"] == 100
    assert s["tokens_max"] == 300
    assert s["tokens_avg"] == 200.0
    assert s["by_doc_type"] == {"brochure": 2, "regulation": 1}
    assert s["by_chunk_type"] == {"text": 2, "table": 1}
    assert s["pages_covered"] == 3  # (a.pdf,1) (a.pdf,2) (a.pdf,3)


def test_compute_strategy_stats_flags_tiny_and_oversized():
    rows = [_row(10), _row(50), _row(900)]
    s = compute_strategy_stats(rows, strategy="fixed", chunk_size=400, max_chunk_size=700)

    # tiny floor = 400 * 0.25 = 100 -> the 10 and 50 token chunks are tiny
    assert s["tiny_chunks"] == 2
    # oversized: > max_chunk_size (700) -> the 900 token chunk
    assert s["oversized_chunks"] == 1


def test_compute_strategy_stats_counts_sheets_for_excel_chunks():
    rows = [_row(100, source_file="book.xlsx", sheet="Sheet1"), _row(100, source_file="book.xlsx", sheet="Sheet1"),
            _row(100, source_file="book.xlsx", sheet="Sheet2")]
    s = compute_strategy_stats(rows, strategy="hybrid", chunk_size=400, max_chunk_size=700)
    assert s["sheets_covered"] == 2


def test_compute_strategy_stats_on_empty_input_does_not_crash():
    s = compute_strategy_stats([], strategy="fixed", chunk_size=400, max_chunk_size=700)
    assert s["total_chunks"] == 0
    assert s["tokens_min"] == 0
    assert s["tokens_avg"] == 0


def test_load_all_stats_scans_output_dir_for_every_strategy(tmp_path):
    for strategy in ("fixed", "hybrid"):
        d = tmp_path / strategy
        d.mkdir()
        with open(d / "stats.json", "w") as f:
            json.dump({"strategy": strategy, "total_chunks": 1}, f)
    (tmp_path / "comparison_report.json").write_text("{}")  # should not be picked up as a strategy

    loaded = load_all_stats(tmp_path)
    assert {s["strategy"] for s in loaded} == {"fixed", "hybrid"}


def test_build_comparison_report_does_not_declare_a_winner():
    report = build_comparison_report([{"strategy": "fixed"}, {"strategy": "hybrid"}])
    assert "best" not in json.dumps(report).lower() or "does not" in report["note"].lower()
    assert len(report["strategies"]) == 2


def test_format_comparison_table_includes_every_strategy_row():
    rows = [
        compute_strategy_stats([_row(100)], "fixed", 400, 700),
        compute_strategy_stats([_row(200)], "hybrid", 400, 700),
    ]
    table = format_comparison_table(rows)
    assert "fixed" in table
    assert "hybrid" in table
