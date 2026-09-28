from ticbot_chunking.chunkers import table_utils
from ticbot_chunking.parsers.ir import Table, TableCell

# The synonym/keyword lists regulation.py and brochure.py actually use in
# production (kept here, not imported, so this test documents the contract
# independently of those chunkers' internals changing).
REGULATION_SYNONYMS = {"insecticide": "entity", "metal": "entity", "contaminant": "entity", "food": "food",
                        "tolerance limit": "limit"}
REGULATION_KEYWORD_FALLBACKS = [("insecticide", "entity"), ("metal", "entity"), ("contaminant", "entity"),
                                 ("food", "food"), ("limit", "limit")]
CATALOG_SYNONYMS = {"id": "product_id", "product": "product"}
CATALOG_KEYWORD_FALLBACKS = [("id", "product_id"), ("product", "product")]


def _insecticide_table() -> Table:
    """Mirrors the sample in section 5A of TICbot_Chunking_Strategy_Answers.md:
    the insecticide name is printed once (rowspan 3) but must carry onto every
    row it applies to, including the one that lands on the next page.
    """
    cells = [
        TableCell(0, 0, "Sl.No.", kind="columnHeader", page_number=5),
        TableCell(0, 1, "Name of Insecticides", kind="columnHeader", page_number=5),
        TableCell(0, 2, "Food", kind="columnHeader", page_number=5),
        TableCell(0, 3, "Tolerance limit mg/kg (ppm)", kind="columnHeader", page_number=5),
        TableCell(1, 0, "2", row_span=3, page_number=5),
        TableCell(1, 1, "Carbaryl", row_span=3, page_number=5),
        TableCell(1, 2, "Fish", page_number=5),
        TableCell(1, 3, "0.2", page_number=5),
        TableCell(2, 2, "Foodgrains", page_number=5),
        TableCell(2, 3, "1.5", page_number=5),
        TableCell(3, 2, "Okra and leafy vegetables", page_number=6),  # printed on page 6, no name repeated
        TableCell(3, 3, "10.0", page_number=6),
        TableCell(4, 0, "3", page_number=6),
        TableCell(4, 1, "Chlordane (residue to be measured as cis plus trans chlordane)", page_number=6),
        TableCell(4, 2, "Sugar beet", page_number=6),
        TableCell(4, 3, "0.3", page_number=6),
    ]
    return Table(row_count=5, column_count=4, cells=cells, page_numbers=[5, 6], preceding_paragraph_index=4)


def test_resolve_grid_carries_rowspan_label_onto_every_row():
    table = _insecticide_table()
    grid = table_utils.resolve_grid(table)

    assert grid[1][1] == "Carbaryl"
    assert grid[2][1] == "Carbaryl"
    assert grid[3][1] == "Carbaryl"  # the page-6 row with no name printed in the source


def test_extract_logical_rows_skips_no_subgroup_rows_when_absent():
    table = _insecticide_table()
    grid = table_utils.resolve_grid(table)
    rows = table_utils.extract_logical_rows(grid, data_start_row=1, page_numbers_by_row={
        1: 5, 2: 5, 3: 6, 4: 6,
    })

    assert len(rows) == 4
    assert [r.values[1] for r in rows] == ["Carbaryl", "Carbaryl", "Carbaryl", "Chlordane (residue to be measured as cis plus trans chlordane)"]
    assert [r.page_number for r in rows] == [5, 5, 6, 6]
    assert all(r.subgroup is None for r in rows)


def test_extract_logical_rows_detects_full_width_subgroup_row():
    cells = [
        TableCell(0, 0, "Item", kind="columnHeader"),
        TableCell(0, 1, "Limit", kind="columnHeader"),
        TableCell(1, 0, "(i) Beverages", column_span=2),
        TableCell(2, 0, "Cola"),
        TableCell(2, 1, "0.1"),
    ]
    table = Table(row_count=3, column_count=2, cells=cells, page_numbers=[1])
    grid = table_utils.resolve_grid(table)
    rows = table_utils.extract_logical_rows(grid, data_start_row=1)

    assert len(rows) == 1
    assert rows[0].subgroup == "(i) Beverages"
    assert rows[0].values == ["Cola", "0.1"]


def test_markdown_row_prefixes_subgroup_onto_label_column():
    row = table_utils.LogicalRow(values=["Cola", "0.1"], subgroup="(i) Beverages")
    assert table_utils.markdown_row(row) == "| ((i) Beverages) Cola | 0.1 |"


def _make_rows():
    return [
        table_utils.LogicalRow(values=["1", "A", "Fish", "0.2"]),
        table_utils.LogicalRow(values=["1", "A", "Foodgrains", "1.5"]),
        table_utils.LogicalRow(values=["2", "B", "Sugar beet", "0.3"]),
        table_utils.LogicalRow(values=["2", "B", "Wheat", "0.4"]),
    ]


def _chunk(rows, max_tokens):
    return table_utils.chunk_table_rows(
        rows,
        header_line="| Sl.No. | Name | Food | Limit |",
        intro_line="Table context: ...",
        breadcrumb_line="[Regulation] Doc › 2.3.1",
        max_tokens=max_tokens,
        group_key_fn=lambda r: r.values[1],
    )


def test_chunk_table_rows_never_loses_or_duplicates_rows():
    rows = _make_rows()
    # Budget tight enough to force a split, derived from actual token counts
    # so the test doesn't depend on tokenizer-specific magic numbers.
    three_row_tokens = table_utils.count_tokens(
        "\n".join(["[Regulation] Doc › 2.3.1", "Table context: ...", "| Sl.No. | Name | Food | Limit |"]
                   + [table_utils.markdown_row(r) for r in rows[:3]])
    )
    pieces = _chunk(rows, max_tokens=three_row_tokens)

    total_rows = sum(p.row_count for p in pieces)
    assert total_rows == 4
    for piece in pieces:
        for row in piece.rows:
            assert len(row.values) == 4


def test_detect_column_resolves_the_entity_column_on_a_regulation_shaped_header():
    header = ["Sl.No.", "Name of Insecticides", "Food", "Tolerance limit mg/kg (ppm)"]
    cols = table_utils.detect_column(header, REGULATION_SYNONYMS, REGULATION_KEYWORD_FALLBACKS)
    assert cols["entity"] == 1  # "Name of Insecticides" — not hardcoded index 1, resolved by content
    assert cols["food"] == 2
    assert cols["limit"] == 3


def test_detect_column_resolves_the_product_id_column_on_a_catalog_shaped_header():
    header = ["ID", "PRODUCT", "METHOD"]
    cols = table_utils.detect_column(header, CATALOG_SYNONYMS, CATALOG_KEYWORD_FALLBACKS)
    assert cols["product_id"] == 0
    assert cols["product"] == 1


def test_detect_column_returns_no_entry_when_nothing_matches_rather_than_guessing():
    header = ["Random Header A", "Random Header B"]
    cols = table_utils.detect_column(header, REGULATION_SYNONYMS, REGULATION_KEYWORD_FALLBACKS)
    assert cols == {}


def test_detect_column_would_resolve_a_column_a_hardcoded_index_gets_wrong():
    # The real regression this generalization fixes: a table whose entity
    # column is NOT at the previously-hardcoded index (1) still resolves
    # correctly via content, instead of silently reading the wrong column.
    header = ["Sl.No.", "Food", "Name of Insecticides", "Tolerance limit mg/kg (ppm)"]  # entity moved to index 2
    cols = table_utils.detect_column(header, REGULATION_SYNONYMS, REGULATION_KEYWORD_FALLBACKS)
    assert cols["entity"] == 2  # a hardcoded group_col_index=1 would have wrongly grouped by "Food" here


def test_rows_to_structured_renders_rows_as_dicts_with_page():
    rows = [
        table_utils.LogicalRow(values=["PT01.03", "Crustacean species"], page_number=4),
        table_utils.LogicalRow(values=["PT00.244", "Chestnut species"], page_number=4),
    ]
    structured = table_utils.rows_to_structured(rows, {"product_id": 0, "product": 1})
    assert structured == [
        {"product_id": "PT01.03", "product": "Crustacean species", "page": 4},
        {"product_id": "PT00.244", "product": "Chestnut species", "page": 4},
    ]


def test_chunk_table_rows_prefers_group_boundary_over_mid_group_split():
    rows = _make_rows()
    # Exactly enough budget for the first 3 rows (A, A, B) but not all 4 — the
    # naive "pack until it overflows" approach would put row 3 (first B) in the
    # same chunk as the two A rows, leaving the second B row split off alone.
    # The group-boundary-aware chunker should instead back off to the A/B
    # boundary, keeping both B rows together in their own chunk.
    header_breadcrumb_intro = ["[Regulation] Doc › 2.3.1", "Table context: ...", "| Sl.No. | Name | Food | Limit |"]
    three_row_tokens = table_utils.count_tokens(
        "\n".join(header_breadcrumb_intro + [table_utils.markdown_row(r) for r in rows[:3]])
    )
    pieces = _chunk(rows, max_tokens=three_row_tokens)

    assert sum(p.row_count for p in pieces) == 4
    group_b_rows = [r for p in pieces for r in p.rows if r.values[1] == "B"]
    assert len(group_b_rows) == 2
    # both B rows must land in the same piece
    piece_with_b = [p for p in pieces if any(r.values[1] == "B" for r in p.rows)]
    assert len(piece_with_b) == 1
    assert piece_with_b[0].row_count == 2
