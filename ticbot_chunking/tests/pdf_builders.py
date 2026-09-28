"""Synthetic-PDF construction helpers shared by the page-router/page-classifier
tests (`test_page_classifier.py`, `test_page_router.py`).

Real sample PDFs (`upadated_data_sgs/`) remain the source of truth for
"genuine text-based PDF" wherever a test can use them (per the project's
standing rule against fabricating parsing results — see
`test_local_pdf.py`'s module docstring). These helpers exist only for what
real samples can't deterministically provide: precise, reproducible control
over page-by-page text amount, image coverage and page count, which the
page-level routing/classification tests need in order to exercise TEXT,
SCANNED and AMBIGUOUS pages — and every mix of them — on demand. No text
content is invented beyond plain, obviously-synthetic filler ("word0
word1 ..."); nothing here fabricates realistic document content.

Not a test module itself (no `test_` prefix) — pytest does not collect it.
"""
from __future__ import annotations

import ctypes

import pypdfium2 as pdfium
import pypdfium2.raw as raw

DEFAULT_WIDTH = 300.0
DEFAULT_HEIGHT = 400.0


def new_pdf() -> pdfium.PdfDocument:
    return pdfium.PdfDocument.new()


def filler_text(word_count: int) -> str:
    return " ".join(f"word{i}" for i in range(word_count))


def add_text_page(doc: pdfium.PdfDocument, word_count: int, width: float = DEFAULT_WIDTH,
                   height: float = DEFAULT_HEIGHT, x: float = 20.0, y: float | None = None):
    """Adds a page carrying a single real text object with exactly
    `word_count` space-separated words — enough control to land a page
    precisely on either side of the classifier's TEXT thresholds."""
    page = doc.new_page(width, height)
    if word_count > 0:
        text = filler_text(word_count)
        _insert_text(doc, page, text, x=x, y=height - 40.0 if y is None else y)
    page.gen_content()
    return page


def add_blank_page(doc: pdfium.PdfDocument, width: float = DEFAULT_WIDTH, height: float = DEFAULT_HEIGHT):
    """A page with no text and no image — a stand-in for a scanned page
    with no OCR text layer at all (same pattern as `test_local_pdf.py`'s
    `blank_pdf` fixture)."""
    return doc.new_page(width, height)


def add_image_page(doc: pdfium.PdfDocument, image_coverage: float, caption_word_count: int = 0,
                    width: float = DEFAULT_WIDTH, height: float = DEFAULT_HEIGHT):
    """A page carrying one image sized to cover `image_coverage` (0.0-1.0)
    of the page area, and optionally a short caption of real text below
    it — a stand-in for a scanned/photographed page (optionally with a
    thin OCR'd caption)."""
    page = doc.new_page(width, height)
    if image_coverage > 0:
        img_height = min(height, height * image_coverage)
        img_width = width
        bitmap = pdfium.PdfBitmap.new_native(max(1, int(img_width)), max(1, int(img_height)), raw.FPDFBitmap_BGRA)
        bitmap.fill_rect((120, 120, 120, 255), 0, 0, max(1, int(img_width)), max(1, int(img_height)))
        image = pdfium.PdfImage.new(doc)
        image.set_bitmap(bitmap)
        image.set_matrix(pdfium.PdfMatrix().scale(img_width, img_height).translate(0, height - img_height))
        page.insert_obj(image)
    if caption_word_count > 0:
        _insert_text(doc, page, filler_text(caption_word_count), x=10.0, y=15.0)
    page.gen_content()
    return page


def add_multi_block_page(doc: pdfium.PdfDocument, blocks: list[tuple],
                          width: float = DEFAULT_WIDTH, height: float = DEFAULT_HEIGHT, font_size: float = 12.0):
    """Adds a page carrying several independently-positioned text blocks —
    `blocks` is a list of `(text, x, y_from_top)` triples (or `(text, x,
    y_from_top, block_font_size)` 4-tuples, to give one block a distinct
    font size — e.g. a heading-sized title against normal-sized body text,
    which the local parser's font-based heading fallback relies on).
    `y_from_top` is measured from the page's TOP edge (matching
    pdfplumber's own `top` convention) rather than pdfium's native
    bottom-left origin, so callers can reason about "near the
    top"/"near the bottom" directly. Used for header/footer/page-number/
    per-page-title fixtures that need multiple distinct blocks on one
    page, which `add_text_page`'s single block can't express."""
    page = doc.new_page(width, height)
    for block in blocks:
        text, x, y_from_top = block[0], block[1], block[2]
        block_font_size = block[3] if len(block) > 3 else font_size
        _insert_text(doc, page, text, x=x, y=height - y_from_top, font_size=block_font_size)
    page.gen_content()
    return page


def _insert_text(doc: pdfium.PdfDocument, page, text: str, x: float, y: float, font_size: float = 12.0):
    text_obj = raw.FPDFPageObj_NewTextObj(doc.raw, b"Helvetica", font_size)
    buf = (text + "\x00").encode("utf-16-le")
    raw.FPDFText_SetText(text_obj, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort)))
    matrix = raw.FS_MATRIX(1, 0, 0, 1, x, y)
    raw.FPDFPageObj_SetMatrix(text_obj, ctypes.byref(matrix))
    raw.FPDFPage_InsertObject(page.raw, text_obj)


def save_pdf(doc: pdfium.PdfDocument, path) -> str:
    doc.save(str(path))
    return str(path)
