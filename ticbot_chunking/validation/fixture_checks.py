"""Fixture-based edge-case checks.

Some of the 12 required checks (row splitting, rowspan carry-forward, NABL
grouping, brochure reading order, Excel block separation) can't be verified
by scanning arbitrary already-generated chunks.jsonl output — there's no
ground truth in plain chunk text to compare against. Instead, each check
here builds a small, known synthetic document (the same kind of fixture the
unit tests in ticbot_chunking/tests/ use), runs every strategy against it
fresh, and compares the actual output to a specific, known-correct expected
outcome — a real "Edge Case | Expected | Actual | Pass/Fail" comparison
rather than a heuristic guess.

Strategies that don't implement a given capability by design (e.g.
fixed/recursive have no NABL-grouping concept at all) are reported as such
rather than silently marked "N/A" — the point of this framework is to make
that difference visible, not to hide it.
"""
from __future__ import annotations

import re

from ticbot_chunking.experiments import fixed_size, hybrid, recursive, structure_aware
from ticbot_chunking.experiments.common import ParsedDoc, build_doc_metadata
from ticbot_chunking.metadata.schema import Chunk
from ticbot_chunking.parsers.ir import (
    BoundingBox,
    LayoutDocument,
    Page,
    Paragraph,
    ROLE_SECTION_HEADING,
    ROLE_TITLE,
    Table,
    TableCell,
)
from ticbot_chunking.validation.edge_cases import EdgeCaseResult

DEFAULT_CHUNK_SIZE = 400
DEFAULT_OVERLAP = 60
DEFAULT_MAX_CHUNK_SIZE = 700


def _bbox(page: int, x: float = 0.0, y: float = 0.0, width: float = 100.0, height: float = 10.0) -> BoundingBox:
    return BoundingBox(page_number=page, x=x, y=y, width=width, height=height)


def run_all_strategies_on_pdf(layout_doc: LayoutDocument, doc_type: str, chunk_size: int = DEFAULT_CHUNK_SIZE,
                               overlap: int = DEFAULT_OVERLAP, max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE
                               ) -> dict[str, list[Chunk]]:
    parsed = ParsedDoc(source_file=layout_doc.source_file, local_path=layout_doc.source_file, doc_type=doc_type,
                        kind="pdf", layout_doc=layout_doc)
    doc_meta = build_doc_metadata(parsed)
    return {
        "fixed": fixed_size.chunk_fixed_size(parsed, doc_meta, chunk_size, overlap, max_chunk_size),
        "recursive": recursive.chunk_recursive(parsed, doc_meta, chunk_size, overlap, max_chunk_size),
        "structure_aware": structure_aware.chunk_structure_aware(parsed, doc_meta, chunk_size, overlap, max_chunk_size),
        "hybrid": hybrid.chunk_hybrid(parsed),
    }


def run_all_strategies_on_excel(local_path: str, doc_type: str, chunk_size: int = DEFAULT_CHUNK_SIZE,
                                 overlap: int = DEFAULT_OVERLAP, max_chunk_size: int = DEFAULT_MAX_CHUNK_SIZE
                                 ) -> dict[str, list[Chunk]]:
    parsed = ParsedDoc(source_file=local_path.split("/")[-1], local_path=local_path, doc_type=doc_type, kind="excel")
    doc_meta = build_doc_metadata(parsed)
    return {
        "fixed": fixed_size.chunk_fixed_size(parsed, doc_meta, chunk_size, overlap, max_chunk_size),
        "recursive": recursive.chunk_recursive(parsed, doc_meta, chunk_size, overlap, max_chunk_size),
        "structure_aware": structure_aware.chunk_structure_aware(parsed, doc_meta, chunk_size, overlap, max_chunk_size),
        "hybrid": hybrid.chunk_hybrid(parsed),
    }


# ---------------------------------------------------------------------------
# #1 Table rows being split
# ---------------------------------------------------------------------------

def _build_split_table_fixture() -> LayoutDocument:
    n_rows = 15
    paragraphs = [
        Paragraph("Test Regulation", role=ROLE_TITLE, bounding_boxes=[_bbox(1)]),
        Paragraph("CHAPTER 1 – Limits", role=ROLE_SECTION_HEADING, bounding_boxes=[_bbox(1)]),
        Paragraph("The table below lists per-item limits.", bounding_boxes=[_bbox(1)]),
    ]
    cells = [
        TableCell(0, 0, "Name", kind="columnHeader"),
        TableCell(0, 1, "Note", kind="columnHeader"),
    ]
    for i in range(1, n_rows + 1):
        # Varied-length padding (not a uniform repeat) so a fixed token
        # window is very likely to land mid-row somewhere across 15 rows,
        # the same technique used in the experiment framework's own tests.
        padding = " ".join(f"detail{j}" for j in range(1, (i % 9) + 4))
        cells.append(TableCell(i, 0, f"Marker{i:03d}", page_number=1))
        cells.append(TableCell(i, 1, padding, page_number=1))
    table = Table(row_count=n_rows + 1, column_count=2, cells=cells, page_numbers=[1], preceding_paragraph_index=2)
    return LayoutDocument(source_file="split_table_fixture.pdf", pages=[Page(1)], paragraphs=paragraphs,
                           tables=[table])


def check_table_rows_not_split() -> list[EdgeCaseResult]:
    doc = _build_split_table_fixture()
    expected_markers = {f"Marker{i:03d}" for i in range(1, 16)}
    # Deliberately tight budget so fixed-size's raw token windows are likely
    # to land inside a row's own token span at least once.
    results = run_all_strategies_on_pdf(doc, doc_type="regulation", chunk_size=25, overlap=5, max_chunk_size=25)

    rows = []
    for strategy, chunks in results.items():
        combined = "\n".join(c.text for c in chunks)
        found = set(re.findall(r"Marker\d{3}", combined))
        missing_or_corrupted = expected_markers - found
        rows.append(EdgeCaseResult(
            edge_case="Table rows being split",
            strategy=strategy,
            expected=f"All {len(expected_markers)} row markers appear intact, none truncated",
            actual=f"{len(found & expected_markers)}/{len(expected_markers)} intact"
                   + (f"; corrupted/missing: {sorted(missing_or_corrupted)}" if missing_or_corrupted else ""),
            passed=len(missing_or_corrupted) == 0,
        ))
    return rows


# ---------------------------------------------------------------------------
# #3 Rowspan / merged-label carry-forward
# ---------------------------------------------------------------------------

def _build_rowspan_fixture() -> LayoutDocument:
    paragraphs = [
        Paragraph("Test Regulation", role=ROLE_TITLE, bounding_boxes=[_bbox(1)]),
        Paragraph("CHAPTER 1 – Limits", role=ROLE_SECTION_HEADING, bounding_boxes=[_bbox(1)]),
        Paragraph("Tolerance limits by food.", bounding_boxes=[_bbox(1)]),
    ]
    cells = [
        TableCell(0, 0, "Insecticide", kind="columnHeader"),
        TableCell(0, 1, "Food", kind="columnHeader"),
        TableCell(0, 2, "Limit", kind="columnHeader"),
        TableCell(1, 0, "Carbaryl", row_span=3, page_number=1),  # printed once, spans 3 rows
        TableCell(1, 1, "Fish", page_number=1), TableCell(1, 2, "0.2", page_number=1),
        TableCell(2, 1, "Foodgrains", page_number=1), TableCell(2, 2, "1.5", page_number=1),
        TableCell(3, 1, "Okra", page_number=1), TableCell(3, 2, "10.0", page_number=1),
    ]
    table = Table(row_count=4, column_count=3, cells=cells, page_numbers=[1], preceding_paragraph_index=2)
    return LayoutDocument(source_file="rowspan_fixture.pdf", pages=[Page(1)], paragraphs=paragraphs, tables=[table])


def check_rowspan_carry_forward() -> list[EdgeCaseResult]:
    doc = _build_rowspan_fixture()
    results = run_all_strategies_on_pdf(doc, doc_type="regulation")

    rows = []
    for strategy, chunks in results.items():
        combined = "\n".join(c.text for c in chunks)
        # "Carbaryl" must appear alongside each of the three foods it
        # implicitly covers, not just once next to "Fish".
        carried = all(food in combined and combined.count("Carbaryl") >= 1 for food in ("Fish", "Foodgrains", "Okra"))
        carbaryl_count = combined.count("Carbaryl")
        rows.append(EdgeCaseResult(
            edge_case="Rowspan/merged-label carry-forward",
            strategy=strategy,
            expected="'Carbaryl' is present for all 3 rows it applies to (Fish, Foodgrains, Okra)",
            actual=f"'Carbaryl' appears {carbaryl_count}x; foods present: "
                   + ", ".join(f for f in ("Fish", "Foodgrains", "Okra") if f in combined),
            passed=carried and carbaryl_count >= 3,
        ))
    return rows


# ---------------------------------------------------------------------------
# #7 NABL discipline/material grouping
# ---------------------------------------------------------------------------

def _build_nabl_two_group_fixture() -> LayoutDocument:
    cells = [
        TableCell(0, 0, "S.No", kind="columnHeader"),
        TableCell(0, 1, "Discipline/Group", kind="columnHeader"),
        TableCell(0, 2, "Material/Product", kind="columnHeader"),
        TableCell(0, 3, "Parameter", kind="columnHeader"),
        TableCell(0, 4, "Method", kind="columnHeader"),
        TableCell(1, 0, "1"), TableCell(1, 1, "CHEMICAL"), TableCell(1, 2, "Spices"),
        TableCell(1, 3, "Moisture"), TableCell(1, 4, "AOAC 925.10"),
        TableCell(2, 0, "2"), TableCell(2, 1, "CHEMICAL"), TableCell(2, 2, "Spices"),
        TableCell(2, 3, "Total Ash"), TableCell(2, 4, "AOAC 923.03"),
        TableCell(3, 0, "3"), TableCell(3, 1, "BIOLOGICAL"), TableCell(3, 2, "Fish"),
        TableCell(3, 3, "E. coli"), TableCell(3, 4, "ISO 7251"),
        TableCell(4, 0, "4"), TableCell(4, 1, "BIOLOGICAL"), TableCell(4, 2, "Fish"),
        TableCell(4, 3, "Salmonella"), TableCell(4, 4, "ISO 6579"),
    ]
    table = Table(row_count=5, column_count=5, cells=cells, page_numbers=[3])
    return LayoutDocument(source_file="nabl_two_group_fixture.pdf", pages=[Page(3)], paragraphs=[], tables=[table])


def check_nabl_discipline_material_grouping() -> list[EdgeCaseResult]:
    doc = _build_nabl_two_group_fixture()
    results = run_all_strategies_on_pdf(doc, doc_type="accreditation_scope")

    rows = []
    for strategy, chunks in results.items():
        if strategy != "hybrid":
            # Only the hybrid strategy has NABL-specific grouping logic —
            # the others have no discipline/material concept at all.
            rows.append(EdgeCaseResult(
                edge_case="Incorrect NABL discipline/material grouping",
                strategy=strategy,
                expected="N/A — only the hybrid strategy implements NABL-specific grouping",
                actual="no discipline/material metadata produced (expected, by design)",
                passed=None,
            ))
            continue

        scope_chunks = [c for c in chunks if c.metadata.chunk_type == "scope_records"]
        chemical_chunks = [c for c in scope_chunks if c.metadata.discipline == "CHEMICAL"]
        biological_chunks = [c for c in scope_chunks if c.metadata.discipline == "BIOLOGICAL"]
        no_cross_contamination = all("E. coli" not in c.text and "Salmonella" not in c.text for c in chemical_chunks) \
            and all("Moisture" not in c.text and "Total Ash" not in c.text for c in biological_chunks)
        rows.append(EdgeCaseResult(
            edge_case="Incorrect NABL discipline/material grouping",
            strategy=strategy,
            expected="CHEMICAL/Spices and BIOLOGICAL/Fish records are grouped into separate chunks, never mixed",
            actual=f"{len(chemical_chunks)} CHEMICAL chunk(s), {len(biological_chunks)} BIOLOGICAL chunk(s), "
                   f"cross-contamination={'no' if no_cross_contamination else 'YES'}",
            passed=bool(chemical_chunks) and bool(biological_chunks) and no_cross_contamination,
        ))
    return rows


# ---------------------------------------------------------------------------
# #8 Brochure reading order
# ---------------------------------------------------------------------------

def _build_two_column_brochure_fixture(with_title: bool) -> LayoutDocument:
    paragraphs = []
    if with_title:
        # A full-width title above two narrower columns — realistic (this
        # is exactly how the real SGS Molecular Catalog sample is laid
        # out), but a harder case: a wide box can overlap both columns.
        paragraphs.append(Paragraph("Test Catalog", role=ROLE_TITLE, bounding_boxes=[_bbox(1, x=0, width=100)]))
    paragraphs += [
        Paragraph("Left A", bounding_boxes=[_bbox(1, x=0, y=0, width=40)]),
        Paragraph("Right A", bounding_boxes=[_bbox(1, x=50, y=5, width=40)]),
        Paragraph("Left B", bounding_boxes=[_bbox(1, x=0, y=20, width=40)]),
        Paragraph("Right B", bounding_boxes=[_bbox(1, x=50, y=25, width=40)]),
    ]
    return LayoutDocument(source_file="two_column_fixture.pdf", pages=[Page(1)], paragraphs=paragraphs, tables=[])


def _check_reading_order_scenario(edge_case: str, with_title: bool) -> list[EdgeCaseResult]:
    doc = _build_two_column_brochure_fixture(with_title=with_title)
    results = run_all_strategies_on_pdf(doc, doc_type="brochure")

    rows = []
    for strategy, chunks in results.items():
        combined = "\n".join(c.text for c in chunks)
        positions = {label: combined.find(label) for label in ("Left A", "Left B", "Right A", "Right B")}
        found_all = all(p != -1 for p in positions.values())
        column_correct_order = found_all and positions["Left A"] < positions["Left B"] < positions["Right A"] < positions["Right B"]
        actual = (
            (("column-correct" if column_correct_order else "interleaved/incorrect") + f" — positions: {positions}")
            if found_all else "one or more paragraphs missing from output"
        )
        rows.append(EdgeCaseResult(
            edge_case=edge_case,
            strategy=strategy,
            expected="Column-correct order: Left A, Left B, Right A, Right B (not interleaved Left A, Right A, Left B, Right B)",
            actual=actual,
            passed=column_correct_order,
        ))
    return rows


def check_brochure_reading_order() -> list[EdgeCaseResult]:
    # Two scenarios, reported separately: a clean two-column body in
    # isolation, and the more realistic case of a full-width title sitting
    # above it. These can (and, as found below, do) behave differently —
    # `fix_reading_order` buckets paragraphs into columns using the first
    # item placed in each column as that column's reference box, so a
    # full-width title placed first can make later, narrower items on both
    # the real left and right columns register as "overlapping" it and get
    # merged into a single column, corrupting the order. Reported as a
    # found issue, not fixed here — this step is evaluation only.
    return (
        _check_reading_order_scenario("Brochure reading order — clean 2-column body", with_title=False)
        + _check_reading_order_scenario("Brochure reading order — full-width title above 2-column body", with_title=True)
    )


# ---------------------------------------------------------------------------
# #9 Excel block separation
# ---------------------------------------------------------------------------

def _build_two_block_workbook(tmp_dir) -> str:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Category", "Count"])
    ws.append(["Quality Manager", 3])
    ws.append(["Lab Head", 2])
    ws.append([])  # blank row separates the two blocks
    ws.append(["Total contacts", 21])
    path = str(tmp_dir / "two_block_fixture.xlsx")
    wb.save(path)
    return path


def check_excel_block_separation(tmp_dir) -> list[EdgeCaseResult]:
    path = _build_two_block_workbook(tmp_dir)
    results = run_all_strategies_on_excel(path, doc_type="reference_register")

    rows = []
    for strategy, chunks in results.items():
        # Content-based, not cell_range-string-based: different strategies
        # use different (each internally valid) cell_range conventions —
        # e.g. structure-aware's ranges cover only data rows, excluding the
        # header row that hybrid's whole-block ranges include — so the
        # correctness signal that generalizes across strategies is whether
        # the two blocks' *content* stays separate, not an exact range.
        block1_present = any("Quality Manager" in c.text and "Lab Head" in c.text for c in chunks)
        block2_present = any("Total contacts" in c.text for c in chunks)
        merged = any(
            ("Total contacts" in c.text) and ("Quality Manager" in c.text or "Lab Head" in c.text) for c in chunks
        )
        rows.append(EdgeCaseResult(
            edge_case="Incorrect Excel block separation",
            strategy=strategy,
            expected="Both blocks present, each in its own chunk, never merged together",
            actual=f"block1 present={block1_present}, block2 present={block2_present}, merged into one chunk={merged}",
            passed=(block1_present and block2_present and not merged),
        ))
    return rows


def run_all_fixture_checks(tmp_dir) -> list[EdgeCaseResult]:
    results: list[EdgeCaseResult] = []
    results.extend(check_table_rows_not_split())
    results.extend(check_rowspan_carry_forward())
    results.extend(check_nabl_discipline_material_grouping())
    results.extend(check_brochure_reading_order())
    results.extend(check_excel_block_separation(tmp_dir))
    return results
