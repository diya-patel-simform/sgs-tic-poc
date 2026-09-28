"""Layout-aware chunking for brochures / service catalogues.

Implements the "Brochures / catalogues" row of section 1 of
TICbot_Chunking_Strategy_Answers.md: multi-column reading order is fixed
first, then chunks are split by heading, product tables are handled as
tables, and informative figures become their own chunks (decorative photos
excluded).

Section hierarchy uses the same `SectionTracker` regulation.py uses (not a
separate, flat `document_title › heading` breadcrumb) — a page's own
title (e.g. "Crop Science") opens a new top-level branch via
`ingest_top_level`, and any finer heading on the same page nests one level
below it automatically. A page with no heading/title paragraph at all
(e.g. a photo + pull-quote page whose sector is conveyed only by an icon)
still gets its own section, titled literally "(untitled page)" unless
Document Intelligence assigned a title-role paragraph anywhere on that
page — tagged via `quality_flags` either way, never silently guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ticbot_chunking.chunkers import table_utils
from ticbot_chunking.chunkers.section_numbering import SectionTracker
from ticbot_chunking.chunkers.text_utils import MIN_CONTENT_TOKENS, split_paragraph_units
from ticbot_chunking.config import NARRATIVE, REGULATION_TABLE
from ticbot_chunking.experiments.common import document_title as _compute_document_title
from ticbot_chunking.metadata.classifier import infer_printed_page_labels
from ticbot_chunking.metadata.schema import Chunk, ChunkMetadata, DocumentMetadata
from ticbot_chunking.metadata.spellfix import spell_normalize
from ticbot_chunking.parsers.ir import (
    Figure,
    LayoutDocument,
    Paragraph,
    ROLE_PAGE_FOOTER,
    ROLE_PAGE_HEADER,
    ROLE_PAGE_NUMBER,
    ROLE_SECTION_HEADING,
    ROLE_TITLE,
    Table,
)
from ticbot_chunking.tokenizer import count_tokens

# A figure is treated as decorative (and dropped) unless it has a caption or
# inline text, matching the sample result of 50 decorative / 8 informative
# out of 58 brochure images (section 6.6).
DEFAULT_FIGURE_CLASSIFIER: Callable[[Figure], bool] = lambda fig: bool(
    (fig.caption and fig.caption.strip()) or fig.inline_text_fragments
)

# Column-role synonyms/fallbacks for a catalog-style product table (Task 3
# item C) — generic content-driven grouping instead of a hardcoded column.
_PRODUCT_ID_SYNONYMS = {"id": "product_id", "product id": "product_id"}
_PRODUCT_ID_KEYWORD_FALLBACKS = [("id", "product_id")]
_PRODUCT_SYNONYMS = {"product": "product", "service": "product"}
_PRODUCT_KEYWORD_FALLBACKS = [("product", "product"), ("service", "product"), ("description", "product")]
_METHOD_SYNONYMS = {"method": "method", "technique": "method"}
_METHOD_KEYWORD_FALLBACKS = [("method", "method"), ("technique", "method")]

MIN_TINY_SECTION_TOKENS = 30  # ~150 characters (Task 3.4's "under ~150 characters" rule, in tokens


def fix_reading_order(paragraphs: list[Paragraph]) -> list[Paragraph]:
    """Multi-column layouts are read column-by-column, top-to-bottom, left-
    to-right across columns, rather than raw top-to-bottom across the whole
    page width (which would interleave unrelated columns' lines).

    Groups paragraphs per page, buckets them into columns by x-position
    (paragraphs whose bounding boxes overlap on x are in the same column),
    orders columns left to right, and orders paragraphs within a column by y.

    Known limitation (see `parsers/page_classifier.py`'s own documented
    limitation on the same underlying problem): a full-width paragraph
    placed first in a column bucket becomes that bucket's permanent
    x-reference, so a full-width title immediately followed by genuine
    columns can still collapse them into one bucket. Left as-is rather than
    "fixed" with an equally-fragile heuristic — see KNOWN_ISSUES.md.
    """
    by_page: dict[int, list[Paragraph]] = {}
    for p in paragraphs:
        pages = p.page_numbers or [0]
        by_page.setdefault(pages[0], []).append(p)

    ordered: list[Paragraph] = []
    for page_number in sorted(by_page):
        page_paragraphs = by_page[page_number]
        with_boxes = [p for p in page_paragraphs if p.bounding_boxes]
        without_boxes = [p for p in page_paragraphs if not p.bounding_boxes]

        columns: list[list[Paragraph]] = []
        for p in sorted(with_boxes, key=lambda p: p.bounding_boxes[0].x):
            x = p.bounding_boxes[0].x
            width = p.bounding_boxes[0].width or 0.0
            placed = False
            for col in columns:
                col_x = col[0].bounding_boxes[0].x
                col_width = col[0].bounding_boxes[0].width or 0.0
                if x < col_x + col_width and col_x < x + width:
                    col.append(p)
                    placed = True
                    break
            if not placed:
                columns.append([p])

        columns.sort(key=lambda col: min(p.bounding_boxes[0].x for p in col))
        for col in columns:
            col.sort(key=lambda p: p.bounding_boxes[0].y)
        for col in columns:
            ordered.extend(col)
        ordered.extend(without_boxes)

    return ordered


@dataclass
class _Section:
    section_path: str
    section_number: str | None
    parent_key: tuple
    paragraphs: list[tuple[str, list[int]]] = field(default_factory=list)
    pages: set[int] = field(default_factory=set)
    tables: list[Table] = field(default_factory=list)
    table_intro: dict[int, str] = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)


def _walk_sections(paragraphs: list[Paragraph], tables: list[Table], document_title: str) -> list[_Section]:
    tracker = SectionTracker(document_title)
    tables_by_para_idx: dict[int, list[Table]] = {}
    for t in tables:
        idx = t.preceding_paragraph_index if t.preceding_paragraph_index is not None else -1
        tables_by_para_idx.setdefault(idx, []).append(t)

    # Pages that have at least one heading/title-role paragraph anywhere —
    # precomputed so an untitled page (Task 3.3) can be detected the moment
    # its first (body-text) paragraph is reached, with no lookahead needed
    # inside the main walk below.
    heading_roles = (ROLE_TITLE, ROLE_SECTION_HEADING)
    pages_with_heading = {p.page_numbers[0] for p in paragraphs if p.role in heading_roles and p.page_numbers}

    sections: list[_Section] = []
    current: _Section | None = None
    last_text = ""
    current_page: int | None = None

    def open_section(quality_flags: list[str] | None = None) -> _Section:
        nonlocal current
        current = _Section(tracker.section_path, tracker.section_number, tracker.parent_key,
                            quality_flags=list(quality_flags or []))
        sections.append(current)
        return current

    def ensure_current() -> _Section:
        nonlocal current
        if current is None:
            open_section()
        return current

    def attach_tables_for(idx: int) -> None:
        sec = ensure_current()
        for table in tables_by_para_idx.get(idx, []):
            sec.table_intro[len(sec.tables)] = last_text
            sec.tables.append(table)
            sec.pages.update(table.page_numbers)

    for i, para in enumerate(paragraphs):
        page_number = para.page_numbers[0] if para.page_numbers else current_page

        if para.role in (ROLE_PAGE_HEADER, ROLE_PAGE_FOOTER, ROLE_PAGE_NUMBER):
            attach_tables_for(i)
            continue

        if para.role == ROLE_TITLE and current is None and not sections and para.text.strip() == document_title:
            # This page's title IS exactly the already-computed document
            # title (the common case: `document_title()` picked this very
            # paragraph) — skip opening a redundant page-title node for it,
            # since `SectionTracker.section_path` already starts with
            # `document_title` at its base level. Any OTHER title-role
            # paragraph (including a later, DIFFERENT page-1 candidate)
            # still opens its own section below.
            attach_tables_for(i)
            current_page = page_number
            continue

        if para.role in (ROLE_TITLE, ROLE_SECTION_HEADING):
            if para.role == ROLE_TITLE:
                # Every other title-role paragraph is a PAGE's own title
                # (never silently skipped as a document-wide letterhead the
                # way regulation.py's is — a brochure's page title is
                # genuinely structural, e.g. a real intro heading, not a
                # throwaway address block; the document's own title is
                # computed separately, up front, by `document_title()`).
                tracker.ingest_top_level(para.text.strip())
            else:
                tracker.ingest_heading(para.text.strip())
            open_section()
            current.pages.update(para.page_numbers)
            current_page = page_number
            attach_tables_for(i)
            continue

        if page_number is not None and page_number != current_page and page_number not in pages_with_heading:
            # Body text is the first thing on this page — no heading/title
            # was ever assigned to it (a genuinely untitled page). Prefer a
            # Document-Intelligence-assigned title anywhere on the page if
            # one exists (the real Health & Nutrition page-5 "Crop Science"
            # case: a title role that isn't the page's first/largest
            # paragraph) over the literal "(untitled page)" fallback.
            di_title = next(
                (p.text.strip() for p in paragraphs
                 if p.page_numbers and p.page_numbers[0] == page_number and p.role == ROLE_TITLE),
                None,
            )
            if di_title:
                tracker.ingest_top_level(di_title)
                open_section(quality_flags=["sector_inferred_from_di_title_role"])
            else:
                tracker.ingest_top_level("(untitled page)")
                open_section(quality_flags=["untitled_page"])

        current_page = page_number if page_number is not None else current_page

        sec = ensure_current()
        text = para.text.strip()
        if text:
            sec.paragraphs.append((text, para.page_numbers))
            last_text = text
        sec.pages.update(para.page_numbers)
        attach_tables_for(i)

    for table in tables_by_para_idx.get(-1, []):
        sec = ensure_current()
        sec.table_intro[len(sec.tables)] = last_text
        sec.tables.append(table)
        sec.pages.update(table.page_numbers)

    return sections


def _merge_tiny_sections(sections: list[_Section]) -> list[_Section]:
    """Task 3.4: a heading-only or very small section (< ~150 characters of
    its own narrative) is folded into a neighbouring sibling under the same
    parent, rather than left as an orphan near-empty chunk — mirroring
    regulation.py's `_merge_small_sections`, generalized here via
    `SectionTracker.parent_key` (now shared, since brochure sections carry
    real hierarchy too)."""
    merged: list[_Section] = []
    i = 0
    while i < len(sections):
        s = sections[i]
        text_tokens = count_tokens(" ".join(t for t, _ in s.paragraphs))
        is_tiny = text_tokens < MIN_TINY_SECTION_TOKENS

        if is_tiny and merged and merged[-1].parent_key == s.parent_key:
            merged[-1].paragraphs.extend(s.paragraphs)
            merged[-1].pages.update(s.pages)
            merged[-1].quality_flags.extend(f for f in s.quality_flags if f not in merged[-1].quality_flags)
            for idx, table in enumerate(s.tables):
                merged[-1].table_intro[len(merged[-1].tables)] = s.table_intro.get(idx, "")
                merged[-1].tables.append(table)
            i += 1
            continue

        if is_tiny and i + 1 < len(sections) and sections[i + 1].parent_key == s.parent_key:
            nxt = sections[i + 1]
            nxt.paragraphs = s.paragraphs + nxt.paragraphs
            nxt.pages = s.pages | nxt.pages
            nxt.quality_flags = list(dict.fromkeys(s.quality_flags + nxt.quality_flags))
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


def _embed_text(document_title: str, section_path: str, pages: list[int], body: str) -> str:
    page_label = f"Page {pages[0]}" if len(pages) == 1 else f"Pages {pages[0]}-{pages[-1]}" if pages else "Page —"
    return f"{section_path} | {page_label}\n{spell_normalize(body)}"


def _emit_text_chunks(section: _Section, doc_meta: DocumentMetadata, document_title: str) -> list[Chunk]:
    if not section.paragraphs:
        return []

    header = f"[Brochure / Service catalog] {section.section_path}"
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
            doc_type="brochure",
            source_file=doc_meta.source_file,
            tokens=count_tokens(text),
            pages=pages,
            page_start=pages[0] if pages else None,
            page_end=pages[-1] if pages else None,
            doc_title=document_title,
            section_path=section.section_path,
            section_number=section.section_number,
            part=f"{idx}/{n}" if n > 1 else None,
            access_class=doc_meta.access_class,
            quality_flags=section.quality_flags or None,
        )
        chunks.append(Chunk(
            text=text, metadata=meta,
            embed_text=_embed_text(document_title, section.section_path, pages, part_text),
        ))
    return chunks


def _emit_table_chunks(section: _Section, table: Table, intro_text: str, doc_meta: DocumentMetadata,
                        document_title: str) -> list[Chunk]:
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

    id_cols = table_utils.detect_column(header, _PRODUCT_ID_SYNONYMS, _PRODUCT_ID_KEYWORD_FALLBACKS)
    product_cols = table_utils.detect_column(header, _PRODUCT_SYNONYMS, _PRODUCT_KEYWORD_FALLBACKS)
    method_cols = table_utils.detect_column(header, _METHOD_SYNONYMS, _METHOD_KEYWORD_FALLBACKS)
    label_col = id_cols.get("product_id", product_cols.get("product"))

    breadcrumb = f"[Brochure / Service catalog] {section.section_path}"
    intro_line = f"Table context: {intro_text}" if intro_text else "Table context:"
    header_line = table_utils.markdown_header(header)

    def group_key_fn(row: table_utils.LogicalRow) -> str | None:
        if label_col is not None and label_col < len(row.values):
            return row.values[label_col]
        return row.subgroup if row.subgroup else (row.values[0] if row.values else None)

    column_map = {}
    if "product_id" in id_cols:
        column_map["product_id"] = id_cols["product_id"]
    if "product" in product_cols:
        column_map["product"] = product_cols["product"]
    if "method" in method_cols:
        column_map["method"] = method_cols["method"]

    pieces = table_utils.chunk_table_rows(
        logical_rows,
        header_line=header_line,
        intro_line=intro_line,
        breadcrumb_line=breadcrumb,
        max_tokens=REGULATION_TABLE.max_tokens,
        group_key_fn=group_key_fn,
    )

    chunks = []
    for piece in pieces:
        pages = piece.page_numbers or sorted(section.pages)
        structured_rows = table_utils.rows_to_structured(piece.rows, column_map) if column_map else None
        meta = ChunkMetadata(
            chunk_type="table",
            doc_type="brochure",
            source_file=doc_meta.source_file,
            tokens=count_tokens(piece.body_text),
            pages=pages,
            page_start=pages[0] if pages else None,
            page_end=pages[-1] if pages else None,
            doc_title=document_title,
            section_path=section.section_path,
            table_header=header,
            structured_rows=structured_rows,
            row_count=piece.row_count,
            access_class=doc_meta.access_class,
        )
        chunks.append(Chunk(
            text=piece.body_text, metadata=meta,
            embed_text=_embed_text(document_title, section.section_path, pages, piece.body_text),
        ))
    return chunks


def _emit_figure_chunk(figure: Figure, section_path: str, doc_meta: DocumentMetadata,
                        document_title: str) -> Chunk | None:
    if not DEFAULT_FIGURE_CLASSIFIER(figure):
        return None
    figure_text = " | ".join(figure.inline_text_fragments) if figure.inline_text_fragments else (figure.caption or "")
    if count_tokens(figure_text) < MIN_CONTENT_TOKENS:
        return None
    text = f"[Brochure / Service catalog] {section_path}\nFigure text: {figure_text}"
    pages = [figure.page_number]
    meta = ChunkMetadata(
        chunk_type="figure_text",
        doc_type="brochure",
        source_file=doc_meta.source_file,
        tokens=count_tokens(text),
        pages=pages,
        page_start=pages[0],
        page_end=pages[0],
        doc_title=document_title,
        section_path=section_path,
        access_class=doc_meta.access_class,
    )
    return Chunk(
        text=text, metadata=meta,
        embed_text=_embed_text(document_title, section_path, pages, figure_text),
    )


def chunk_brochure(doc: LayoutDocument, doc_meta: DocumentMetadata) -> list[Chunk]:
    document_title = _compute_document_title(doc, doc_meta.source_file)
    ordered_paragraphs = fix_reading_order(doc.paragraphs)
    sections = _walk_sections(ordered_paragraphs, doc.tables, document_title)
    sections = _merge_tiny_sections(sections)

    chunks: list[Chunk] = []
    for section in sections:
        chunks.extend(_emit_text_chunks(section, doc_meta, document_title))
        for idx, table in enumerate(section.tables):
            intro = section.table_intro.get(idx, "")
            chunks.extend(_emit_table_chunks(section, table, intro, doc_meta, document_title))

    for figure in doc.figures:
        section = next((s for s in sections if figure.page_number in s.pages), None)
        section_path = section.section_path if section else f"{document_title} › (untitled page)"
        chunk = _emit_figure_chunk(figure, section_path, doc_meta, document_title)
        if chunk:
            chunks.append(chunk)

    printed_labels = infer_printed_page_labels(doc_meta.source_file, [p.page_number for p in doc.pages])
    if printed_labels:
        for c in chunks:
            if c.metadata.page_start in printed_labels:
                c.metadata.printed_page_label = printed_labels[c.metadata.page_start]

    return chunks
