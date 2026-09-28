from ticbot_chunking.validation import fixture_checks as fc


def _by_strategy(results):
    out = {}
    for r in results:
        out.setdefault(r.edge_case, {})[r.strategy] = r
    return out


def test_table_rows_not_split_all_strategies_run():
    results = fc.check_table_rows_not_split()
    by = _by_strategy(results)["Table rows being split"]
    assert set(by) == {"fixed", "recursive", "structure_aware", "hybrid"}
    # row-integrity-preserving strategies must keep every marker intact
    assert by["hybrid"].passed is True
    assert by["structure_aware"].passed is True
    assert by["recursive"].passed is True


def test_rowspan_carry_forward_passes_for_all_strategies():
    # every strategy flattens the table via the same rowspan-resolving
    # grid, so the carried label should show up regardless of strategy
    results = fc.check_rowspan_carry_forward()
    for r in results:
        assert r.passed is True, f"{r.strategy}: {r.actual}"


def test_nabl_grouping_only_meaningfully_checked_for_hybrid():
    results = fc.check_nabl_discipline_material_grouping()
    by = _by_strategy(results)["Incorrect NABL discipline/material grouping"]
    assert by["fixed"].passed is None
    assert by["recursive"].passed is None
    assert by["structure_aware"].passed is None
    assert by["hybrid"].passed is True


def test_nabl_grouping_detects_cross_contamination_if_present():
    # sanity-check the check itself can fail: patch chunk_hybrid's grouping
    # away isn't practical here, so instead assert the discipline split
    # actually happened as expected (a regression on this would show up as
    # a failure the moment grouping breaks)
    results = fc.check_nabl_discipline_material_grouping()
    hybrid_result = next(r for r in results if r.strategy == "hybrid")
    assert "CHEMICAL" in hybrid_result.actual
    assert "BIOLOGICAL" in hybrid_result.actual
    assert "cross-contamination=no" in hybrid_result.actual


def test_brochure_reading_order_clean_body_hybrid_passes_others_fail():
    results = fc.check_brochure_reading_order()
    by = _by_strategy(results)["Brochure reading order — clean 2-column body"]
    assert by["hybrid"].passed is True
    assert by["fixed"].passed is False
    assert by["recursive"].passed is False
    assert by["structure_aware"].passed is False


def test_brochure_reading_order_with_title_is_a_harder_case_for_everyone():
    # Documents a real, found limitation: a full-width title above the
    # columns currently breaks fix_reading_order's column bucketing even
    # for the hybrid strategy.
    results = fc.check_brochure_reading_order()
    by = _by_strategy(results)["Brochure reading order — full-width title above 2-column body"]
    assert by["hybrid"].passed is False


def test_excel_block_separation_structure_aware_and_hybrid_pass_naive_strategies_fail(tmp_path):
    results = fc.check_excel_block_separation(tmp_path)
    by = _by_strategy(results)["Incorrect Excel block separation"]
    assert by["hybrid"].passed is True
    assert by["structure_aware"].passed is True
    assert by["fixed"].passed is False
    assert by["recursive"].passed is False


def test_run_all_fixture_checks_returns_all_five_edge_cases(tmp_path):
    results = fc.run_all_fixture_checks(tmp_path)
    edge_cases = {r.edge_case for r in results}
    assert edge_cases == {
        "Table rows being split",
        "Rowspan/merged-label carry-forward",
        "Incorrect NABL discipline/material grouping",
        "Brochure reading order — clean 2-column body",
        "Brochure reading order — full-width title above 2-column body",
        "Incorrect Excel block separation",
    }
    # 4 strategies x 6 edge-case rows
    assert len(results) == 24
