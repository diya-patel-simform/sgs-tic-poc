from ticbot_chunking.chunkers.brochure import chunk_brochure, fix_reading_order
from ticbot_chunking.metadata.schema import DocumentMetadata
from ticbot_chunking.parsers.ir import (
    BoundingBox,
    Figure,
    LayoutDocument,
    Page,
    Paragraph,
    ROLE_SECTION_HEADING,
    ROLE_TITLE,
)


def _doc_meta() -> DocumentMetadata:
    return DocumentMetadata(doc_type="brochure", source_file="SGS_Molecular_Catalog_pages_3-4-12.pdf")


def test_fix_reading_order_reads_columns_not_raw_top_to_bottom():
    # Two columns on one page: left column has two short lines top-to-bottom,
    # right column has two short lines top-to-bottom. A naive top-to-bottom-only
    # sort by y would interleave "Left1, Right1, Left2, Right2" if the right
    # column's first line sits higher than the left column's second line.
    left1 = Paragraph("Left line 1", bounding_boxes=[BoundingBox(page_number=1, x=0, y=0, width=40)])
    right1 = Paragraph("Right line 1", bounding_boxes=[BoundingBox(page_number=1, x=50, y=5, width=40)])
    left2 = Paragraph("Left line 2", bounding_boxes=[BoundingBox(page_number=1, x=0, y=20, width=40)])
    right2 = Paragraph("Right line 2", bounding_boxes=[BoundingBox(page_number=1, x=50, y=25, width=40)])

    ordered = fix_reading_order([right1, left1, right2, left2])
    texts = [p.text for p in ordered]

    assert texts == ["Left line 1", "Left line 2", "Right line 1", "Right line 2"]


def test_figure_chunk_matches_sample_shape_and_decorative_figures_are_dropped():
    doc = LayoutDocument(
        source_file="SGS_Molecular_Catalog_pages_3-4-12.pdf",
        pages=[Page(16)],
        paragraphs=[
            Paragraph("SGS Molecular – Service Catalog", role=ROLE_TITLE, bounding_boxes=[BoundingBox(1)]),
            Paragraph("ALL SPECIES ID SOFTWARE", role=ROLE_SECTION_HEADING, bounding_boxes=[BoundingBox(16)]),
        ],
        tables=[],
        figures=[
            Figure(
                caption=None,
                page_number=16,
                inline_text_fragments=[
                    "DNA Praparation 1-16 hours", "Library Praparation 4 hours",
                    "Template Praparation 12 hours", "Sequencing <5 hours", "Data Analysis -1.5 hours",
                ],
            ),
            Figure(caption=None, page_number=16, inline_text_fragments=[]),  # decorative photo, no text
        ],
    )

    chunks = chunk_brochure(doc, _doc_meta())
    figure_chunks = [c for c in chunks if c.metadata.chunk_type == "figure_text"]

    assert len(figure_chunks) == 1
    assert figure_chunks[0].metadata.pages == [16]
    assert figure_chunks[0].metadata.section_path == "SGS Molecular – Service Catalog › ALL SPECIES ID SOFTWARE"
    assert "DNA Praparation 1-16 hours" in figure_chunks[0].text
    assert figure_chunks[0].text.startswith("[Brochure / Service catalog]")


def test_figure_with_only_a_decorative_caption_word_is_dropped():
    # Has a caption (passes the has-caption-or-text classifier) but the
    # caption itself is a single decorative word, not real content — the
    # minimum-content rule (section 2 footnote) should still drop it.
    doc = LayoutDocument(
        source_file="SGS_Molecular_Catalog_pages_3-4-12.pdf",
        pages=[Page(4)],
        paragraphs=[
            Paragraph("SGS Molecular – Service Catalog", role=ROLE_TITLE, bounding_boxes=[BoundingBox(1)]),
        ],
        tables=[],
        figures=[Figure(caption="Photo", page_number=4, inline_text_fragments=[])],
    )

    chunks = chunk_brochure(doc, _doc_meta())
    figure_chunks = [c for c in chunks if c.metadata.chunk_type == "figure_text"]

    assert figure_chunks == []


def test_narrative_chunk_gets_breadcrumb_header():
    doc = LayoutDocument(
        source_file="SGS_Molecular_Catalog_pages_3-4-12.pdf",
        pages=[Page(3)],
        paragraphs=[
            Paragraph("SGS Molecular – Service Catalog", role=ROLE_TITLE, bounding_boxes=[BoundingBox(1)]),
            Paragraph("Species Identification", role=ROLE_SECTION_HEADING, bounding_boxes=[BoundingBox(3)]),
            Paragraph(
                "Our DNA barcoding service identifies the species present in a sample with high confidence, "
                "supporting food fraud investigations and regulatory compliance across the supply chain.",
                bounding_boxes=[BoundingBox(3)],
            ),
        ],
        tables=[],
    )

    chunks = chunk_brochure(doc, _doc_meta())
    text_chunks = [c for c in chunks if c.metadata.chunk_type == "text"]

    assert len(text_chunks) == 1
    assert text_chunks[0].text.startswith("[Brochure / Service catalog] SGS Molecular – Service Catalog › Species Identification")
