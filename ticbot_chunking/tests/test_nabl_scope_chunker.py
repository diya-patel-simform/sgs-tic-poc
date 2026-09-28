from ticbot_chunking.chunkers.nabl_scope import chunk_nabl_scope
from ticbot_chunking.metadata.schema import DocumentMetadata
from ticbot_chunking.parsers.ir import LayoutDocument, Page, Table, TableCell


def _doc_meta() -> DocumentMetadata:
    return DocumentMetadata(
        doc_type="accreditation_scope",
        source_file="NABL_Scope_Chennai.pdf",
        lab_location="Chennai",
        certificate_no="TC-5006",
        accreditation_standard="ISO/IEC 17025: 2017",
        validity="20.11.2025 to 19.11.2027",
        last_amended="02.02.2026",
    )


def test_explicit_discipline_material_columns_group_records_and_carry_forward():
    cells = [
        TableCell(0, 0, "S.No", kind="columnHeader"),
        TableCell(0, 1, "Discipline/Group", kind="columnHeader"),
        TableCell(0, 2, "Material/Product", kind="columnHeader"),
        TableCell(0, 3, "Parameter", kind="columnHeader"),
        TableCell(0, 4, "Method", kind="columnHeader"),
        TableCell(1, 0, "22"), TableCell(1, 1, "BIOLOGICAL/ ANIMAL FOOD AND FEED"),
        TableCell(1, 2, "Fish, Shrimps, Prawn feed"), TableCell(1, 3, "Enterobacteriaceae"),
        TableCell(1, 4, "ISO 21528-1: 2017"),
        TableCell(2, 0, "25"), TableCell(2, 1, "BIOLOGICAL/ ANIMAL FOOD AND FEED"),
        TableCell(2, 2, "Fish, Shrimps, Prawn feed"), TableCell(2, 3, "Escherichia coli"),
        TableCell(2, 4, "ISO 7251: 2005"),
        TableCell(3, 0, "31"), TableCell(3, 1, "BIOLOGICAL/ ANIMAL FOOD AND FEED"),
        TableCell(3, 2, "Fish, Shrimps, Prawn feed"), TableCell(3, 3, "Faecal streptococci"),
        TableCell(3, 4, "APHA 5th Edn Chapter 10: 2015"),
    ]
    table = Table(row_count=4, column_count=5, cells=cells, page_numbers=[3, 4])
    doc = LayoutDocument(
        source_file="NABL_Scope_Chennai.pdf",
        pages=[Page(3), Page(4)],
        paragraphs=[],
        tables=[table],
    )

    chunks = chunk_nabl_scope(doc, _doc_meta(), "NABL Scope – SGS India Multi-Laboratory, Chennai (TC-5006)")
    scope_chunks = [c for c in chunks if c.metadata.chunk_type == "scope_records"]

    assert len(scope_chunks) == 1
    chunk = scope_chunks[0]
    assert chunk.metadata.discipline == "BIOLOGICAL/ ANIMAL FOOD AND FEED"
    assert chunk.metadata.material == "Fish, Shrimps, Prawn feed"
    assert chunk.metadata.sno_range == "22–31"
    assert chunk.metadata.row_count == 3
    assert chunk.metadata.certificate_no == "TC-5006"
    assert "S.No 22: Enterobacteriaceae — Method: ISO 21528-1: 2017" in chunk.text
    assert "S.No 31: Faecal streptococci — Method: APHA 5th Edn Chapter 10: 2015" in chunk.text
    assert "Discipline/Group: BIOLOGICAL/ ANIMAL FOOD AND FEED" in chunk.text
    assert "Certificate TC-5006" in chunk.text


def test_banner_row_fallback_when_no_explicit_discipline_columns():
    cells = [
        TableCell(0, 0, "S.No", kind="columnHeader"),
        TableCell(0, 1, "Parameter", kind="columnHeader"),
        TableCell(0, 2, "Method", kind="columnHeader"),
        TableCell(1, 0, "Facility: Permanent Facility | Discipline/Group: CHEMICAL | Material/Product: Spices",
                  column_span=3),
        TableCell(2, 0, "1"), TableCell(2, 1, "Moisture"), TableCell(2, 2, "AOAC 925.10"),
        TableCell(3, 0, "2"), TableCell(3, 1, "Total Ash"), TableCell(3, 2, "AOAC 923.03"),
    ]
    table = Table(row_count=4, column_count=3, cells=cells, page_numbers=[10])
    doc = LayoutDocument(source_file="NABL_Scope_Ahmedabad.pdf", pages=[Page(10)], paragraphs=[], tables=[table])

    chunks = chunk_nabl_scope(doc, _doc_meta(), "NABL Scope – Ahmedabad")
    scope_chunks = [c for c in chunks if c.metadata.chunk_type == "scope_records"]

    assert len(scope_chunks) == 1
    assert scope_chunks[0].metadata.discipline == "CHEMICAL"
    assert scope_chunks[0].metadata.material == "Spices"
    assert scope_chunks[0].metadata.row_count == 2


def test_blank_records_are_excluded_not_indexed():
    # Mirrors section 6.6: Chennai S.No 3816-3820 are blank in the source PDF
    # (no parameter, no method) and must be flagged/excluded, not indexed as
    # empty accredited-test records.
    cells = [
        TableCell(0, 0, "S.No", kind="columnHeader"),
        TableCell(0, 1, "Parameter", kind="columnHeader"),
        TableCell(0, 2, "Method", kind="columnHeader"),
        TableCell(1, 0, "Facility: Permanent Facility | Discipline/Group: CHEMICAL | Material/Product: Spices",
                  column_span=3),
        TableCell(2, 0, "1"), TableCell(2, 1, "Moisture"), TableCell(2, 2, "AOAC 925.10"),
        TableCell(3, 0, "2"), TableCell(3, 1, ""), TableCell(3, 2, ""),  # blank source row
        TableCell(4, 0, "3"), TableCell(4, 1, "Total Ash"), TableCell(4, 2, "AOAC 923.03"),
    ]
    table = Table(row_count=5, column_count=3, cells=cells, page_numbers=[10])
    doc = LayoutDocument(source_file="NABL_Scope_Ahmedabad.pdf", pages=[Page(10)], paragraphs=[], tables=[table])

    chunks = chunk_nabl_scope(doc, _doc_meta(), "NABL Scope – Ahmedabad")
    scope_chunks = [c for c in chunks if c.metadata.chunk_type == "scope_records"]

    assert len(scope_chunks) == 1
    assert scope_chunks[0].metadata.row_count == 2
    assert "S.No 2" not in scope_chunks[0].text


def test_scanned_certificate_page_becomes_its_own_chunk():
    doc = LayoutDocument(
        source_file="NABL_Scope_Chennai.pdf",
        pages=[Page(1, is_scanned=True)],
        paragraphs=[],
        tables=[],
    )
    from ticbot_chunking.parsers.ir import Paragraph

    doc.paragraphs.append(Paragraph("Certificate of Accreditation ... TC-5006", bounding_boxes=[]))
    # attach page 1 to the paragraph's bounding boxes
    from ticbot_chunking.parsers.ir import BoundingBox
    doc.paragraphs[0].bounding_boxes = [BoundingBox(page_number=1)]

    chunks = chunk_nabl_scope(doc, _doc_meta(), "NABL Scope – Chennai")
    cert_chunks = [c for c in chunks if c.metadata.chunk_type == "certificate"]
    assert len(cert_chunks) == 1
    assert cert_chunks[0].metadata.pages == [1]
