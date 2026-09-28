from openpyxl import Workbook

from ticbot_chunking.experiments.common import ParsedDoc, build_doc_metadata
from ticbot_chunking.experiments.recursive import chunk_recursive
from ticbot_chunking.parsers.ir import BoundingBox, LayoutDocument, Page, Paragraph, ROLE_TITLE


def _bbox(page: int) -> BoundingBox:
    return BoundingBox(page_number=page)


def _pdf_doc(paragraph_texts: list[str]) -> LayoutDocument:
    paragraphs = [Paragraph("Some Catalog", role=ROLE_TITLE, bounding_boxes=[_bbox(1)])]
    paragraphs += [Paragraph(t, bounding_boxes=[_bbox(1)]) for t in paragraph_texts]
    return LayoutDocument(source_file="catalog.pdf", pages=[Page(1)], paragraphs=paragraphs, tables=[])


def _parsed_pdf(paragraph_texts: list[str]) -> ParsedDoc:
    return ParsedDoc(source_file="catalog.pdf", local_path="catalog.pdf", doc_type="brochure", kind="pdf",
                      layout_doc=_pdf_doc(paragraph_texts))


def test_pack_units_tags_chunks_with_the_requested_strategy_not_its_own_default():
    # Regression test: _pack_units is reused by structure_aware.py, which
    # must be able to tag its own chunks "structure_aware" rather than
    # silently getting "recursive" from this module's own STRATEGY_NAME
    # default baked into the metadata.
    from ticbot_chunking.experiments.common import UnitRef
    from ticbot_chunking.experiments.recursive import _pack_units

    parsed = _parsed_pdf(["irrelevant"])
    doc_meta = build_doc_metadata(parsed)
    units = [("Some text.", UnitRef(pages=[1]))]

    default_chunks = _pack_units(units, "header", doc_meta, chunk_size=400, overlap=0, max_chunk_size=700)
    assert default_chunks[0].metadata.strategy == "recursive"

    custom_chunks = _pack_units(units, "header", doc_meta, chunk_size=400, overlap=0, max_chunk_size=700,
                                 strategy="structure_aware")
    assert custom_chunks[0].metadata.strategy == "structure_aware"


def test_recursive_never_cuts_a_short_paragraph_mid_sentence():
    short_paragraphs = [f"This is short paragraph number {i}, complete and self-contained." for i in range(20)]
    parsed = _parsed_pdf(short_paragraphs)
    doc_meta = build_doc_metadata(parsed)

    chunks = chunk_recursive(parsed, doc_meta, chunk_size=60, overlap=10, max_chunk_size=200)

    all_text = " ".join(c.text for c in chunks)
    for p in short_paragraphs:
        assert p in all_text  # every whole paragraph appears intact somewhere


def test_recursive_carries_overlap_between_consecutive_chunks():
    short_paragraphs = [f"This is short paragraph number {i}, complete and self-contained." for i in range(20)]
    parsed = _parsed_pdf(short_paragraphs)
    doc_meta = build_doc_metadata(parsed)

    chunks = chunk_recursive(parsed, doc_meta, chunk_size=60, overlap=15, max_chunk_size=200)

    assert len(chunks) > 1
    # the tail of one chunk's body should reappear at the head of the next
    body0 = chunks[0].text.split("\n", 1)[1]
    body1 = chunks[1].text.split("\n", 1)[1]
    last_sentence_of_0 = body0.strip().rsplit("This is short paragraph", 1)[-1]
    assert ("This is short paragraph" + last_sentence_of_0).strip() in body1


def test_recursive_splits_a_single_oversized_paragraph_at_sentence_boundaries():
    long_paragraph = " ".join(f"Sentence number {i} is right here." for i in range(80))
    parsed = _parsed_pdf([long_paragraph])
    doc_meta = build_doc_metadata(parsed)

    chunks = chunk_recursive(parsed, doc_meta, chunk_size=40, overlap=5, max_chunk_size=40)

    assert len(chunks) > 1
    for c in chunks:
        body = c.text.split("\n", 1)[1]
        assert body.strip() == "" or body.strip().endswith(".") or body.strip().endswith("right here")


def test_recursive_fixed_size_differ_on_where_they_cut_a_long_paragraph():
    from ticbot_chunking.experiments.fixed_size import chunk_fixed_size

    # Deliberately varied sentence lengths (unlike a uniform "Sentence
    # number N is right here." pattern, which can coincidentally align with
    # fixed windows if every sentence happens to be the same token count) —
    # this makes a fixed-size window landing mid-sentence somewhere close
    # to a certainty, while the recursive splitter must still never do so.
    words = ["Alpha", "Beta", "of", "the", "regulatory", "framework", "and", "its", "implementation",
             "across", "multiple", "jurisdictions", "including", "several", "edge", "cases"]
    sentences = [" ".join(words[: (i % len(words)) + 1]) + "." for i in range(1, 60)]
    long_paragraph = " ".join(sentences)
    parsed = _parsed_pdf([long_paragraph])
    doc_meta = build_doc_metadata(parsed)

    recursive_chunks = chunk_recursive(parsed, doc_meta, chunk_size=40, overlap=0, max_chunk_size=40)
    fixed_chunks = chunk_fixed_size(parsed, doc_meta, chunk_size=40, overlap=0, max_chunk_size=40)

    def body(c):
        return c.text.split("\n", 1)[1]

    recursive_all_clean = all(body(c).strip() == "" or body(c).strip()[-1] in ".!?" for c in recursive_chunks)
    fixed_any_mid_sentence = any(body(c).strip() and body(c).strip()[-1] not in ".!?" for c in fixed_chunks)

    assert recursive_all_clean
    assert fixed_any_mid_sentence  # fixed-size is expected to cut mid-sentence somewhere


def test_recursive_on_excel_packs_whole_rows(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for i in range(1, 15):
        ws.append([f"Row{i}A", f"Row{i}B"])
    path = tmp_path / "book.xlsx"
    wb.save(path)

    parsed = ParsedDoc(source_file="book.xlsx", local_path=str(path), doc_type="reference_register", kind="excel")
    doc_meta = build_doc_metadata(parsed)
    chunks = chunk_recursive(parsed, doc_meta, chunk_size=40, overlap=5, max_chunk_size=40)

    assert chunks
    assert all(c.metadata.sheet == "Sheet1" for c in chunks)
    for c in chunks:
        # every line in a chunk's body should be a whole "RowNA | RowNB" row, never a fragment
        for line in c.text.splitlines()[1:]:
            if line.strip():
                assert " | " in line
