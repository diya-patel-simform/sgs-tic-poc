"""Tests for parsers/page_classifier.py — per-page TEXT/SCANNED/AMBIGUOUS
detection for mixed text/scanned PDFs. Uses the real sample PDF for "every
page is genuinely text" and synthetic pages built via `pdf_builders` (never
`text_length == 0` alone) for the other classifications — see that
module's docstring for why synthetic pages are needed here at all.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ticbot_chunking.parsers.page_classifier import (
    PAGE_AMBIGUOUS,
    PAGE_SCANNED,
    PAGE_TEXT,
    classify_pages,
)
from ticbot_chunking.tests.pdf_builders import (
    add_blank_page,
    add_image_page,
    add_text_page,
    new_pdf,
    save_pdf,
)

REAL_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "upadated_data_sgs"
REAL_REGULATION_PDF = REAL_SAMPLES_DIR / "Contaminants_Regulations_pages_1-5.pdf"


def _require_real_sample(path: Path):
    if not path.exists():
        pytest.skip(f"real sample PDF not present: {path}")


def test_real_text_pdf_classifies_every_page_as_text():
    _require_real_sample(REAL_REGULATION_PDF)
    signals = classify_pages(str(REAL_REGULATION_PDF))
    assert len(signals) == 5
    assert all(s.classification == PAGE_TEXT for s in signals)
    assert [s.page_number for s in signals] == [1, 2, 3, 4, 5]


def test_blank_page_classifies_as_scanned(tmp_path):
    doc = new_pdf()
    add_blank_page(doc)
    path = save_pdf(doc, tmp_path / "blank.pdf")

    signal = classify_pages(path)[0]
    assert signal.classification == PAGE_SCANNED
    assert signal.char_count == 0
    assert signal.word_count == 0


def test_full_page_image_with_caption_still_classifies_as_scanned(tmp_path):
    # Detection must not rely on text_length == 0 alone: this page DOES
    # have real, extractable caption text, but is overwhelmingly a
    # full-page image (>= SCANNED_IMAGE_COVERAGE) — a photographed/scanned
    # page, not a text page with an incidental image.
    doc = new_pdf()
    add_image_page(doc, image_coverage=0.95, caption_word_count=15)
    path = save_pdf(doc, tmp_path / "image_with_caption.pdf")

    signal = classify_pages(path)[0]
    assert signal.char_count > 0  # real text was present
    assert signal.classification == PAGE_SCANNED  # image coverage still dominates


def test_sparse_text_page_classifies_as_ambiguous(tmp_path):
    # Some genuine text, but far below the confident-TEXT thresholds, and
    # well above the "essentially nothing" SCANNED cutoff.
    doc = new_pdf()
    add_text_page(doc, word_count=5)
    path = save_pdf(doc, tmp_path / "sparse.pdf")

    signal = classify_pages(path)[0]
    assert signal.classification == PAGE_AMBIGUOUS


def test_moderate_image_coverage_with_some_text_classifies_as_ambiguous(tmp_path):
    doc = new_pdf()
    add_image_page(doc, image_coverage=0.7, caption_word_count=15)
    path = save_pdf(doc, tmp_path / "moderate_image.pdf")

    signal = classify_pages(path)[0]
    assert signal.classification == PAGE_AMBIGUOUS


def test_dense_real_text_page_classifies_as_text_not_scanned(tmp_path):
    # A page with plenty of words (as a dense table/list page would have)
    # should read as TEXT, not be second-guessed into SCANNED/AMBIGUOUS.
    doc = new_pdf()
    add_text_page(doc, word_count=60)
    path = save_pdf(doc, tmp_path / "dense.pdf")

    signal = classify_pages(path)[0]
    assert signal.classification == PAGE_TEXT
    assert signal.word_count == 60


# ---------------------------------------------------------------------------
# layout_multi_column / layout_table_dense — the two new "too complex for
# the local parser to trust" signals. Tested against lightweight fake page
# objects (mirroring pdfplumber's own Page interface: .width, .height,
# .find_tables()) rather than real PDFs, since these test the geometric
# detection functions directly, in isolation, with precise control over
# word positions that a real generated PDF couldn't guarantee as exactly.
# ---------------------------------------------------------------------------

def _word(text, x0, x1, top, bottom=None):
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": bottom if bottom is not None else top + 10}


class _FakeTable:
    def __init__(self, data, bbox):
        self._data = data
        self.bbox = bbox

    def extract(self):
        return self._data


class _FakePage:
    def __init__(self, width, height, tables=None):
        self.width = width
        self.height = height
        self._tables = tables or []

    def find_tables(self):
        return self._tables


def test_detect_multi_column_true_for_a_clean_two_column_layout():
    from ticbot_chunking.parsers import page_classifier as pc

    words = []
    # Two columns whose lines are offset in `top` from each other (as real
    # columns of independently-wrapped text usually are) so the naive
    # same-top line grouping doesn't merge them — see this function's own
    # docstring for the real-world case where lines DO align and this
    # signal misses it.
    for i in range(6):
        words.append(_word(f"left{i}", 40, 220, top=100 + i * 20))
    for i in range(6):
        words.append(_word(f"right{i}", 380, 560, top=105 + i * 20))
    page = _FakePage(width=600, height=800)

    assert pc._detect_multi_column(page, words) is True


def test_detect_multi_column_false_for_ordinary_single_column_words():
    from ticbot_chunking.parsers import page_classifier as pc

    words = [_word(f"word{i}", 40, 200, top=100 + i * 20) for i in range(10)]
    page = _FakePage(width=600, height=800)

    assert pc._detect_multi_column(page, words) is False


def test_detect_multi_column_false_with_too_few_lines():
    from ticbot_chunking.parsers import page_classifier as pc

    # Only 2 lines per side — below MIN_LINES_PER_COLUMN, even though the
    # gutter itself would otherwise qualify.
    words = [_word("left0", 40, 220, top=100), _word("left1", 40, 220, top=120),
              _word("right0", 380, 560, top=105), _word("right1", 380, 560, top=125)]
    page = _FakePage(width=600, height=800)

    assert pc._detect_multi_column(page, words) is False


def test_detect_table_dense_true_for_a_large_ruled_table():
    from ticbot_chunking.parsers import page_classifier as pc

    data = [["ID", "Product", "Method"]] + [[f"P{i}", f"Product {i}", "PCR"] for i in range(5)]
    table = _FakeTable(data, bbox=(50, 100, 550, 400))  # covers a large fraction of an 600x800 page
    page = _FakePage(width=600, height=800, tables=[table])

    assert pc._detect_table_dense(page) is True


def test_detect_table_dense_false_for_a_small_table():
    from ticbot_chunking.parsers import page_classifier as pc

    data = [["A", "B"], ["1", "2"]]
    table = _FakeTable(data, bbox=(50, 100, 150, 130))  # tiny fraction of the page
    page = _FakePage(width=600, height=800, tables=[table])

    assert pc._detect_table_dense(page) is False


def test_detect_table_dense_false_when_no_tables_found():
    from ticbot_chunking.parsers import page_classifier as pc

    page = _FakePage(width=600, height=800, tables=[])
    assert pc._detect_table_dense(page) is False


def test_layout_signals_downgrade_an_otherwise_text_page_to_ambiguous():
    from ticbot_chunking.parsers import page_classifier as pc

    strong_text_kwargs = dict(char_count=500, word_count=80, density=0.01, image_coverage=0.0, quality=1.0)
    assert pc._classify(**strong_text_kwargs) == PAGE_TEXT
    assert pc._classify(**strong_text_kwargs, layout_multi_column=True) == PAGE_AMBIGUOUS
    assert pc._classify(**strong_text_kwargs, layout_table_dense=True) == PAGE_AMBIGUOUS


def test_classification_does_not_rely_on_char_count_alone():
    # A page can fail to be TEXT even with a non-zero char count (covered
    # above by the image-with-caption case) and a page can fail to be
    # SCANNED even with a fairly low char count (the sparse/ambiguous
    # case) — classification is genuinely multi-signal, not a single
    # `text_length == 0` check re-implemented under a new name.
    from ticbot_chunking.parsers import page_classifier as pc

    assert pc._classify(char_count=50, word_count=8, density=0.001, image_coverage=0.0, quality=1.0) == PAGE_AMBIGUOUS
    assert pc._classify(char_count=200, word_count=5, density=0.001, image_coverage=0.0, quality=1.0) == PAGE_AMBIGUOUS  # enough chars, too few words
    assert pc._classify(char_count=200, word_count=30, density=0.001, image_coverage=0.0, quality=0.4) == PAGE_AMBIGUOUS  # garbled text layer
