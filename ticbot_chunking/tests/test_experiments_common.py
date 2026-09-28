from ticbot_chunking.experiments.common import (
    UnitRef,
    aggregate_refs,
    build_token_stream,
    discover_input_files,
    pdf_units_with_tables,
    refs_in_range,
    sliding_windows,
)
from ticbot_chunking.parsers.ir import (
    BoundingBox,
    LayoutDocument,
    Page,
    Paragraph,
    ROLE_PAGE_HEADER,
    ROLE_TITLE,
    Table,
    TableCell,
)


def test_build_token_stream_segments_cover_the_whole_stream_in_order():
    units = [("First unit.", UnitRef(pages=[1])), ("Second unit is here.", UnitRef(pages=[2]))]
    stream = build_token_stream(units)

    assert stream.segments[0].start == 0
    assert stream.segments[0].end == stream.segments[1].start
    assert stream.segments[-1].end == len(stream.ids)


def test_refs_in_range_finds_only_overlapping_segments():
    units = [("Alpha.", UnitRef(pages=[1])), ("Beta.", UnitRef(pages=[2])), ("Gamma.", UnitRef(pages=[3]))]
    stream = build_token_stream(units)

    # A window covering only the first segment's token range.
    seg0_end = stream.segments[0].end
    refs = refs_in_range(stream, 0, seg0_end)
    assert [r.pages for r in refs] == [[1]]

    # A window spanning segments 0 and 1 but not 2.
    refs = refs_in_range(stream, 0, stream.segments[1].end - 1)
    assert [r.pages for r in refs] == [[1], [2]]


def test_sliding_windows_covers_everything_with_requested_overlap():
    windows = list(sliding_windows(n_tokens=25, window=10, overlap=3))

    assert windows[0] == (0, 10)
    # each subsequent window starts (window - overlap) tokens after the previous start
    for (s0, e0), (s1, e1) in zip(windows, windows[1:]):
        assert s1 == s0 + (10 - 3)
    assert windows[-1][1] == 25  # covers to the end
    # every token index is covered by at least one window
    covered = set()
    for s, e in windows:
        covered.update(range(s, e))
    assert covered == set(range(25))


def test_sliding_windows_handles_content_smaller_than_one_window():
    windows = list(sliding_windows(n_tokens=5, window=10, overlap=2))
    assert windows == [(0, 5)]


def test_aggregate_refs_unions_pages_and_computes_sheet_cell_range():
    refs = [UnitRef(pages=[5]), UnitRef(pages=[5, 6]), UnitRef(pages=[7])]
    agg = aggregate_refs(refs)
    assert agg["pages"] == [5, 6, 7]
    assert agg["sheet"] is None
    assert agg["cell_range"] is None

    excel_refs = [UnitRef(sheet="Sheet1", row=3, max_col=4), UnitRef(sheet="Sheet1", row=5, max_col=4)]
    agg = aggregate_refs(excel_refs)
    assert agg["sheet"] == "Sheet1"
    assert agg["cell_range"] == "A3:D5"


def test_aggregate_refs_drops_sheet_when_refs_span_multiple_sheets():
    refs = [UnitRef(sheet="Sheet1", row=1, max_col=2), UnitRef(sheet="Sheet2", row=1, max_col=2)]
    agg = aggregate_refs(refs)
    assert agg["sheet"] is None


def test_pdf_units_with_tables_attaches_table_despite_earlier_stripped_paragraphs():
    # Regression test: `preceding_paragraph_index` (set by azure_docintel.py)
    # is an index into the FULL, unfiltered paragraph list. A title and a
    # page header appear before the table's real preceding paragraph here —
    # if those were stripped out before indices were computed (as an
    # earlier version of this code did), the table would attach to the
    # wrong paragraph, or be lost/misplaced entirely.
    paragraphs = [
        Paragraph("Doc Title", role=ROLE_TITLE, bounding_boxes=[BoundingBox(1)]),      # index 0 — stripped
        Paragraph("Page 1 of 5", role=ROLE_PAGE_HEADER, bounding_boxes=[BoundingBox(1)]),  # index 1 — stripped
        Paragraph("The table below lists tolerance limits.", bounding_boxes=[BoundingBox(1)]),  # index 2 — kept
    ]
    cells = [
        TableCell(0, 0, "Name", kind="columnHeader"), TableCell(0, 1, "Limit", kind="columnHeader"),
        TableCell(1, 0, "Carbaryl", page_number=1), TableCell(1, 1, "0.2", page_number=1),
    ]
    table = Table(row_count=2, column_count=2, cells=cells, page_numbers=[1], preceding_paragraph_index=2)
    doc = LayoutDocument(source_file="regs.pdf", pages=[Page(1)], paragraphs=paragraphs, tables=[table])

    units = pdf_units_with_tables(doc)
    texts = [t for t, _ in units]

    assert texts == [
        "The table below lists tolerance limits.",
        "Name: Carbaryl | Limit: 0.2",
    ]
    # the table row's page comes through correctly too
    assert units[-1][1].pages == [1]


def test_discover_input_files_is_recursive_and_filters_by_extension(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.pdf").write_bytes(b"x")
    (tmp_path / "sub" / "b.xlsx").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    (tmp_path / "sub" / ".~lock.b.xlsx#").write_bytes(b"x")

    found = {p.name for p in discover_input_files(str(tmp_path))}
    assert found == {"a.pdf", "b.xlsx"}
