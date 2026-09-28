from ticbot_chunking.validation import generic_checks as gc


def _row(tokens=100, chunk_type="text", source_file="a.pdf", pages=None, sheet=None, cell_range=None,
         section_path=None, row_count=None, text="some chunk text here"):
    meta = {"tokens": tokens, "chunk_type": chunk_type, "source_file": source_file}
    if pages is not None:
        meta["pages"] = pages
    if sheet is not None:
        meta["sheet"] = sheet
    if cell_range is not None:
        meta["cell_range"] = cell_range
    if section_path is not None:
        meta["section_path"] = section_path
    if row_count is not None:
        meta["row_count"] = row_count
    return {"text": text, "metadata": meta}


def test_missing_source_page_metadata_passes_when_every_chunk_is_cited():
    rows = [_row(pages=[1]), _row(sheet="S1", cell_range="A1:B2")]
    r = gc.check_missing_source_page_metadata(rows, "hybrid")
    assert r.passed is True


def test_missing_source_page_metadata_fails_when_a_chunk_has_no_location():
    rows = [_row(pages=[1]), _row(pages=None, sheet=None)]
    r = gc.check_missing_source_page_metadata(rows, "hybrid")
    assert r.passed is False
    assert "1/2" in r.actual


def test_missing_source_page_metadata_na_on_empty_corpus():
    r = gc.check_missing_source_page_metadata([], "hybrid")
    assert r.passed is None


def test_empty_tiny_chunks_detects_near_empty_text():
    rows = [_row(tokens=100), _row(tokens=2)]
    r = gc.check_empty_tiny_chunks(rows, "fixed")
    assert r.passed is False
    assert "1/2" in r.actual


def test_empty_tiny_chunks_detects_blank_text_regardless_of_token_count():
    rows = [_row(tokens=100, text="   ")]
    r = gc.check_empty_tiny_chunks(rows, "fixed")
    assert r.passed is False


def test_excessive_duplication_flags_exact_duplicate_text():
    rows = [_row(text="same text"), _row(text="same text"), _row(text="different")]
    r = gc.check_excessive_duplication(rows, "hybrid")
    assert r.passed is False
    assert "2 chunk" in r.actual or "2)" in r.actual


def test_excessive_duplication_passes_with_all_unique_text():
    rows = [_row(text="a"), _row(text="b"), _row(text="c")]
    r = gc.check_excessive_duplication(rows, "hybrid")
    assert r.passed is True


def test_token_limit_violations_flags_chunk_over_its_type_limit():
    rows = [_row(tokens=900, chunk_type="table")]
    r = gc.check_token_limit_violations(rows, "hybrid", limit_fn=lambda ct: {"table": 550}.get(ct))
    assert r.passed is False


def test_token_limit_violations_ignores_types_with_no_known_limit():
    rows = [_row(tokens=900, chunk_type="figure")]
    r = gc.check_token_limit_violations(rows, "hybrid", limit_fn=lambda ct: {"table": 550}.get(ct))
    assert r.passed is True  # no limit defined for "figure" -> nothing to violate


def test_missing_table_headers_na_when_no_table_chunks():
    rows = [_row(chunk_type="text")]
    r = gc.check_missing_table_headers(rows, "fixed")
    assert r.passed is None


def test_missing_table_headers_passes_with_markdown_separator():
    rows = [_row(chunk_type="table", text="header\n| a | b |\n| --- | --- |\n| 1 | 2 |")]
    r = gc.check_missing_table_headers(rows, "hybrid")
    assert r.passed is True


def test_missing_table_headers_passes_with_columns_line():
    rows = [_row(chunk_type="sheet_table", text="header\nColumns: A | B\nRow 2 — A: 1 | B: 2")]
    r = gc.check_missing_table_headers(rows, "hybrid")
    assert r.passed is True


def test_missing_table_headers_passes_with_scope_records_intro():
    rows = [_row(chunk_type="scope_records", text="header\nAccredited tests:\nS.No 1: X — Method: Y")]
    r = gc.check_missing_table_headers(rows, "hybrid")
    assert r.passed is True


def test_missing_table_headers_fails_when_no_marker_present():
    rows = [_row(chunk_type="table", text="just some rows with no header line at all")]
    r = gc.check_missing_table_headers(rows, "hybrid")
    assert r.passed is False


def test_missing_section_hierarchy_is_na_for_fixed_and_recursive_by_design():
    rows = [_row(chunk_type="text", source_file="a.pdf", section_path=None)]
    for strategy in ("fixed", "recursive"):
        r = gc.check_missing_section_hierarchy(rows, strategy)
        assert r.passed is None


def test_missing_section_hierarchy_fails_for_hybrid_when_section_path_absent():
    rows = [_row(chunk_type="text", source_file="a.pdf", section_path=None)]
    r = gc.check_missing_section_hierarchy(rows, "hybrid")
    assert r.passed is False


def test_missing_section_hierarchy_passes_for_hybrid_when_section_path_present():
    rows = [_row(chunk_type="text", source_file="a.pdf", section_path="Chapter 1 > 1.1")]
    r = gc.check_missing_section_hierarchy(rows, "hybrid")
    assert r.passed is True


def test_missing_section_hierarchy_ignores_excel_chunks():
    rows = [_row(chunk_type="sheet_table", source_file="a.xlsx", section_path=None)]
    r = gc.check_missing_section_hierarchy(rows, "hybrid")
    assert r.passed is None  # no PDF chunks in this corpus to judge


def test_multi_page_table_continuity_na_with_no_multi_page_chunks():
    rows = [_row(pages=[1])]
    r = gc.check_multi_page_table_continuity(rows, "hybrid")
    assert r.passed is None


def test_multi_page_table_continuity_fails_when_row_count_missing_on_table_chunk():
    rows = [_row(pages=[1, 2], chunk_type="table", row_count=None)]
    r = gc.check_multi_page_table_continuity(rows, "hybrid")
    assert r.passed is False


def test_multi_page_table_continuity_passes_when_well_formed():
    rows = [_row(pages=[1, 2], chunk_type="table", row_count=5, tokens=200)]
    r = gc.check_multi_page_table_continuity(rows, "hybrid")
    assert r.passed is True


def test_run_all_generic_checks_returns_seven_results():
    rows = [_row(pages=[1])]
    results = gc.run_all_generic_checks(rows, "hybrid", limit_fn=lambda ct: None)
    assert len(results) == 7
    assert all(r.strategy == "hybrid" for r in results)
