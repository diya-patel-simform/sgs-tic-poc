from ticbot_chunking.search.chunk_id import compute_chunk_id
from ticbot_chunking.search.document_mapper import build_search_document
from ticbot_chunking.search.schema import STRATEGY_INDEX_NAMES, build_metadata_fields


def _row(**metadata_overrides):
    metadata = {
        "chunk_type": "text",
        "doc_type": "regulation",
        "source_file": "sample-pdf-data/Contaminants_Regulations.pdf",
        "pages": [3, 4],
        "section_path": "Chapter 2 > 2.3",
        "section_number": "2.3.1",
        "authority": "FSSAI",
        "parser": "local_pdf",
        "access_class": "public",
        "contains_pii": False,
    }
    metadata.update(metadata_overrides)
    return {"text": "Some chunk text about contaminant limits.", "metadata": metadata}


def test_maps_every_schema_metadata_field_that_has_a_value():
    row = _row()
    doc = build_search_document(row, "fixed", 5, [0.1, 0.2, 0.3])

    assert doc["text"] == row["text"]
    assert doc["chunking_strategy"] == "fixed"
    assert doc["document_type"] == "regulation"  # renamed from doc_type
    assert doc["chunk_type"] == "text"
    assert doc["source_file"] == "sample-pdf-data/Contaminants_Regulations.pdf"
    assert doc["blob_path"] == "sample-pdf-data/Contaminants_Regulations.pdf"  # alias of source_file
    assert doc["parser_used"] == "local_pdf"  # renamed from parser
    assert doc["pages"] == [3, 4]
    assert doc["section_path"] == "Chapter 2 > 2.3"
    assert doc["section_number"] == "2.3.1"
    assert doc["authority"] == "FSSAI"
    assert doc["access_class"] == "public"
    assert doc["contains_pii"] is False
    assert doc["chunk_vector"] == [0.1, 0.2, 0.3]


def test_produces_a_stable_chunk_id_matching_compute_chunk_id():
    row = _row()
    doc = build_search_document(row, "fixed", 5, [0.1])
    expected = compute_chunk_id("fixed", row["metadata"]["source_file"], 5, row["text"])
    assert doc["chunk_id"] == expected


def test_every_output_field_name_is_a_real_schema_field():
    row = _row(sheet="Sheet1", cell_range="A1:B10", discipline="Chemical", material="Water",
               facility="Lab A", certificate_no="TC-1234", lab_location="Mumbai")
    doc = build_search_document(row, "hybrid", 0, [0.1])

    schema_field_names = {f.name for f in build_metadata_fields()} | {"chunk_id", "text", "chunk_vector"}
    assert set(doc.keys()) <= schema_field_names


def test_omits_fields_that_are_absent_from_metadata_rather_than_nulling_them():
    row = _row()  # no sheet, cell_range, discipline, material, facility, certificate_no, lab_location
    doc = build_search_document(row, "fixed", 0, [0.1])

    for absent_field in ("sheet", "cell_range", "discipline", "material", "facility",
                         "certificate_no", "lab_location"):
        assert absent_field not in doc


def test_does_not_mix_index_names_across_strategies():
    assert len(set(STRATEGY_INDEX_NAMES.values())) == 4


def test_maps_page_start_end_printed_label_and_doc_title():
    row = _row(page_start=3, page_end=4, printed_page_label="4/20", doc_title="Real Document Title")
    doc = build_search_document(row, "hybrid", 0, [0.1])

    assert doc["page_start"] == 3
    assert doc["page_end"] == 4
    assert doc["printed_page_label"] == "4/20"
    assert doc["doc_title"] == "Real Document Title"


def test_maps_embed_text_when_present():
    row = _row()
    row["embed_text"] = "Real Document Title | Section | Page 3\nshort embed-only body"
    doc = build_search_document(row, "hybrid", 0, [0.1])

    assert doc["embed_text"] == "Real Document Title | Section | Page 3\nshort embed-only body"


def test_omits_embed_text_when_absent():
    row = _row()  # no top-level "embed_text" key at all
    doc = build_search_document(row, "hybrid", 0, [0.1])
    assert "embed_text" not in doc


def test_excel_style_metadata_is_preserved():
    row = {
        "text": "Sheet content",
        "metadata": {
            "chunk_type": "sheet_table", "doc_type": "capability_matrix",
            "source_file": "sample-xlsx-data/Food Testing capability.xlsx",
            "sheet": "Sheet1", "cell_range": "A1:D20", "parser": "excel_parser",
            "access_class": "public", "contains_pii": False,
        },
    }
    doc = build_search_document(row, "hybrid", 2, [0.5])
    assert doc["sheet"] == "Sheet1"
    assert doc["cell_range"] == "A1:D20"
    assert doc["parser_used"] == "excel_parser"
    assert doc["document_type"] == "capability_matrix"
