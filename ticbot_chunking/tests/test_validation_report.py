import json

from ticbot_chunking.validation.edge_cases import EdgeCaseResult
from ticbot_chunking.validation.report import (
    build_chunk_inspection_report_markdown,
    build_edge_case_report_markdown,
    format_chunk_inspection_entry,
    format_edge_case_table,
    results_to_dicts,
)


def test_edge_case_result_status_mapping():
    assert EdgeCaseResult("e", "s", "x", "y", True).status == "PASS"
    assert EdgeCaseResult("e", "s", "x", "y", False).status == "FAIL"
    assert EdgeCaseResult("e", "s", "x", "y", None).status == "N/A"


def test_format_edge_case_table_has_four_columns_and_only_that_strategys_rows():
    results = [
        EdgeCaseResult("Check A", "fixed", "exp", "act", True),
        EdgeCaseResult("Check B", "fixed", "exp2", "act2", False),
        EdgeCaseResult("Check A", "hybrid", "exp", "act", True),
    ]
    table = format_edge_case_table(results, "fixed")
    lines = table.splitlines()
    assert lines[0] == "| Edge Case | Expected | Actual | Pass/Fail |"
    assert len(lines) == 4  # header + separator + 2 fixed rows
    assert "hybrid" not in table
    assert "PASS" in table and "FAIL" in table


def test_format_edge_case_table_escapes_pipes_and_newlines():
    results = [EdgeCaseResult("Check|A", "fixed", "exp\nwith newline", "act | with pipe", True)]
    table = format_edge_case_table(results, "fixed")
    data_line = table.splitlines()[2]
    assert data_line.count("|") == 5 + 2  # 5 column-boundary pipes (4 cols) + the 2 escaped content pipes
    assert "\n" not in data_line.strip()


def test_build_edge_case_report_markdown_sections_only_strategies_with_results():
    results = [EdgeCaseResult("Check A", "hybrid", "exp", "act", True)]
    md = build_edge_case_report_markdown(results)
    assert "## hybrid" in md
    assert "## fixed" not in md
    assert "does not declare a best strategy" in md.lower() or "not declare" in md.lower()


def test_results_to_dicts_round_trips_through_json():
    results = [EdgeCaseResult("Check A", "hybrid", "exp", "act", False, details="d")]
    dumped = json.dumps(results_to_dicts(results))
    loaded = json.loads(dumped)
    assert loaded[0]["edge_case"] == "Check A"
    assert loaded[0]["status"] == "FAIL"


def test_format_chunk_inspection_entry_includes_all_requested_fields():
    row = {
        "text": "the chunk body text",
        "metadata": {
            "source_file": "doc.pdf", "pages": [5, 6], "section_path": "Ch 1 > 1.1",
            "chunk_type": "table", "tokens": 123, "strategy": "hybrid",
        },
    }
    entry = format_chunk_inspection_entry(row, 3)
    assert "Chunk #3" in entry
    assert "doc.pdf" in entry
    assert "[5, 6]" in entry
    assert "Ch 1 > 1.1" in entry
    assert "table" in entry
    assert "123" in entry
    assert "the chunk body text" in entry


def test_build_chunk_inspection_report_groups_by_source_document():
    rows = [
        {"text": "t1", "metadata": {"source_file": "a.pdf", "chunk_type": "text", "tokens": 10}},
        {"text": "t2", "metadata": {"source_file": "b.pdf", "chunk_type": "text", "tokens": 10}},
        {"text": "t3", "metadata": {"source_file": "a.pdf", "chunk_type": "text", "tokens": 10}},
    ]
    md = build_chunk_inspection_report_markdown(rows, "hybrid")
    assert "## a.pdf" in md
    assert "## b.pdf" in md
    assert md.index("## a.pdf") < md.index("## b.pdf")
    # both a.pdf chunks appear under the a.pdf section, before b.pdf's section
    a_section = md[md.index("## a.pdf"):md.index("## b.pdf")]
    assert "t1" in a_section and "t3" in a_section
