"""Heading- and section-numbering-aware chunking for regulations (e.g.
FSSAI), with table-aware handling for limit tables.

Implements the "Regulations" row of section 1, and sections 2-4 and 6 of
TICbot_Chunking_Strategy_Answers.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ticbot_chunking.chunkers import table_utils
from ticbot_chunking.chunkers.section_numbering import SectionTracker
from ticbot_chunking.chunkers.text_utils import MIN_CONTENT_TOKENS, split_paragraph_units
from ticbot_chunking.config import NARRATIVE, REGULATION_TABLE
from ticbot_chunking.experiments.common import document_title as _compute_document_title
from ticbot_chunking.metadata.classifier import extract_method_codes, infer_printed_page_labels
from ticbot_chunking.metadata.schema import Chunk, ChunkMetadata, DocumentMetadata
from ticbot_chunking.metadata.spellfix import spell_normalize
from ticbot_chunking.parsers.ir import (
    LayoutDocument,
    ROLE_PAGE_FOOTER,
    ROLE_PAGE_HEADER,
    ROLE_PAGE_NUMBER,
    ROLE_SECTION_HEADING,
    ROLE_TITLE,
    Table,
)
from ticbot_chunking.tokenizer import count_tokens

# Column-role synonyms/fallbacks for a regulation's limit table (Task 3
# item C — generic content-driven grouping instead of a hardcoded column
# index). "entity" is whichever column names the thing being regulated
# (an insecticide, a metal, a contaminant); "food" is the food/article
# column; "limit" is the tolerance-limit/value column.
_ENTITY_SYNONYMS = {
    "name of insecticides": "entity", "name of insecticide": "entity", "insecticide": "entity",
    "name of the metal": "entity", "metal": "entity", "contaminant": "entity", "name of contaminant": "entity",
}
_ENTITY_KEYWORD_FALLBACKS = [
    ("insecticide", "entity"), ("metal", "entity"), ("contaminant", "entity"), ("name of", "entity"),
]
_FOOD_SYNONYMS = {"name of the article of food": "food", "article of food": "food", "food": "food"}
_FOOD_KEYWORD_FALLBACKS = [("article of food", "food"), ("food", "food")]
_LIMIT_SYNONYMS = {"tolerance limit": "limit", "limit": "limit", "parts per million": "limit"}
_LIMIT_KEYWORD_FALLBACKS = [("tolerance", "limit"), ("limit", "limit"), ("million", "limit"), ("ppm", "limit")]


@dataclass
class _Section:
    section_path: str
    section_number: str | None
    parent_key: tuple
    depth: int
    is_annexure: bool
    paragraphs: list[tuple[str, list[int]]] = field(default_factory=list)
    pages: set[int] = field(default_factory=set)
    tables: list[Table] = field(default_factory=list)
    table_intro: dict[int, str] = field(default_factory=dict)


def _walk_sections(doc: LayoutDocument, document_title: str) -> list[_Section]:
    tracker = SectionTracker(document_title)
    sections: list[_Section] = []
    current: _Section | None = None
    last_text_paragraph = ""

    tables_by_para_idx: dict[int, list[Table]] = {}
    for t in doc.tables:
        idx = t.preceding_paragraph_index if t.preceding_paragraph_index is not None else -1
        tables_by_para_idx.setdefault(idx, []).append(t)

    def ensure_current() -> _Section:
        nonlocal current
        if current is None:
            current = _Section(
                tracker.section_path, tracker.section_number, tracker.parent_key,
                tracker.depth, tracker.in_annexure,
            )
            sections.append(current)
        return current

    def attach_tables_for(idx: int) -> None:
        sec = ensure_current()
        for table in tables_by_para_idx.get(idx, []):
            sec.table_intro[len(sec.tables)] = last_text_paragraph
            sec.tables.append(table)
            sec.pages.update(table.page_numbers)

    for i, para in enumerate(doc.paragraphs):
        if para.role in (ROLE_PAGE_HEADER, ROLE_PAGE_FOOTER, ROLE_PAGE_NUMBER):
            attach_tables_for(i)
            continue
        if para.role == ROLE_TITLE and current is None and not sections:
            attach_tables_for(i)
            continue
        # Any OTHER title-role paragraph is a later page's own per-page
        # title (local_pdf.py now assigns ROLE_TITLE once per physical
        # page, not once per document — see its docstring), which for a
        # regulation is just another heading, not a second document title.
        if para.role in (ROLE_SECTION_HEADING, ROLE_TITLE):
            tracker.ingest_heading(para.text)
            current = _Section(
                tracker.section_path, tracker.section_number, tracker.parent_key,
                tracker.depth, tracker.in_annexure,
            )
            sections.append(current)
            current.pages.update(para.page_numbers)
            attach_tables_for(i)
            continue

        sec = ensure_current()
        text = para.text.strip()
        if text:
            sec.paragraphs.append((text, para.page_numbers))
            last_text_paragraph = text
        sec.pages.update(para.page_numbers)
        attach_tables_for(i)

    for table in tables_by_para_idx.get(-1, []):
        sec = ensure_current()
        sec.table_intro[len(sec.tables)] = last_text_paragraph
        sec.tables.append(table)
        sec.pages.update(table.page_numbers)

    return sections


def _merge_small_sections(sections: list[_Section]) -> list[_Section]:
    merged: list[_Section] = []
    i = 0
    while i < len(sections):
        s = sections[i]
        text_tokens = count_tokens(" ".join(t for t, _ in s.paragraphs))
        has_narrative = bool(s.paragraphs)

        if has_narrative and text_tokens < NARRATIVE.min_tokens and merged and merged[-1].parent_key == s.parent_key:
            merged[-1].paragraphs.extend(s.paragraphs)
            merged[-1].pages.update(s.pages)
            for idx, table in enumerate(s.tables):
                merged[-1].table_intro[len(merged[-1].tables)] = s.table_intro.get(idx, "")
                merged[-1].tables.append(table)
            i += 1
            continue

        if (
            has_narrative
            and text_tokens < NARRATIVE.min_tokens
            and i + 1 < len(sections)
            and sections[i + 1].parent_key == s.parent_key
        ):
            nxt = sections[i + 1]
            nxt.paragraphs = s.paragraphs + nxt.paragraphs
            nxt.pages = s.pages | nxt.pages
            shifted_intro = dict(s.table_intro)
            for idx, intro in nxt.table_intro.items():
                shifted_intro[idx + len(s.tables)] = intro
            nxt.table_intro = shifted_intro
            nxt.tables = s.tables + nxt.tables
            i += 1
            continue

        merged.append(s)
        i += 1
    return merged


def _short_section_path(document_title: str, section_path: str) -> str:
    """The short embed-only prefix (Task 3.7): document title + the section
    breadcrumb *below* it, not the long citation breadcrumb `text` also
    carries. `section_path` already starts with `document_title` (see
    SectionTracker) so this just avoids repeating it twice."""
    return section_path


def _embed_text(document_title: str, section_path: str, pages: list[int], body: str) -> str:
    page_label = f"Page {pages[0]}" if len(pages) == 1 else f"Pages {pages[0]}-{pages[-1]}" if pages else "Page —"
    prefix = f"{_short_section_path(document_title, section_path)} | {page_label}"
    return f"{prefix}\n{spell_normalize(body)}"


def _emit_narrative_chunks(section: _Section, doc_meta: DocumentMetadata, source_file: str,
                            document_title: str) -> list[Chunk]:
    if not section.paragraphs:
        return []

    header = f"[Regulation] {section.section_path}."
    full_text = "\n\n".join(t for t, _ in section.paragraphs).strip()
    if not full_text:
        return []
    total_tokens = count_tokens(full_text)
    if total_tokens <= NARRATIVE.max_tokens:
        parts = [(full_text, sorted(section.pages))]
    else:
        parts = split_paragraph_units(
            section.paragraphs, NARRATIVE.target_tokens, NARRATIVE.max_tokens, NARRATIVE.overlap_max_tokens,
            min_tokens=NARRATIVE.min_tokens,
        )

    chunks = []
    n = len(parts)
    for idx, (part_text, part_pages) in enumerate(parts, start=1):
        if count_tokens(part_text) < MIN_CONTENT_TOKENS:
            continue
        text = f"{header}\n{part_text}"
        pages = part_pages or sorted(section.pages)
        meta = ChunkMetadata(
            chunk_type="text",
            doc_type="regulation",
            source_file=source_file,
            tokens=count_tokens(text),
            pages=pages,
            page_start=pages[0] if pages else None,
            page_end=pages[-1] if pages else None,
            doc_title=document_title,
            section_path=section.section_path,
            section_number=section.section_number,
            part=f"{idx}/{n}" if n > 1 else None,
            authority=doc_meta.authority,
            effective=doc_meta.effective,
            access_class=doc_meta.access_class,
        )
        chunks.append(Chunk(
            text=text, metadata=meta,
            embed_text=_embed_text(document_title, section.section_path, pages, part_text),
        ))
    return chunks


def _emit_table_chunks(
    section: _Section, table: Table, intro_text: str, doc_meta: DocumentMetadata, source_file: str,
    document_title: str,
) -> list[Chunk]:
    grid = table_utils.resolve_grid(table)
    hidx = table_utils.header_row_index(table)
    header = grid[hidx]

    page_by_row: dict[int, int] = {}
    for cell in table.cells:
        if cell.page_number is not None and cell.row_index not in page_by_row:
            page_by_row[cell.row_index] = cell.page_number

    logical_rows = table_utils.extract_logical_rows(grid, hidx + 1, page_by_row)
    if not logical_rows:
        return []

    entity_cols = table_utils.detect_column(header, _ENTITY_SYNONYMS, _ENTITY_KEYWORD_FALLBACKS)
    food_cols = table_utils.detect_column(header, _FOOD_SYNONYMS, _FOOD_KEYWORD_FALLBACKS)
    limit_cols = table_utils.detect_column(header, _LIMIT_SYNONYMS, _LIMIT_KEYWORD_FALLBACKS)
    label_col = entity_cols.get("entity")

    header_line = table_utils.markdown_header(header)
    breadcrumb = f"[Regulation] {section.section_path}."
    intro_line = f"Table context: {intro_text}" if intro_text else "Table context:"

    def group_key_fn(row: table_utils.LogicalRow) -> str | None:
        if label_col is not None and label_col < len(row.values):
            return row.values[label_col]
        return row.subgroup  # falls back to the table's own full-width banner-row grouping, never a hardcoded index

    column_map = {}
    if "entity" in entity_cols:
        column_map["contaminant"] = entity_cols["entity"]
    if "food" in food_cols:
        column_map["food"] = food_cols["food"]
    if "limit" in limit_cols:
        column_map["limit"] = limit_cols["limit"]

    pieces = table_utils.chunk_table_rows(
        logical_rows,
        header_line=header_line,
        intro_line=intro_line,
        breadcrumb_line=breadcrumb,
        max_tokens=REGULATION_TABLE.max_tokens,
        group_key_fn=group_key_fn,
        entity_fn=group_key_fn,
    )

    chunks = []
    for piece in pieces:
        codes = extract_method_codes(piece.body_text)
        pages = piece.page_numbers or sorted(section.pages)
        structured_rows = table_utils.rows_to_structured(piece.rows, column_map) if column_map else None
        meta = ChunkMetadata(
            chunk_type="table",
            doc_type="regulation",
            source_file=source_file,
            tokens=count_tokens(piece.body_text),
            pages=pages,
            page_start=pages[0] if pages else None,
            page_end=pages[-1] if pages else None,
            doc_title=document_title,
            section_path=section.section_path,
            section_number=section.section_number,
            table_header=header,
            structured_rows=structured_rows,
            entities=piece.entities or (codes or None),
            row_count=piece.row_count,
            authority=doc_meta.authority,
            effective=doc_meta.effective,
            access_class=doc_meta.access_class,
        )
        chunks.append(Chunk(
            text=piece.body_text, metadata=meta,
            embed_text=_embed_text(document_title, section.section_path, pages, piece.body_text),
        ))
    return chunks


def chunk_regulation(doc: LayoutDocument, doc_meta: DocumentMetadata) -> list[Chunk]:
    document_title = _compute_document_title(doc, doc_meta.source_file)
    sections = _walk_sections(doc, document_title)
    sections = _merge_small_sections(sections)

    chunks: list[Chunk] = []
    for section in sections:
        chunks.extend(_emit_narrative_chunks(section, doc_meta, doc.source_file, document_title))
        for idx, table in enumerate(section.tables):
            intro = section.table_intro.get(idx, "")
            chunks.extend(_emit_table_chunks(section, table, intro, doc_meta, doc.source_file, document_title))

    printed_labels = infer_printed_page_labels(doc_meta.source_file, [p.page_number for p in doc.pages])
    if printed_labels:
        for c in chunks:
            if c.metadata.page_start in printed_labels:
                c.metadata.printed_page_label = printed_labels[c.metadata.page_start]

    return chunks
