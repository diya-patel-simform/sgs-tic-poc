"""Record-aware table chunking for NABL scopes of accreditation.

Implements the "NABL scopes of accreditation" row of section 1, the NABL
rows of sections 2-4 and 6, and the certificate + annexure modelling
described in section 4 ("Appendices / annexures") of
TICbot_Chunking_Strategy_Answers.md.

Each accredited test (S.No, discipline, material, parameter, method) is kept
whole. Tests are grouped by discipline and material, and every chunk repeats
the lab/certificate header plus the Facility/Discipline/Material line for
its own group, so it stands alone (section 5B's sample chunk shape).
"""
from __future__ import annotations

import re
from typing import Iterable, Iterator

from ticbot_chunking.chunkers import table_utils
from ticbot_chunking.config import NABL_SCOPE
from ticbot_chunking.metadata.schema import Chunk, ChunkMetadata, DocumentMetadata
from ticbot_chunking.parsers.ir import LayoutDocument, Table
from ticbot_chunking.tokenizer import count_tokens

# Column-name synonyms seen across NABL scope tables, mapped to canonical roles.
# Matched only against a normalized header cell (see _normalize_header_cell) —
# exact match, checked first.
COLUMN_SYNONYMS = {
    "s.no": "sno", "s. no.": "sno", "s.no.": "sno", "sl.no": "sno", "sr.no": "sno",
    "facility": "facility", "type of facility": "facility",
    "discipline": "discipline", "discipline/group": "discipline", "group": "discipline",
    "material": "material", "material/product": "material", "product": "material",
    "parameter": "parameter", "parameter/analyte": "parameter", "test": "parameter",
    "test parameter": "parameter",
    "method": "method", "method/technique": "method", "test method": "method",
    "specification": "method",
}

# Fallback for real-world NABL scope tables whose header cells are longer,
# multi-line, real regulatory-document phrasing that doesn't exactly match
# COLUMN_SYNONYMS (e.g. a real header column reading "Component, parameter or
# characteristic tested / Specific Test Performed / Tests or type of tests
# performed" rather than a short "Parameter" label) — checked only for a
# column whose role isn't already resolved by an exact synonym match, using
# the first keyword (in this priority order) that appears anywhere in the
# normalized header text.
KEYWORD_FALLBACKS: list[tuple[str, str]] = [
    ("facility", "facility"),
    ("discipline", "discipline"),
    ("material", "material"), ("product", "material"),
    ("parameter", "parameter"), ("characteristic", "parameter"), ("analyte", "parameter"),
    ("method", "method"), ("specification", "method"), ("technique", "method"),
]


# Used when discipline/material aren't explicit columns and instead arrive as a
# full-width banner row (extracted as `row.subgroup`) like:
# "Facility: Permanent Facility | Discipline/Group: ... | Material/Product: ..."
FACILITY_RE = re.compile(r"Facility\s*:\s*([^|]+)", re.IGNORECASE)
DISCIPLINE_RE = re.compile(r"Discipline(?:/Group)?\s*:\s*([^|]+)", re.IGNORECASE)
MATERIAL_RE = re.compile(r"Material(?:/Product)?\s*:\s*([^|]+)", re.IGNORECASE)


def _canonical_columns(header: list[str]) -> dict[str, int]:
    """Thin wrapper over the shared, generalized `table_utils.detect_column`
    — kept as its own function (rather than inlining the call at each call
    site) purely so NABL's own synonym/fallback tables stay declared next
    to the code that uses them. Behavior is unchanged from before this was
    generalized; see test_nabl_scope_real_header_regression.py."""
    return table_utils.detect_column(header, COLUMN_SYNONYMS, KEYWORD_FALLBACKS)


def _first_match(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1).strip() if m else None


def _group_context(row: table_utils.LogicalRow, cols: dict[str, int]) -> tuple[str, str | None, str | None, str | None]:
    """Returns (group_key, facility, discipline, material) for a row, reading
    from explicit columns when present, else parsing the banner subgroup."""
    if "discipline" in cols or "material" in cols:
        facility = row.values[cols["facility"]].strip() if "facility" in cols else None
        discipline = row.values[cols["discipline"]].strip() if "discipline" in cols else None
        material = row.values[cols["material"]].strip() if "material" in cols else None
    elif row.subgroup:
        banner = row.subgroup
        facility = _first_match(FACILITY_RE, banner)
        discipline = _first_match(DISCIPLINE_RE, banner)
        material = _first_match(MATERIAL_RE, banner)
        if discipline is None and material is None:
            discipline = banner.strip()
    else:
        facility = discipline = material = None

    key = f"{facility}||{discipline}||{material}"
    return key, facility, discipline, material


def _group_line(facility: str | None, discipline: str | None, material: str | None) -> str:
    # "—" for an unresolved field, consistently with discipline/material —
    # unlike an earlier version of this line, a genuinely unknown facility is
    # never presented as "Permanent Facility" (that value is only ever used
    # when actually extracted from an explicit facility column or a real
    # "Facility: ..." banner row — see _group_context).
    return (
        f"Facility: {facility or '—'} | "
        f"Discipline/Group: {discipline or '—'} | "
        f"Material/Product: {material or '—'}"
    )


def _format_record(row: table_utils.LogicalRow, cols: dict[str, int]) -> str:
    sno = row.values[cols["sno"]].strip() if "sno" in cols else "?"
    parameter = row.values[cols["parameter"]].strip() if "parameter" in cols else ""
    method = row.values[cols["method"]].strip() if "method" in cols else ""
    return f"S.No {sno}: {parameter} — Method: {method}".strip()


def _is_blank_record(row: table_utils.LogicalRow, cols: dict[str, int]) -> bool:
    """A row with no parameter and no method is a blank source-PDF row (seen
    in the samples, e.g. Chennai S.No 3816-3820) rather than a real
    accredited test — flagged and excluded, per section 6.6."""
    parameter = row.values[cols["parameter"]].strip() if "parameter" in cols else ""
    method = row.values[cols["method"]].strip() if "method" in cols else ""
    return not parameter and not method


def _sno_range(rows: list[table_utils.LogicalRow], cols: dict[str, int]) -> str | None:
    if "sno" not in cols:
        return None
    numbers = [int(r.values[cols["sno"]].strip()) for r in rows if r.values[cols["sno"]].strip().isdigit()]
    if not numbers:
        return None
    lo, hi = min(numbers), max(numbers)
    return f"{lo}–{hi}" if lo != hi else str(lo)


def _iter_group_blocks(
    rows: Iterable[table_utils.LogicalRow], cols: dict[str, int]
) -> Iterator[tuple[str, str | None, str | None, str | None, list[table_utils.LogicalRow]]]:
    """Groups contiguous rows sharing the same (facility, discipline,
    material), preserving document order — a scope table is read top to
    bottom one accredited-test block at a time, so contiguity is enough."""
    rows = list(rows)
    if not rows:
        return
    key, facility, discipline, material = _group_context(rows[0], cols)
    block = [rows[0]]
    for row in rows[1:]:
        k, f, d, m = _group_context(row, cols)
        if k == key:
            block.append(row)
        else:
            yield key, facility, discipline, material, block
            key, facility, discipline, material, block = k, f, d, m, [row]
    yield key, facility, discipline, material, block


def chunk_nabl_scope_table(
    table: Table, doc_meta: DocumentMetadata, doc_header_lines: list[str],
) -> list[Chunk]:
    grid = table_utils.resolve_grid(table)
    hidx = table_utils.header_row_index(table)
    header = grid[hidx]
    cols = _canonical_columns(header)

    page_by_row: dict[int, int] = {}
    for cell in table.cells:
        if cell.page_number is not None and cell.row_index not in page_by_row:
            page_by_row[cell.row_index] = cell.page_number

    logical_rows = table_utils.extract_logical_rows(grid, hidx + 1, page_by_row)
    if "parameter" in cols or "method" in cols:
        logical_rows = [r for r in logical_rows if not _is_blank_record(r, cols)]
    if not logical_rows:
        return []

    chunks: list[Chunk] = []
    for key, facility, discipline, material, block in _iter_group_blocks(logical_rows, cols):
        breadcrumb_block = "\n".join(doc_header_lines + [_group_line(facility, discipline, material)])
        pieces = table_utils.chunk_table_rows(
            block,
            header_line="",
            intro_line="Accredited tests:",
            breadcrumb_line=breadcrumb_block,
            max_tokens=NABL_SCOPE.max_tokens,
            group_key_fn=lambda _row, _k=key: _k,  # whole block is one group; splits are pure token-budget cuts
            row_formatter=lambda r: _format_record(r, cols),
        )
        for piece in pieces:
            meta = ChunkMetadata(
                chunk_type="scope_records",
                doc_type="accreditation_scope",
                source_file=doc_meta.source_file,
                tokens=count_tokens(piece.body_text),
                pages=piece.page_numbers,
                row_count=piece.row_count,
                discipline=discipline,
                material=material,
                facility=facility,
                lab_location=doc_meta.lab_location,
                certificate_no=doc_meta.certificate_no,
                validity=doc_meta.validity,
                sno_range=_sno_range(piece.rows, cols),
                access_class=doc_meta.access_class,
            )
            chunks.append(Chunk(text=piece.body_text, metadata=meta))
    return chunks


def chunk_scanned_certificate_page(
    ocr_text: str, page_number: int, doc_meta: DocumentMetadata, document_title: str,
) -> Chunk:
    """The scanned Certificate of Accreditation page (OCR'd) becomes its own
    single chunk, tagged chunk_type='certificate' and linked to the scope
    annexure by certificate number."""
    text = f"[NABL Certificate] {document_title}\n{ocr_text.strip()}"
    meta = ChunkMetadata(
        chunk_type="certificate",
        doc_type="accreditation_scope",
        source_file=doc_meta.source_file,
        tokens=count_tokens(text),
        pages=[page_number],
        lab_location=doc_meta.lab_location,
        certificate_no=doc_meta.certificate_no,
        validity=doc_meta.validity,
        access_class=doc_meta.access_class,
    )
    return Chunk(text=text, metadata=meta)


def chunk_nabl_scope(doc: LayoutDocument, doc_meta: DocumentMetadata, document_title: str) -> list[Chunk]:
    """Top-level entry: builds the repeating lab/certificate header lines,
    applies them (plus the per-group Facility/Discipline/Material line) to
    every scope-record chunk, and folds in any scanned certificate page found
    via OCR-only pages in the layout."""
    lab_line = (
        f"Lab: {doc_meta.lab_location or ''} | Certificate {doc_meta.certificate_no or ''} | "
        f"{doc_meta.accreditation_standard or ''} | Valid {doc_meta.validity or ''}"
        + (f" | Last amended {doc_meta.last_amended}" if doc_meta.last_amended else "")
    )
    doc_header_lines = [f"[NABL Scope of Accreditation] {document_title}", lab_line]

    chunks: list[Chunk] = []
    for table in doc.tables:
        chunks.extend(chunk_nabl_scope_table(table, doc_meta, doc_header_lines))

    for page in doc.pages:
        if page.is_scanned:
            ocr_paragraphs = [p.text for p in doc.paragraphs if page.page_number in p.page_numbers]
            if ocr_paragraphs:
                chunks.append(
                    chunk_scanned_certificate_page(
                        "\n".join(ocr_paragraphs), page.page_number, doc_meta, document_title
                    )
                )

    return chunks
