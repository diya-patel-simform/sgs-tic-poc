"""Adapter: Azure AI Document Intelligence (prebuilt-layout) -> LayoutDocument.

Used only for scanned/image-only PDFs — `parsers/router.py` decides which
PDFs come here vs. to the local parser (`parsers/local_pdf.py`), based on
automatic text-layer detection, not a manually supplied flag. This is the
only module in the chunking pipeline that makes a live Azure call.
Everything downstream (section_numbering, table_utils, the four chunkers)
is built and unit-tested against the LayoutDocument IR directly, so it
needs no credentials — only this adapter and `retrieval/` do.

Requires AZURE_DOCINTEL_ENDPOINT / AZURE_DOCINTEL_KEY (see .env.example).
"""
from __future__ import annotations

import re

from ticbot_chunking.config import DOCINTEL
from ticbot_chunking.parsers.ir import (
    BoundingBox,
    Figure,
    LayoutDocument,
    Page,
    Paragraph,
    Table,
    TableCell,
)

# Document Intelligence is called with output_content_format="markdown"
# (see parse_pdf/parse_pdf_pages below), which can inject markdown syntax
# into a paragraph's own `.content` — headings, bold/italic emphasis, or an
# occasional stray table-row line — that has no business showing up as
# visible characters in chunk text. Stripped once here, at IR-construction
# time, rather than downstream in every chunker.
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_MD_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_MD_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")


def _strip_markdown_syntax(text: str) -> str:
    if not text:
        return text
    lines = [line for line in text.split("\n") if not _MD_TABLE_ROW_RE.match(line)]
    cleaned = _MD_HEADING_RE.sub("", "\n".join(lines))
    cleaned = _MD_BOLD_RE.sub(lambda m: m.group(1) or m.group(2), cleaned)
    cleaned = _MD_ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), cleaned)
    return cleaned


def _require_client():
    if not DOCINTEL.is_configured:
        raise RuntimeError(
            "Azure Document Intelligence is not configured. Set AZURE_DOCINTEL_ENDPOINT and "
            "AZURE_DOCINTEL_KEY (see .env.example) before parsing PDFs."
        )
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    return DocumentIntelligenceClient(endpoint=DOCINTEL.endpoint, credential=AzureKeyCredential(DOCINTEL.key))


def _bounding_boxes(bounding_regions) -> list[BoundingBox]:
    boxes = []
    for region in bounding_regions or []:
        polygon = region.polygon or []
        xs = polygon[0::2]
        ys = polygon[1::2]
        if not xs or not ys:
            boxes.append(BoundingBox(page_number=region.page_number))
            continue
        boxes.append(
            BoundingBox(
                page_number=region.page_number,
                x=min(xs), y=min(ys),
                width=max(xs) - min(xs), height=max(ys) - min(ys),
            )
        )
    return boxes


def _span_offset(item) -> int:
    spans = getattr(item, "spans", None)
    return spans[0].offset if spans else -1


def _to_layout_document(result, source_file: str, scanned_page_numbers: set[int] | None = None) -> LayoutDocument:
    """`scanned_page_numbers` are the pages Document Intelligence should tag
    `is_scanned=True` on the resulting IR. Callers get this automatically
    from `parsers.local_pdf.inspect_text_layer` (see `parse_pdf` below) —
    it's accepted here as a plain parameter only to keep this function
    testable against synthetic `result` objects without needing a real PDF
    file on disk."""
    scanned_page_numbers = scanned_page_numbers or set()

    pages = [
        Page(
            page_number=p.page_number, width=p.width or 0.0, height=p.height or 0.0,
            is_scanned=p.page_number in scanned_page_numbers,
        )
        for p in (result.pages or [])
    ]

    paragraphs: list[Paragraph] = []
    para_offsets: list[int] = []
    for p in result.paragraphs or []:
        paragraphs.append(
            Paragraph(text=_strip_markdown_syntax(p.content or ""), role=p.role or "text",
                      bounding_boxes=_bounding_boxes(p.bounding_regions))
        )
        para_offsets.append(_span_offset(p))

    tables: list[Table] = []
    for t in result.tables or []:
        cells = []
        table_page_numbers: set[int] = set()
        for c in t.cells or []:
            page_number = None
            if c.bounding_regions:
                page_number = c.bounding_regions[0].page_number
                table_page_numbers.add(page_number)
            cells.append(
                TableCell(
                    row_index=c.row_index, column_index=c.column_index, content=c.content or "",
                    row_span=c.row_span or 1, column_span=c.column_span or 1,
                    kind=c.kind, page_number=page_number,
                )
            )

        table_offset = _span_offset(t)
        preceding_idx = None
        for i, off in enumerate(para_offsets):
            if off == -1:
                continue
            if off < table_offset:
                preceding_idx = i
            else:
                break

        tables.append(
            Table(
                row_count=t.row_count, column_count=t.column_count, cells=cells,
                page_numbers=sorted(table_page_numbers), preceding_paragraph_index=preceding_idx,
            )
        )

    figures: list[Figure] = []
    for f in getattr(result, "figures", None) or []:
        page_number = f.bounding_regions[0].page_number if f.bounding_regions else 1
        caption = f.caption.content if getattr(f, "caption", None) else None
        fig_box = _bounding_boxes(f.bounding_regions)[0] if f.bounding_regions else None
        inline_fragments = []
        if fig_box:
            for p in paragraphs:
                if not p.bounding_boxes:
                    continue
                box = p.bounding_boxes[0]
                if box.page_number != page_number:
                    continue
                overlaps_x = box.x < fig_box.x + fig_box.width and fig_box.x < box.x + box.width
                overlaps_y = box.y < fig_box.y + fig_box.height and fig_box.y < box.y + box.height
                if overlaps_x and overlaps_y:
                    inline_fragments.append(p.text)
        figures.append(Figure(caption=caption, page_number=page_number, bounding_box=fig_box,
                               inline_text_fragments=inline_fragments))

    return LayoutDocument(source_file=source_file, pages=pages, paragraphs=paragraphs, tables=tables, figures=figures)


def _pages_param(page_numbers: set[int]) -> str:
    """Compresses a set of 1-based page numbers into Document Intelligence's
    `pages=` selection syntax, e.g. {41, 81, 82} -> "41,81-82" — so a page
    selection sends only the pages that actually need OCR, not the whole
    document (see `parse_pdf_pages` / `parsers/page_router.py`)."""
    ordered = sorted(page_numbers)
    ranges: list[tuple[int, int]] = []
    start = prev = ordered[0]
    for n in ordered[1:]:
        if n == prev + 1:
            prev = n
            continue
        ranges.append((start, prev))
        start = prev = n
    ranges.append((start, prev))
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in ranges)


def parse_pdf_pages(file_path: str, page_numbers: set[int], scanned_page_numbers: set[int] | None = None) -> LayoutDocument:
    """Runs the Layout model over only `page_numbers` of the PDF, via
    Document Intelligence's `pages=` selection — the page-level counterpart
    to `parse_pdf` below, used for mixed text/scanned PDFs where only some
    pages need OCR (see `parsers/page_router.py`). Pages *not* in
    `page_numbers` are never sent to Azure at all.

    Document Intelligence's page selection preserves each analyzed page's
    original `page_number` in the result (it does not renumber the
    selection to 1..N), so the `LayoutDocument` returned here merges
    directly by page number with the local parser's output for the
    document's other pages.

    `scanned_page_numbers` defaults to all of `page_numbers` — every page
    sent here went through OCR, so every page is tagged `is_scanned=True`
    on the resulting IR unless the caller narrows it (e.g. to exclude
    AMBIGUOUS pages that still had some of their own extractable text).
    """
    if not page_numbers:
        raise ValueError("parse_pdf_pages requires at least one page number")
    scanned_page_numbers = scanned_page_numbers if scanned_page_numbers is not None else set(page_numbers)

    client = _require_client()
    with open(file_path, "rb") as f:
        poller = client.begin_analyze_document(
            "prebuilt-layout", body=f, output_content_format="markdown",
            features=["ocrHighResolution"], pages=_pages_param(page_numbers),
        )
    result = poller.result()
    return _to_layout_document(result, source_file=file_path, scanned_page_numbers=scanned_page_numbers)


def parse_pdf(file_path: str, text_layer_stats=None) -> LayoutDocument:
    """Runs the Layout model (with OCR and figure detection) over a PDF and
    returns the normalized LayoutDocument IR. This is the path used for
    scanned/image-only PDFs — see `parsers/router.py` for how a PDF is
    routed here vs. to the local parser.

    Document Intelligence OCRs every page uniformly and doesn't expose a
    native/scanned distinction per page, so which pages get tagged
    `is_scanned=True` on the resulting IR is determined automatically from
    `text_layer_stats` (a `local_pdf.TextLayerStats`, cheap and local to
    compute — no manual flag): a page with no usable embedded text layer of
    its own is `is_scanned=True` even though the whole document was routed
    here. If not supplied, it's computed on the fly from `file_path`.
    """
    if text_layer_stats is None:
        from ticbot_chunking.parsers.local_pdf import inspect_text_layer
        text_layer_stats = inspect_text_layer(file_path)
    scanned_pages = {p for p in range(1, text_layer_stats.total_pages + 1)} - text_layer_stats.pages_with_text

    client = _require_client()
    with open(file_path, "rb") as f:
        poller = client.begin_analyze_document(
            "prebuilt-layout", body=f, output_content_format="markdown",
            features=["ocrHighResolution"],
        )
    result = poller.result()
    return _to_layout_document(result, source_file=file_path, scanned_page_numbers=scanned_pages)
