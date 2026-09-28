"""Normalized layout representation that every chunker operates on.

This mirrors the shape of an Azure AI Document Intelligence (prebuilt-layout)
AnalyzeResult closely on purpose: `azure_docintel.py` is a thin adapter that
maps the SDK response onto these dataclasses, so everything downstream
(section-numbering, table handling, the four document-type chunkers) can be
built and unit-tested against plain Python fixtures without any Azure
credentials, and swapped onto real Azure output with no chunker changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Paragraph roles we care about, as produced by the Layout model.
ROLE_TITLE = "title"
ROLE_SECTION_HEADING = "sectionHeading"
ROLE_PAGE_HEADER = "pageHeader"
ROLE_PAGE_FOOTER = "pageFooter"
ROLE_PAGE_NUMBER = "pageNumber"  # a standalone printed page number/label (e.g. "3", "4/20") — dropped from chunk text
ROLE_FOOTNOTE = "footnote"
ROLE_TEXT = "text"


@dataclass
class BoundingBox:
    """Position on a page, used to fix multi-column reading order."""
    page_number: int
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0


@dataclass
class Paragraph:
    text: str
    role: str = ROLE_TEXT
    bounding_boxes: list[BoundingBox] = field(default_factory=list)

    @property
    def page_numbers(self) -> list[int]:
        return sorted({b.page_number for b in self.bounding_boxes})


@dataclass
class TableCell:
    row_index: int
    column_index: int
    content: str
    row_span: int = 1
    column_span: int = 1
    kind: str | None = None  # "columnHeader" | "rowHeader" | None
    page_number: int | None = None


@dataclass
class Table:
    row_count: int
    column_count: int
    cells: list[TableCell]
    page_numbers: list[int] = field(default_factory=list)
    # Index into LayoutDocument.paragraphs of the paragraph that most likely
    # introduces this table (nearest preceding text paragraph on the same page).
    preceding_paragraph_index: int | None = None
    caption: str | None = None


@dataclass
class Figure:
    caption: str | None
    page_number: int
    bounding_box: BoundingBox | None = None
    # Free-text extracted from inside the figure region (e.g. labelled workflow
    # steps in a brochure infographic), when the layout model surfaces it.
    inline_text_fragments: list[str] = field(default_factory=list)


@dataclass
class Page:
    page_number: int
    width: float = 0.0
    height: float = 0.0
    is_scanned: bool = False  # true if this page had no extractable text layer (OCR-only)


@dataclass
class LayoutDocument:
    source_file: str
    pages: list[Page]
    paragraphs: list[Paragraph]
    tables: list[Table]
    figures: list[Figure] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)
