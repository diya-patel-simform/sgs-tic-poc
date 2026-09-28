"""Page-level routing and merging for mixed text/scanned PDFs.

    PDF -> page_classifier.classify_pages() -> per page: TEXT / SCANNED / AMBIGUOUS
                     |                                        |
                     | TEXT pages                              | SCANNED or AMBIGUOUS pages
                     v                                        v
        local_pdf.parse_pdf_local_pages()      azure_docintel.parse_pdf_pages()
        (e.g. pages 1-40, 42-80, 83-100)        (e.g. pages="41,81-82" — only
                                                  those pages are sent to Azure,
                                                  never the whole document)
                     \\                                        /
                      \\-------------------> merge by original page number, in
                                              ascending page order -> one
                                              LayoutDocument -> chunking

Unlike `parsers/router.py` (which picks exactly one parser for an entire
document, based on what fraction of its pages have a usable text layer),
this module decides per page — so a document that's mostly text-based with
a handful of scanned pages sends only those scanned pages to Document
Intelligence, and a document that's mostly scanned still gets its few real
text pages parsed locally for free. This is the fix for the "mixed
text/scanned PDFs route as a whole document, not per page" item in
KNOWN_ISSUES.md.

Both parsers already return the exact same `LayoutDocument` IR (see
`parsers/ir.py`), so merging is purely a matter of combining and
reordering — no format translation needed. `parse_pdf_paged` is the single
entry point; everything else here is either a building block for it or a
diagnostic helper.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from ticbot_chunking.parsers import azure_docintel, local_pdf, text_normalize
from ticbot_chunking.parsers.ir import LayoutDocument, Page
from ticbot_chunking.parsers.page_classifier import PAGE_TEXT, PageSignal, classify_pages

PARSER_LOCAL = "local_pdf"
PARSER_DOCUMENT_INTELLIGENCE = "document_intelligence"


@dataclass
class PageRoutingPlan:
    signals: list[PageSignal]
    text_pages: set[int]  # routed to the local parser
    ocr_pages: set[int]  # routed to Document Intelligence (SCANNED + AMBIGUOUS)

    @property
    def total_pages(self) -> int:
        return len(self.signals)

    def parser_for_page(self, page_number: int) -> str:
        return PARSER_LOCAL if page_number in self.text_pages else PARSER_DOCUMENT_INTELLIGENCE


def plan_page_routing(file_path: str) -> PageRoutingPlan:
    """Classifies every page (cheap, local, no Azure call) and decides which
    parser each one goes to, without actually parsing anything yet."""
    signals = classify_pages(file_path)
    text_pages = {s.page_number for s in signals if s.classification == PAGE_TEXT}
    ocr_pages = {s.page_number for s in signals if s.classification != PAGE_TEXT}
    return PageRoutingPlan(signals=signals, text_pages=text_pages, ocr_pages=ocr_pages)


def describe_page_routing(file_path: str) -> PageRoutingPlan:
    """Alias for `plan_page_routing` — useful for diagnostics/tests that
    want to confirm the per-page routing decision cheaply, without parsing
    (mirrors `router.describe_routing`'s role for whole-document routing)."""
    return plan_page_routing(file_path)


def parse_pdf_paged(file_path: str, plan: PageRoutingPlan | None = None) -> LayoutDocument:
    """Parses a PDF with page-level routing: TEXT pages go through the
    local parser, SCANNED/AMBIGUOUS pages go through Document Intelligence
    (only those pages — see `azure_docintel.parse_pdf_pages`), and both
    results are merged back into one `LayoutDocument`, ordered by original
    page number, with page numbers, `source_file`, and reading order all
    preserved. See the module docstring for the full pipeline.

    `plan` lets a caller that already needs the routing decision for its
    own purposes (e.g. `ingestion.orchestrator`, which also records which
    parser(s) ran for its processing report) pass it in directly, instead
    of this function classifying every page a second time.

    Letter-spacing artifacts are normalized (`text_normalize`) exactly once
    here, after parsing/merging, regardless of which path below produced
    the document — letter-spacing can come from either parser, and running
    it once on the final paragraph list (rather than per-parser) avoids
    ever normalizing the same already-merged text twice.
    """
    plan = plan or plan_page_routing(file_path)

    if not plan.ocr_pages:
        # No page needs OCR — parse entirely locally, no Azure call at all.
        doc = local_pdf.parse_pdf_local(file_path)
    else:
        local_doc = local_pdf.parse_pdf_local_pages(file_path, plan.text_pages) if plan.text_pages else None
        azure_doc = azure_docintel.parse_pdf_pages(file_path, plan.ocr_pages, scanned_page_numbers=plan.ocr_pages)
        doc = _merge(file_path, local_doc, azure_doc)

    text_normalize.normalize_paragraphs(doc.paragraphs)
    return doc


def _page_number_of(paragraph) -> int:
    return paragraph.bounding_boxes[0].page_number if paragraph.bounding_boxes else 0


def _merge(file_path: str, local_doc: LayoutDocument | None, azure_doc: LayoutDocument | None) -> LayoutDocument:
    docs = [d for d in (local_doc, azure_doc) if d is not None]

    pages_by_number: dict[int, Page] = {}
    for doc in docs:
        for page in doc.pages:
            pages_by_number[page.page_number] = page
    ordered_pages = [pages_by_number[n] for n in sorted(pages_by_number)]

    # Tag every paragraph with which source doc/index it came from so a
    # table's `preceding_paragraph_index` (an index into that doc's own
    # paragraph list) can be remapped onto the merged list below — sorting
    # to establish final page order invalidates the original indices.
    tagged = [(para, doc_idx, i) for doc_idx, doc in enumerate(docs) for i, para in enumerate(doc.paragraphs)]
    tagged.sort(key=lambda t: _page_number_of(t[0]))  # stable: preserves each doc's own reading order per page

    paragraphs = [t[0] for t in tagged]
    index_map = {(doc_idx, old_idx): new_idx for new_idx, (_, doc_idx, old_idx) in enumerate(tagged)}

    tables = []
    for doc_idx, doc in enumerate(docs):
        for table in doc.tables:
            new_preceding = None
            if table.preceding_paragraph_index is not None:
                new_preceding = index_map.get((doc_idx, table.preceding_paragraph_index))
            tables.append(replace(table, preceding_paragraph_index=new_preceding))
    tables.sort(key=lambda t: min(t.page_numbers) if t.page_numbers else 0)

    figures = [figure for doc in docs for figure in doc.figures]
    figures.sort(key=lambda f: f.page_number)

    return LayoutDocument(source_file=file_path, pages=ordered_pages, paragraphs=paragraphs, tables=tables, figures=figures)
