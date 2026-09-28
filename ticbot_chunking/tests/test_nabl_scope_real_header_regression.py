"""Regression tests for the real NABL scope data-loss bug found during
retrieval evaluation: the real `NABL Scope-TC-5378 (1).pdf` document's table
header text is long, multi-line, real regulatory-document phrasing (not the
short labels the synthetic fixtures in test_nabl_scope_chunker.py use), which
`_canonical_columns`'s exact-match-only synonym lookup failed to recognize —
so every accredited-test row's discipline/material/parameter/method came out
blank, and `metadata.lab_location` was never populated at all (no extraction
function existed for it).

Uses the exact real header text and the first 3 real accredited-test rows
from that document (verbatim, from `local_pdf.parse_pdf_local()` output,
verified against the live document during the investigation) rather than a
synthetic fixture — a real regression test for a real, reproduced bug.
"""
from __future__ import annotations

from ticbot_chunking.chunkers.nabl_scope import _canonical_columns, chunk_nabl_scope
from ticbot_chunking.experiments.common import ParsedDoc
from ticbot_chunking.experiments.hybrid import chunk_hybrid
from ticbot_chunking.metadata.classifier import extract_lab_location
from ticbot_chunking.metadata.schema import DocumentMetadata
from ticbot_chunking.parsers.ir import BoundingBox, LayoutDocument, Page, Paragraph, Table, TableCell

# Verbatim real header row, exactly as pdfplumber extracts it from
# NABL Scope-TC-5378 1 (1).pdf (embedded newlines from real mid-phrase
# line-wrapping in the source PDF's table cells).
REAL_HEADER = [
    "S.No",
    "Discipline / Group",
    "Materials or Products tested",
    "Component, parameter or\ncharacteristic tested /\nSpecific Test Performed /\nTests or type of tests\nperformed",
    "Test Method Specification\nagainst which tests are\nperformed and / or the\ntechniques / equipment\nused",
]

# Verbatim real first 3 accredited-test rows from the same document (page 1).
REAL_ROWS = [
    ["1", "BIOLOGICAL- ANIMAL\nFOOD & FEED",
     "Corn gluten, Soybean, Ground nut, Rape seed &\npet food. Poultry stuffing, Guar meal, Soya bean\nMeal.",
     "Bacillus cereus\n(Enumeration)", "IS 5887-6:2012"],
    ["2", "BIOLOGICAL- ANIMAL\nFOOD & FEED",
     "Corn gluten, Soybean, Ground nut, Rape seed &\npet food. Poultry stuffing, Guar meal, Soya bean\nMeal.",
     "Bacillus cereus\n(Enumeration)", "ISO 7932:2004"],
    ["3", "BIOLOGICAL- ANIMAL\nFOOD & FEED",
     "Corn gluten, Soybean, Ground nut, Rape seed &\npet food. Poultry stuffing, Guar meal, Soya bean\nMeal.",
     "Clostridium perfringens\n(Detection)", "IS 5887-4:1999"],
]

# Verbatim real page-1 paragraph text (the lab identity line), from the same document.
REAL_LAB_LINE = "Laboratory Name : SGS INDIA PVT. LTD., 201, SUMEL II, S.G. HIGHWAY, AHMEDABAD, GUJARAT, INDIA"

# Verbatim real page-1 paragraph text (certificate/validity header block),
# from the same document — what pipeline._build_doc_metadata's real
# extraction functions run against for an accreditation_scope PDF.
REAL_CERT_LINE = (
    "Accreditation Standard ISO/IEC 17025:2017\nCertificate Number TC-5378 Page No 1 of 256\n"
    "Validity 01/04/2024 to 31/03/2026 Last Amended on 30/05/2025"
)


def _real_page1_paragraphs() -> list[Paragraph]:
    return [
        Paragraph(REAL_LAB_LINE, bounding_boxes=[BoundingBox(page_number=1)]),
        Paragraph(REAL_CERT_LINE, bounding_boxes=[BoundingBox(page_number=1)]),
    ]


def _real_table(page_number: int = 1) -> Table:
    cells = [
        TableCell(0, i, col, kind="columnHeader") for i, col in enumerate(REAL_HEADER)
    ]
    for row_idx, row in enumerate(REAL_ROWS, start=1):
        for col_idx, value in enumerate(row):
            cells.append(TableCell(row_idx, col_idx, value, page_number=page_number))
    return Table(row_count=len(REAL_ROWS) + 1, column_count=len(REAL_HEADER), cells=cells,
                 page_numbers=[page_number])


def _real_doc_meta() -> DocumentMetadata:
    return DocumentMetadata(
        doc_type="accreditation_scope", source_file="NABL Scope-TC-5378 1 (1).pdf",
        lab_location=extract_lab_location(REAL_LAB_LINE), certificate_no="TC-5378",
        accreditation_standard="ISO/IEC 17025: 2017", validity="01/04/2024 to 31/03/2026",
        last_amended="30/05/2025",
    )


def test_real_header_text_resolves_all_five_canonical_columns():
    # Before the fix, only "sno" resolved — discipline/material/parameter/
    # method were silently unmapped because the real header text doesn't
    # exactly match any COLUMN_SYNONYMS entry.
    cols = _canonical_columns(REAL_HEADER)
    assert set(cols.keys()) == {"sno", "discipline", "material", "parameter", "method"}


def test_extract_lab_location_from_real_page_text():
    assert extract_lab_location(REAL_LAB_LINE) == (
        "SGS INDIA PVT. LTD., 201, SUMEL II, S.G. HIGHWAY, AHMEDABAD, GUJARAT, INDIA"
    )


def test_extract_lab_location_returns_none_when_absent():
    assert extract_lab_location("No laboratory information on this page.") is None


def test_real_document_rows_are_not_silently_dropped_to_blank_records():
    doc = LayoutDocument(source_file="NABL Scope-TC-5378 1 (1).pdf", pages=[Page(1)], paragraphs=[],
                          tables=[_real_table()])
    chunks = chunk_nabl_scope(doc, _real_doc_meta(), "NABL Scope-TC-5378 1 (1)")
    scope_chunks = [c for c in chunks if c.metadata.chunk_type == "scope_records"]

    assert len(scope_chunks) == 1  # all 3 real rows share one discipline/material group
    chunk = scope_chunks[0]
    assert chunk.metadata.row_count == 3
    assert chunk.metadata.sno_range == "1–3"


def test_real_document_discipline_and_material_are_extracted_not_blank():
    doc = LayoutDocument(source_file="NABL Scope-TC-5378 1 (1).pdf", pages=[Page(1)], paragraphs=[],
                          tables=[_real_table()])
    chunk = chunk_nabl_scope(doc, _real_doc_meta(), "title")[0]

    assert chunk.metadata.discipline == "BIOLOGICAL- ANIMAL\nFOOD & FEED"
    assert "Corn gluten" in chunk.metadata.material


def test_real_document_method_and_parameter_appear_in_chunk_text_not_blank():
    doc = LayoutDocument(source_file="NABL Scope-TC-5378 1 (1).pdf", pages=[Page(1)], paragraphs=[],
                          tables=[_real_table()])
    chunk = chunk_nabl_scope(doc, _real_doc_meta(), "title")[0]

    assert "IS 5887-6:2012" in chunk.text  # method for S.No 1
    assert "ISO 7932:2004" in chunk.text   # method for S.No 2
    assert "Bacillus cereus" in chunk.text  # parameter
    # the bug produced literally "S.No 1: — Method:" for every row
    assert "S.No 1: — Method:" not in chunk.text


def test_certificate_and_lab_metadata_are_preserved_on_the_chunk():
    doc = LayoutDocument(source_file="NABL Scope-TC-5378 1 (1).pdf", pages=[Page(1)], paragraphs=[],
                          tables=[_real_table()])
    chunk = chunk_nabl_scope(doc, _real_doc_meta(), "title")[0]

    assert chunk.metadata.certificate_no == "TC-5378"
    assert chunk.metadata.lab_location == "SGS INDIA PVT. LTD., 201, SUMEL II, S.G. HIGHWAY, AHMEDABAD, GUJARAT, INDIA"
    assert chunk.metadata.validity == "01/04/2024 to 31/03/2026"
    assert "Lab: SGS INDIA PVT. LTD." in chunk.text
    assert "Certificate TC-5378" in chunk.text


def test_page_provenance_is_preserved_across_multiple_pages():
    doc = LayoutDocument(
        source_file="NABL Scope-TC-5378 1 (1).pdf", pages=[Page(1), Page(2)], paragraphs=[],
        tables=[_real_table(page_number=1), _real_table(page_number=2)],
    )
    chunks = [c for c in chunk_nabl_scope(doc, _real_doc_meta(), "title") if c.metadata.chunk_type == "scope_records"]

    pages_seen = {p for c in chunks for p in c.metadata.pages}
    assert pages_seen == {1, 2}


def test_facility_is_not_fabricated_as_permanent_facility_when_unknown():
    # The real document has no explicit Facility column and no "Facility:"
    # banner row — a previous version of this chunker silently defaulted the
    # DISPLAY text (though never metadata.facility itself) to "Permanent
    # Facility", presenting a guess as if it were extracted fact.
    doc = LayoutDocument(source_file="NABL Scope-TC-5378 1 (1).pdf", pages=[Page(1)], paragraphs=[],
                          tables=[_real_table()])
    chunk = chunk_nabl_scope(doc, _real_doc_meta(), "title")[0]

    assert chunk.metadata.facility is None
    assert "Facility: —" in chunk.text
    assert "Permanent Facility" not in chunk.text


def test_hybrid_strategy_retains_the_corrected_nabl_information():
    doc = LayoutDocument(source_file="NABL Scope-TC-5378 1 (1).pdf", pages=[Page(1)],
                          paragraphs=_real_page1_paragraphs(), tables=[_real_table()])
    parsed = ParsedDoc(source_file="sample-pdf-data/NABL Scope-TC-5378 1 (1).pdf",
                        local_path="/tmp/NABL Scope-TC-5378 1 (1).pdf", doc_type="accreditation_scope",
                        kind="pdf", layout_doc=doc)

    chunks = chunk_hybrid(parsed)
    scope_chunks = [c for c in chunks if c.metadata.chunk_type == "scope_records"]

    assert scope_chunks, "hybrid strategy produced no NABL scope_records chunks"
    chunk = scope_chunks[0]
    assert chunk.metadata.strategy == "hybrid"
    assert chunk.metadata.discipline == "BIOLOGICAL- ANIMAL\nFOOD & FEED"
    assert chunk.metadata.certificate_no == "TC-5378"
    assert chunk.metadata.lab_location == "SGS INDIA PVT. LTD., 201, SUMEL II, S.G. HIGHWAY, AHMEDABAD, GUJARAT, INDIA"
    assert "IS 5887-6:2012" in chunk.text
