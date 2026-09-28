"""Block-aware chunking for Excel workbooks.

Implements the "Excel" row of section 1 and section 6.1/6.5 of
TICbot_Chunking_Strategy_Answers.md: every table or list on a sheet is
detected separately (via defined Excel Tables where they exist, else
blank-row/blank-column boundaries), and each block type is written out in
its own format.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

from ticbot_chunking.chunkers.text_utils import MIN_CONTENT_TOKENS
from ticbot_chunking.config import EXCEL_BLOCK
from ticbot_chunking.metadata.schema import Chunk, ChunkMetadata, DocumentMetadata
from ticbot_chunking.tokenizer import count_tokens

NUMBERED_ITEM_RE = re.compile(r"^\s*\d+[.)]\s+")
LABEL_COLON_RE = re.compile(r".+:\s*$")


def _cell_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _is_blank_row(ws: Worksheet, row: int, min_col: int, max_col: int) -> bool:
    return all(_cell_text(ws.cell(row=row, column=c).value) == "" for c in range(min_col, max_col + 1))


def _is_blank_col(ws: Worksheet, col: int, min_row: int, max_row: int) -> bool:
    return all(_cell_text(ws.cell(row=r, column=col).value) == "" for r in range(min_row, max_row + 1))


@dataclass
class Block:
    min_row: int
    max_row: int
    min_col: int
    max_col: int
    grid: list[list[str]]
    has_formula: bool
    name: str | None = None  # defined Excel Table name, if any

    @property
    def cell_range(self) -> str:
        return f"{get_column_letter(self.min_col)}{self.min_row}:{get_column_letter(self.max_col)}{self.max_row}"


def _extract_block(ws: Worksheet, min_row: int, max_row: int, min_col: int, max_col: int,
                    formula_ws: Worksheet | None, name: str | None = None) -> Block:
    grid = []
    has_formula = False
    for r in range(min_row, max_row + 1):
        row_vals = []
        for c in range(min_col, max_col + 1):
            row_vals.append(_cell_text(ws.cell(row=r, column=c).value))
            if formula_ws is not None:
                fcell = formula_ws.cell(row=r, column=c)
                if isinstance(fcell.value, str) and fcell.value.startswith("="):
                    has_formula = True
        grid.append(row_vals)
    return Block(min_row, max_row, min_col, max_col, grid, has_formula, name)


def detect_blocks(ws: Worksheet, formula_ws: Worksheet | None, skip_ranges: list[tuple[int, int, int, int]]) -> list[Block]:
    """Blank-row/blank-column boundary detection, skipping any cell ranges
    already claimed by a defined Excel Table."""
    max_row, max_col = ws.max_row or 0, ws.max_column or 0
    if max_row == 0 or max_col == 0:
        return []

    def in_skip(r: int, c: int) -> bool:
        return any(sr0 <= r <= sr1 and sc0 <= c <= sc1 for sr0, sc0, sr1, sc1 in skip_ranges)

    row_bands: list[tuple[int, int]] = []
    start = None
    for r in range(1, max_row + 1):
        blank = all(
            _cell_text(ws.cell(row=r, column=c).value) == "" or in_skip(r, c)
            for c in range(1, max_col + 1)
        )
        if not blank and start is None:
            start = r
        if blank and start is not None:
            row_bands.append((start, r - 1))
            start = None
    if start is not None:
        row_bands.append((start, max_row))

    blocks: list[Block] = []
    for r0, r1 in row_bands:
        col_bands: list[tuple[int, int]] = []
        start_c = None
        for c in range(1, max_col + 1):
            blank = all(
                _cell_text(ws.cell(row=r, column=c).value) == "" or in_skip(r, c)
                for r in range(r0, r1 + 1)
            )
            if not blank and start_c is None:
                start_c = c
            if blank and start_c is not None:
                col_bands.append((start_c, c - 1))
                start_c = None
        if start_c is not None:
            col_bands.append((start_c, max_col))

        for c0, c1 in col_bands:
            if any(in_skip(r, c) for r in range(r0, r1 + 1) for c in (c0, c1)):
                continue
            blocks.append(_extract_block(ws, r0, r1, c0, c1, formula_ws))
    return blocks


def classify_block(block: Block) -> str:
    """record_table | column_lists | numbered_list | sheet_kv"""
    grid = block.grid
    n_rows = len(grid)
    n_cols = len(grid[0]) if grid else 0

    if n_cols == 1:
        return "numbered_list"

    header = grid[0] if grid else []
    if header and all(LABEL_COLON_RE.match(h) for h in header if h):
        return "column_lists"

    if n_cols == 2 and n_rows <= 12:
        second_col_short = all(len(row[1]) < 40 for row in grid[1:])
        if second_col_short:
            return "sheet_kv"

    return "record_table"


def format_record_table(block: Block) -> str:
    header = block.grid[0]
    lines = [f"Columns: {' | '.join(header)}"]
    for i, row in enumerate(block.grid[1:], start=1):
        row_num = block.min_row + i
        pairs = " | ".join(f"{h}: {v}" for h, v in zip(header, row) if v)
        lines.append(f"Row {row_num} — {pairs}")
    return "\n".join(lines)


def format_column_lists(block: Block) -> str:
    header = block.grid[0]
    lines = ["(Independent lists — items in the same row are not related)"]
    for col_idx, label in enumerate(header):
        items = [row[col_idx] for row in block.grid[1:] if col_idx < len(row) and row[col_idx]]
        if items:
            lines.append(f"{label} {'; '.join(items)}")
    return "\n".join(lines)


def format_numbered_list(block: Block) -> str:
    items = [row[0] for row in block.grid if row and row[0]]
    return "\n".join(items)


def format_kv(block: Block) -> str:
    return "\n".join(f"{row[0]}: {row[1]}" for row in block.grid if row[0] or (len(row) > 1 and row[1]))


FORMATTERS = {
    "record_table": format_record_table,
    "column_lists": format_column_lists,
    "numbered_list": format_numbered_list,
    "sheet_kv": format_kv,
}


# Header names seen for an explicit per-row access-classification column
# (e.g. the "Licensed References" sheet's "Access Classification" column,
# with values like "Licensed" for full ISO/AOAC/ASTM/AOCS standard text —
# section 7's access-control rule, applied here from the source data itself
# rather than guessed from a sheet name).
ACCESS_CLASS_HEADERS = {"access classification", "access class", "access type"}
ACCESS_CLASS_VALUES = {"public": "public", "internal": "internal", "licensed": "licensed", "restricted": "internal"}


def _access_class_for_rows(header: list[str], rows: list[list[str]], default: str) -> str:
    """If every row shares the same value in a recognized access-classification
    column, use it; otherwise fall back to `default` (mixed or absent)."""
    for idx, h in enumerate(header):
        if h.strip().lower() not in ACCESS_CLASS_HEADERS:
            continue
        values = {row[idx].strip().lower() for row in rows if idx < len(row) and row[idx].strip()}
        if len(values) == 1:
            return ACCESS_CLASS_VALUES.get(values.pop(), default)
    return default


def _block_title(ws_name: str, block: Block, workbook_title: str, block_title: str | None) -> str:
    parts = [workbook_title, f"Sheet: {ws_name}"]
    if block_title:
        parts.append(block_title)
    return " › ".join(parts)


def chunk_excel_block(
    block: Block, ws_name: str, workbook_title: str, doc_meta: DocumentMetadata,
    block_title: str | None = None,
) -> list[Chunk]:
    if len(block.grid) == 1:
        # A lone row isolated by blank rows/columns (e.g. a single
        # "Total contacts: 21" summary line) has no separate header row.
        # Every classify_block/formatter path below assumes grid[0] is a
        # header and data starts at grid[1:] — for a single-row block that
        # reads the row's own values as a fake "Columns:" header and loses
        # its content entirely. Emit it directly as one data row instead.
        row_text = " | ".join(v for v in block.grid[0] if v)
        if count_tokens(row_text) < MIN_CONTENT_TOKENS:
            return []
        path = _block_title(ws_name, block, workbook_title, block_title)
        header_line = f"[{doc_meta.doc_type.replace('_', ' ').title()}] {path}"
        text = f"{header_line}\n{row_text}"
        meta = ChunkMetadata(
            chunk_type="sheet_table", doc_type=doc_meta.doc_type, source_file=doc_meta.source_file,
            tokens=count_tokens(text), sheet=ws_name, cell_range=block.cell_range, excel_table=block.name,
            row_count=1, access_class=doc_meta.access_class, contains_pii=doc_meta.contains_pii,
            quality_flags=["computed_values"] if block.has_formula else None,
        )
        return [Chunk(text=text, metadata=meta)]

    block_type = classify_block(block) if not block.name else "record_table"
    formatter = FORMATTERS[block_type]
    body = formatter(block)
    if count_tokens(body) < MIN_CONTENT_TOKENS:
        return []

    path = _block_title(ws_name, block, workbook_title, block_title)
    header_line = f"[{doc_meta.doc_type.replace('_', ' ').title()}] {path}"
    text = f"{header_line}\n{body}"

    chunk_type_map = {
        "record_table": "sheet_table",
        "column_lists": "sheet_lists",
        "numbered_list": "sheet_lists",
        "sheet_kv": "sheet_kv",
    }

    quality_flags = ["computed_values"] if block.has_formula else None
    access_class = _access_class_for_rows(block.grid[0] if block.grid else [], block.grid[1:], doc_meta.access_class)

    meta = ChunkMetadata(
        chunk_type=chunk_type_map[block_type],
        doc_type=doc_meta.doc_type,
        source_file=doc_meta.source_file,
        tokens=count_tokens(text),
        sheet=ws_name,
        cell_range=block.cell_range,
        excel_table=block.name,
        access_class=access_class,
        contains_pii=doc_meta.contains_pii,
        quality_flags=quality_flags,
    )

    if meta.tokens <= EXCEL_BLOCK.max_tokens:
        return [Chunk(text=text, metadata=meta)]

    # Split an oversized block row-by-row, respecting row integrity, same as
    # narrative-table chunking elsewhere. Each LogicalRow's true sheet row
    # number is tracked by object identity (chunk_table_rows only ever
    # slices/reorders the same row objects, never copies them) so that each
    # split piece can report its own exact cell_range and each formatted
    # "Row N" label reflects the real sheet row — not the original block's
    # first row repeated on every piece.
    from ticbot_chunking.chunkers import table_utils

    logical_rows = [table_utils.LogicalRow(values=row) for row in block.grid[1:]]
    sheet_row_by_id = {id(lr): block.min_row + 1 + i for i, lr in enumerate(logical_rows)}

    def _row_text(r: table_utils.LogicalRow) -> str:
        true_row = sheet_row_by_id[id(r)]
        mini_block = Block(true_row - 1, block.max_row, block.min_col, block.max_col,
                            [block.grid[0], r.values], block.has_formula, block.name)
        return formatter(mini_block).splitlines()[-1]

    header_line_only = table_utils.markdown_header(block.grid[0]) if block.grid else ""
    pieces = table_utils.chunk_table_rows(
        logical_rows,
        header_line=header_line_only,
        intro_line="",
        breadcrumb_line=header_line,
        max_tokens=EXCEL_BLOCK.max_tokens,
        group_key_fn=lambda r: None,
        row_formatter=_row_text,
    )
    chunks = []
    for piece in pieces:
        if count_tokens(piece.body_text) < MIN_CONTENT_TOKENS:
            continue
        piece_rows = [sheet_row_by_id[id(r)] for r in piece.rows]
        piece_cell_range = (
            f"{get_column_letter(block.min_col)}{min(piece_rows)}:"
            f"{get_column_letter(block.max_col)}{max(piece_rows)}"
        )
        piece_access_class = _access_class_for_rows(
            block.grid[0] if block.grid else [], [r.values for r in piece.rows], doc_meta.access_class
        )
        piece_meta = ChunkMetadata(
            chunk_type=chunk_type_map[block_type], doc_type=doc_meta.doc_type, source_file=doc_meta.source_file,
            tokens=count_tokens(piece.body_text), sheet=ws_name, cell_range=piece_cell_range,
            excel_table=block.name, row_count=piece.row_count, access_class=piece_access_class,
            contains_pii=doc_meta.contains_pii, quality_flags=quality_flags,
        )
        chunks.append(Chunk(text=piece.body_text, metadata=piece_meta))
    return chunks


def _resolve_ref_values(formula: str | None, wb) -> list[str]:
    """Resolve a chart series numRef/strRef formula like "'Sheet1'!$B$2:$B$5"
    into the list of cell values it points to."""
    if not formula:
        return []
    m = re.match(r"^'?([^'!]+)'?!(.+)$", formula)
    if not m:
        return []
    sheet_name, ref = m.groups()
    if sheet_name not in wb.sheetnames:
        return []
    ws = wb[sheet_name]
    min_col, min_row, max_col, max_row = range_boundaries(ref.replace("$", ""))
    values = []
    for r in range(min_row, max_row + 1):
        for c in range(min_col, max_col + 1):
            values.append(_cell_text(ws.cell(row=r, column=c).value))
    return values


def chunk_excel_charts(ws: Worksheet, wb, ws_name: str, workbook_title: str, doc_meta: DocumentMetadata) -> list[Chunk]:
    chunks = []
    for chart in getattr(ws, "_charts", []):
        try:
            title = None
            if chart.title and chart.title.tx and chart.title.tx.rich:
                title = "".join(
                    run.t for p in chart.title.tx.rich.p for run in (p.r or []) if run.t
                )
            series_lines = []
            for series in chart.series:
                cats = _resolve_ref_values(getattr(series.cat, "numRef", None) and series.cat.numRef.f
                                            or getattr(series.cat, "strRef", None) and series.cat.strRef.f, wb)
                vals = _resolve_ref_values(getattr(series.val, "numRef", None) and series.val.numRef.f, wb)
                pairs = [f"{c} {v}" for c, v in zip(cats, vals)]
                if pairs:
                    series_lines.append("; ".join(pairs))
            if not series_lines:
                continue
            chart_title = title or "Chart"
            body = f"{chart_title}: {'; '.join(series_lines)}"
            path = f"{workbook_title} › Sheet: {ws_name} › {chart_title}"
            text = f"[{doc_meta.doc_type.replace('_', ' ').title()}] {path}\n{body}"
            meta = ChunkMetadata(
                chunk_type="sheet_chart", doc_type=doc_meta.doc_type, source_file=doc_meta.source_file,
                tokens=count_tokens(text), sheet=ws_name, access_class=doc_meta.access_class,
            )
            chunks.append(Chunk(text=text, metadata=meta))
        except Exception:
            continue
    return chunks


def chunk_workbook(path: str, doc_meta: DocumentMetadata, workbook_title: str) -> list[Chunk]:
    wb = load_workbook(path, data_only=True)
    formula_wb = load_workbook(path, data_only=False)

    chunks: list[Chunk] = []
    for ws_name in wb.sheetnames:
        ws = wb[ws_name]
        formula_ws = formula_wb[ws_name]

        defined_ranges: list[tuple[int, int, int, int]] = []
        for table_name, table_range in getattr(ws, "tables", {}).items():
            min_col, min_row, max_col, max_row = range_boundaries(table_range)
            defined_ranges.append((min_row, min_col, max_row, max_col))
            block = _extract_block(ws, min_row, max_row, min_col, max_col, formula_ws, name=table_name)
            chunks.extend(chunk_excel_block(block, ws_name, workbook_title, doc_meta, block_title=table_name))

        for block in detect_blocks(ws, formula_ws, defined_ranges):
            chunks.extend(chunk_excel_block(block, ws_name, workbook_title, doc_meta))

        chunks.extend(chunk_excel_charts(ws, wb, ws_name, workbook_title, doc_meta))

    return chunks
