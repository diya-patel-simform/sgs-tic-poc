"""Shared table handling: rowspan resolution, sub-group label carry-forward,
row-integrity-preserving chunking, and markdown row formatting.

Implements section 6 of TICbot_Chunking_Strategy_Answers.md:
- a row is never split across chunks
- rowspan labels (e.g. an insecticide name printed once for several rows)
  are carried onto every row they apply to
- full-width sub-group label rows (e.g. "(i) Beverages") are attached to the
  rows they cover, not emitted as their own row
- chunks prefer to break at group boundaries rather than mid-group
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ticbot_chunking.parsers.ir import Table
from ticbot_chunking.tokenizer import count_tokens

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_header_cell(cell: str) -> str:
    """Collapses embedded newlines/runs of whitespace (real multi-line PDF
    table headers wrap mid-phrase) to single spaces, so header text differing
    only in line-wrapping or spacing still matches."""
    return _WHITESPACE_RE.sub(" ", cell.strip().lower())


def detect_column(
    header: list[str], synonyms: dict[str, str], keyword_fallbacks: list[tuple[str, str]]
) -> dict[str, int]:
    """Generic column-role detection: exact-match against `synonyms` first
    (a normalized header cell -> canonical role name), then a keyword-in-text
    fallback via `keyword_fallbacks` (checked in priority order) for real
    headers whose phrasing doesn't exactly match any synonym. Originally
    `nabl_scope._canonical_columns`'s two-pass logic — generalized here so
    every chunker resolves "which column is the grouping/entity column"
    the same, content-driven way instead of a hardcoded column index.
    Returns {canonical_role: column_index}; a role with no match is simply
    absent from the result, never guessed."""
    mapping: dict[str, int] = {}
    normalized = [_normalize_header_cell(col) for col in header]

    for i, norm in enumerate(normalized):
        canonical = synonyms.get(norm)
        if canonical and canonical not in mapping:
            mapping[canonical] = i

    for i, norm in enumerate(normalized):
        for keyword, canonical in keyword_fallbacks:
            if canonical in mapping:
                continue
            if keyword in norm:
                mapping[canonical] = i
                break

    return mapping


def rows_to_structured(rows: Iterable[LogicalRow], column_map: dict[str, int]) -> list[dict[str, Any]]:
    """Renders each row as a plain dict keyed by the caller's own canonical
    column names (from `detect_column`), plus `page` — the "structured
    data" a chunk's table rows are also stored as (alongside the rendered
    markdown body text), so the UI can build a real table from data instead
    of asking the LLM to regenerate one from prose."""
    structured: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = {
            key: (row.values[idx].strip() if idx < len(row.values) else None)
            for key, idx in column_map.items()
        }
        record["page"] = row.page_number
        structured.append(record)
    return structured


def resolve_grid(table: Table) -> list[list[str]]:
    """Expand row/col spans into a dense grid, repeating the spanning cell's
    content into every position it covers. This is what implements rowspan
    carry-forward: a label printed once but visually spanning several rows
    ends up present in the grid for every one of those rows."""
    grid = [["" for _ in range(table.column_count)] for _ in range(table.row_count)]
    for cell in table.cells:
        for r in range(cell.row_index, cell.row_index + cell.row_span):
            for c in range(cell.column_index, cell.column_index + cell.column_span):
                if r < table.row_count and c < table.column_count:
                    grid[r][c] = cell.content
    return grid


def header_row_index(table: Table) -> int:
    header_rows = {c.row_index for c in table.cells if c.kind == "columnHeader"}
    return min(header_rows) if header_rows else 0


@dataclass
class LogicalRow:
    values: list[str]
    subgroup: str | None = None
    page_number: int | None = None


def extract_logical_rows(grid: list[list[str]], data_start_row: int,
                          page_numbers_by_row: dict[int, int] | None = None) -> list[LogicalRow]:
    """Walk the resolved grid below the header and split out full-width
    sub-group label rows from real data rows.

    A row that came from a single cell spanning the whole row will, after
    `resolve_grid`, have identical content repeated in every column — that's
    the signal used to detect it as a sub-group label rather than data.
    """
    rows: list[LogicalRow] = []
    current_subgroup: str | None = None
    for i in range(data_start_row, len(grid)):
        row = grid[i]
        if not row:
            continue
        non_empty = [v for v in row if v.strip()]
        if non_empty and len(set(row)) == 1:
            current_subgroup = row[0].strip()
            continue
        if not non_empty:
            continue
        page_number = (page_numbers_by_row or {}).get(i)
        rows.append(LogicalRow(values=row, subgroup=current_subgroup, page_number=page_number))
    return rows


def markdown_header(header: list[str]) -> str:
    head = "| " + " | ".join(header) + " |"
    sep = "| " + " | ".join(["---"] * len(header)) + " |"
    return f"{head}\n{sep}"


def markdown_row(row: LogicalRow, label_col_index: int = 0) -> str:
    values = list(row.values)
    if row.subgroup and label_col_index < len(values):
        values[label_col_index] = f"({row.subgroup}) {values[label_col_index]}"
    return "| " + " | ".join(values) + " |"


@dataclass
class TableChunkPiece:
    rows: list[LogicalRow]
    body_text: str
    row_count: int
    page_numbers: list[int]
    entities: list[str] = field(default_factory=list)


def chunk_table_rows(
    logical_rows: Iterable[LogicalRow],
    *,
    header_line: str,
    intro_line: str,
    breadcrumb_line: str,
    max_tokens: int,
    group_key_fn: Callable[[LogicalRow], str | None],
    row_formatter: Callable[[LogicalRow], str] = markdown_row,
    entity_fn: Callable[[LogicalRow], str | None] | None = None,
) -> list[TableChunkPiece]:
    """Greedy row-integrity-preserving chunker.

    Never splits a single row. When a candidate chunk would exceed
    `max_tokens`, prefers to cut at the most recent group-boundary already in
    the buffer (so a group like "all Carbaryl rows" stays together) rather
    than mid-group; falls back to a hard cut only when no group boundary is
    available yet.
    """
    rows = list(logical_rows)

    def render(buf: list[LogicalRow]) -> str:
        body = "\n".join(row_formatter(r) for r in buf)
        lines = [l for l in (breadcrumb_line, intro_line, header_line) if l]
        return "\n".join(lines + [body])

    def make_piece(buf: list[LogicalRow]) -> TableChunkPiece:
        entities = []
        if entity_fn:
            for r in buf:
                e = entity_fn(r)
                if e and e not in entities:
                    entities.append(e)
        pages = sorted({r.page_number for r in buf if r.page_number is not None})
        return TableChunkPiece(
            rows=list(buf),
            body_text=render(buf),
            row_count=len(buf),
            page_numbers=pages,
            entities=entities,
        )

    pieces: list[TableChunkPiece] = []
    buffer: list[LogicalRow] = []
    group_boundaries: list[int] = []  # indices into `buffer` where a new group started
    prev_group_key: object = object()  # sentinel, never equal to a real key

    for row in rows:
        group_key = group_key_fn(row)
        is_new_group = group_key != prev_group_key
        candidate = buffer + [row]

        if buffer and count_tokens(render(candidate)) > max_tokens:
            if is_new_group:
                pieces.append(make_piece(buffer))
                buffer = []
                group_boundaries = []
            elif group_boundaries and group_boundaries[-1] > 0:
                cut = group_boundaries[-1]
                pieces.append(make_piece(buffer[:cut]))
                buffer = buffer[cut:]
                group_boundaries = [0]
            else:
                pieces.append(make_piece(buffer))
                buffer = []
                group_boundaries = []
                is_new_group = True

        if is_new_group:
            group_boundaries.append(len(buffer))
        buffer.append(row)
        prev_group_key = group_key

    if buffer:
        pieces.append(make_piece(buffer))

    return pieces
