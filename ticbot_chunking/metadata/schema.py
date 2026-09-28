"""Document-level and chunk-level metadata, per section 7 of
TICbot_Chunking_Strategy_Answers.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class DocumentMetadata:
    doc_type: str  # regulation | accreditation_scope | brochure | capability_matrix | contact_directory | reference_register
    source_file: str
    authority: str | None = None
    business_area: str | None = None
    geography: str | None = None
    lab_location: str | None = None
    certificate_no: str | None = None
    accreditation_standard: str | None = None
    validity: str | None = None
    last_amended: str | None = None
    issued: str | None = None
    effective: str | None = None
    access_class: str = "public"  # public | internal | licensed
    contains_pii: bool = False
    language: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class ChunkMetadata:
    chunk_type: str  # text | table | scope_records | figure | figure_text | certificate | sheet_table | sheet_lists | sheet_kv | sheet_chart
    doc_type: str
    source_file: str
    tokens: int
    pages: list[int] = field(default_factory=list)
    page_start: int | None = None  # first physical page this chunk's own content came from
    page_end: int | None = None  # last physical page this chunk's own content came from
    printed_page_label: str | None = None  # the document's own printed label for page_start, e.g. "4/20", when known
    doc_title: str | None = None  # the document's real title (never a letterhead block — see experiments.common.document_title)
    sheet: str | None = None
    cell_range: str | None = None
    section_path: str | None = None
    section_number: str | None = None
    table_header: list[str] | None = None
    structured_rows: list[dict[str, Any]] | None = None  # this chunk's table rows as data, for UI table rendering
    entities: list[str] | None = None
    row_count: int | None = None
    discipline: str | None = None
    material: str | None = None
    facility: str | None = None
    sno_range: str | None = None
    part: str | None = None
    authority: str | None = None
    effective: str | None = None
    lab_location: str | None = None
    certificate_no: str | None = None
    validity: str | None = None
    access_class: str = "public"
    contains_pii: bool = False
    quality_flags: list[str] | None = None
    excel_table: str | None = None
    strategy: str | None = None  # which chunking strategy produced this (experiment framework only)
    parser: str | None = None  # local_pdf | document_intelligence | excel_parser — which parser read the source

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None and v != []}


@dataclass
class Chunk:
    text: str
    metadata: ChunkMetadata
    # Short, prefix-trimmed, spell-normalized text used only for embedding —
    # `text` stays authoritative for citation/quoting (original wording,
    # original breadcrumb) and is never altered. None for chunk types that
    # don't set one (e.g. Excel), in which case the indexer embeds `text`.
    embed_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {"text": self.text, "metadata": self.metadata.to_dict()}
        if self.embed_text is not None:
            d["embed_text"] = self.embed_text
        return d
