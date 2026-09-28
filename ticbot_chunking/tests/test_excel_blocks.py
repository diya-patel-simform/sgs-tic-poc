from openpyxl import Workbook
from openpyxl.worksheet.table import Table as XlTable, TableStyleInfo

from ticbot_chunking.chunkers.excel_blocks import chunk_workbook
from ticbot_chunking.metadata.schema import DocumentMetadata


def _contact_directory_meta() -> DocumentMetadata:
    return DocumentMetadata(
        doc_type="contact_directory",
        source_file="Key_Contacts.xlsx",
        access_class="internal",
        contains_pii=True,
    )


def test_record_table_block_detected_by_blank_row_boundaries(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Key Contacts"
    ws.append(["S. No.", "Name", "Role / Designation", "Location", "Email ID"])
    ws.append([1, "Contact 001", "Quality Manager", "Chennai", "contact001@example.com"])
    ws.append([2, "Contact 002", "Lab Head", "Ahmedabad", "contact002@example.com"])
    path = tmp_path / "contacts.xlsx"
    wb.save(path)

    chunks = chunk_workbook(str(path), _contact_directory_meta(), "H&N Food Testing India – Key Contacts")
    table_chunks = [c for c in chunks if c.metadata.chunk_type == "sheet_table"]

    assert len(table_chunks) == 1
    chunk = table_chunks[0]
    assert chunk.metadata.sheet == "Key Contacts"
    assert chunk.metadata.cell_range == "A1:E3"
    assert "Row 2 — S. No.: 1 | Name: Contact 001" in chunk.text
    assert "contact001@example.com" in chunk.text
    assert chunk.metadata.contains_pii is True
    assert chunk.metadata.access_class == "internal"


def test_two_blocks_on_same_sheet_are_kept_separate(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Category", "Count"])
    ws.append(["Quality Manager", 3])
    ws.append(["Lab Head", 2])
    ws.append([])  # blank row separates the two blocks
    ws.append(["Total contacts", 21])
    path = tmp_path / "summary.xlsx"
    wb.save(path)

    chunks = chunk_workbook(str(path), _contact_directory_meta(), "Contacts Summary")

    ranges = {c.metadata.cell_range for c in chunks}
    assert "A1:B3" in ranges
    assert "A5:B5" in ranges


def test_column_lists_block_keeps_columns_independent(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Food testing- parameters"
    ws.append(["E nose:", "E tongue:"])
    ws.append(["Detect off-odor", "Match products and formulations"])
    ws.append(["Ensure batch consistency", "Determine shelf life"])
    path = tmp_path / "capability.xlsx"
    wb.save(path)

    meta = DocumentMetadata(doc_type="capability_matrix", source_file="capability.xlsx")
    chunks = chunk_workbook(str(path), meta, "Food & Multi-lab Testing Capability")
    list_chunks = [c for c in chunks if c.metadata.chunk_type == "sheet_lists"]

    assert len(list_chunks) == 1
    text = list_chunks[0].text
    assert "E nose: Detect off-odor; Ensure batch consistency" in text
    assert "E tongue: Match products and formulations; Determine shelf life" in text
    assert "Independent lists" in text


def test_defined_excel_table_is_used_directly_and_not_double_counted(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Contacts"
    ws.append(["ID", "Name"])
    ws.append([1, "Contact 001"])
    ws.append([2, "Contact 002"])
    tbl = XlTable(displayName="HNIndiaContacts", ref="A1:B3")
    tbl.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9")
    ws.add_table(tbl)
    path = tmp_path / "defined_table.xlsx"
    wb.save(path)

    meta = DocumentMetadata(doc_type="contact_directory", source_file="defined_table.xlsx")
    chunks = chunk_workbook(str(path), meta, "Contacts Workbook")
    table_chunks = [c for c in chunks if c.metadata.cell_range == "A1:B3"]

    assert len(table_chunks) == 1
    assert table_chunks[0].metadata.excel_table == "HNIndiaContacts"


def test_tiny_decorative_single_cell_block_is_dropped(tmp_path):
    # A lone short label sitting off to the side, separated from the real
    # table by blank rows/columns, is exactly the kind of near-empty block
    # that shouldn't become its own chunk.
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Category", "Count"])
    ws.append(["Quality Manager", 3])
    ws.append(["Lab Head", 2])
    ws["D1"] = "Notes"  # isolated single-cell block, well below MIN_CONTENT_TOKENS
    path = tmp_path / "summary_with_stray_label.xlsx"
    wb.save(path)

    chunks = chunk_workbook(str(path), _contact_directory_meta(), "Contacts Summary")

    assert not any(c.metadata.cell_range == "D1:D1" for c in chunks)


def test_oversized_block_split_rows_get_their_own_cell_range_and_row_number(tmp_path):
    # Found against the real Key Contacts workbook: a record_table block
    # bigger than EXCEL_BLOCK.max_tokens gets split row-by-row, and every
    # piece used to be tagged with the *whole block's* cell_range and every
    # "Row N" label repeated the same (wrong) row number.
    wb = Workbook()
    ws = wb.active
    ws.title = "Key Contacts"
    ws.append(["S. No.", "Name", "Notes"])
    # Varied wording (not a repeated character, which tiktoken's BPE merges
    # into very few tokens) so a handful of rows blows past the 450-token limit.
    filler_words = ("quality regulatory testing capability discussion outcome review "
                     "approval pending standard method verification process schedule").split()
    for i in range(1, 6):
        note = " ".join(f"{w}{i}" for w in filler_words * 3)
        ws.append([i, f"Contact {i:03d}", note])
    path = tmp_path / "big_contacts.xlsx"
    wb.save(path)

    chunks = chunk_workbook(str(path), _contact_directory_meta(), "Contacts Workbook")
    table_chunks = [c for c in chunks if c.metadata.chunk_type == "sheet_table"]

    assert len(table_chunks) > 1, "fixture should actually force a split"
    ranges = [c.metadata.cell_range for c in table_chunks]
    assert len(set(ranges)) == len(ranges), f"split pieces must have distinct cell ranges, got {ranges}"

    # Each piece's row label must match the actual contact printed in it, not
    # a row number borrowed from wherever the block started.
    for c in table_chunks:
        for line in c.text.splitlines():
            if line.startswith("Row "):
                row_num = int(line.split(" ")[1].rstrip("—").strip())
                assert f"S. No.: {row_num - 1}" in line, line


def test_licensed_reference_column_drives_access_class(tmp_path):
    # Found against the real Regulatory Links Register workbook: the
    # "Licensed References" sheet has an explicit Access Classification
    # column (e.g. "Licensed" for full ISO/AOAC/ASTM/AOCS text) that was
    # previously ignored, leaving every chunk defaulted to "public".
    wb = Workbook()
    ws = wb.active
    ws.title = "Licensed References"
    # More than 2 columns so this stays classified as record_table (a 2-column
    # short-value table would hit the separate sheet_kv heuristic instead).
    ws.append(["Repository", "Permitted Content", "Access Classification", "Official Link"])
    ws.append(["ISO", "Standard number, title, scope", "Licensed", "https://www.iso.org"])
    ws.append(["AOAC International", "Method number, title", "Licensed", "https://www.aoac.org"])
    path = tmp_path / "licensed_refs.xlsx"
    wb.save(path)

    meta = DocumentMetadata(doc_type="reference_register", source_file="licensed_refs.xlsx")
    chunks = chunk_workbook(str(path), meta, "Regulatory Links Register")
    table_chunks = [c for c in chunks if c.metadata.chunk_type == "sheet_table"]

    assert len(table_chunks) == 1
    assert table_chunks[0].metadata.access_class == "licensed"


def test_mixed_access_classification_falls_back_to_document_default(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Mixed"
    ws.append(["Repository", "Permitted Content", "Access Classification", "Official Link"])
    ws.append(["Public Guide", "Everything", "Public", "https://example.com/guide"])
    ws.append(["ISO", "Standard number, title", "Licensed", "https://www.iso.org"])
    path = tmp_path / "mixed.xlsx"
    wb.save(path)

    meta = DocumentMetadata(doc_type="reference_register", source_file="mixed.xlsx")
    chunks = chunk_workbook(str(path), meta, "Mixed Register")
    table_chunks = [c for c in chunks if c.metadata.chunk_type == "sheet_table"]

    assert table_chunks[0].metadata.access_class == "public"  # DocumentMetadata default, not guessed


def test_lone_isolated_row_keeps_its_own_data_instead_of_being_read_as_a_header(tmp_path):
    # A single row isolated by blank rows/columns (e.g. a one-line summary
    # like "Total contacts: 21") has no separate header row above it.
    # classify_block/format_record_table assume grid[0] is a header and
    # data starts at grid[1:] — for a genuinely single-row block that used
    # to read the row's own values as a fake "Columns:" header, discarding
    # the row entirely with no data lines emitted.
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["A", "B", "C"])
    ws.append(["Widget", "10", "20"])
    ws.append([])
    ws.append(["Standalone", "5", "6", "7"])  # isolated single row, 4 columns -> record_table shape
    path = tmp_path / "single_row_block.xlsx"
    wb.save(path)

    meta = DocumentMetadata(doc_type="reference_register", source_file="single_row_block.xlsx")
    chunks = chunk_workbook(str(path), meta, "Single Row Workbook")

    lone_row_chunk = next(c for c in chunks if c.metadata.cell_range == "A4:D4")
    assert "Standalone" in lone_row_chunk.text
    assert "5" in lone_row_chunk.text and "6" in lone_row_chunk.text and "7" in lone_row_chunk.text
    assert "Columns:" not in lone_row_chunk.text  # not misread as a header-only chunk


def test_formula_block_is_flagged_as_computed(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Item", "Total"])
    ws.append(["Widgets", "=1+2"])
    path = tmp_path / "formulas.xlsx"
    wb.save(path)

    meta = DocumentMetadata(doc_type="reference_register", source_file="formulas.xlsx")
    chunks = chunk_workbook(str(path), meta, "Formulas Workbook")

    assert any(c.metadata.quality_flags and "computed_values" in c.metadata.quality_flags for c in chunks)
