from ticbot_chunking.chunkers.section_numbering import SectionTracker


def test_chapter_and_nested_numbering_breadcrumb():
    tracker = SectionTracker("FSS (Contaminants, Toxins and Residues) Regulations, 2011")
    tracker.ingest_heading("CHAPTER 2 – Contaminants, Toxins And Residues")
    tracker.ingest_heading("2.3 Residues")
    tracker.ingest_heading("2.3.1 Restriction on the use of insecticides")

    assert tracker.section_number == "2.3.1"
    assert tracker.section_path == (
        "FSS (Contaminants, Toxins and Residues) Regulations, 2011 › "
        "CHAPTER 2 – Contaminants, Toxins And Residues › "
        "2.3: Residues › 2.3.1: Restriction on the use of insecticides"
    )
    assert not tracker.in_annexure


def test_sibling_sections_share_parent_key():
    tracker = SectionTracker("Doc")
    tracker.ingest_heading("CHAPTER 2 – Contaminants")
    tracker.ingest_heading("2.1 Pesticides")
    parent_of_first = tracker.parent_key
    tracker.ingest_heading("2.2 Residues")
    parent_of_second = tracker.parent_key

    assert parent_of_first == parent_of_second


def test_returning_to_shallower_depth_pops_stack():
    tracker = SectionTracker("Doc")
    tracker.ingest_heading("CHAPTER 2 – Contaminants")
    tracker.ingest_heading("2.3 Residues")
    tracker.ingest_heading("2.3.1 Restriction")
    tracker.ingest_heading("2.4 Additives")

    assert tracker.section_number == "2.4"
    assert "2.3.1" not in tracker.section_path


def test_annexure_opens_new_top_level_branch():
    tracker = SectionTracker("NABL Scope – SGS India Chennai")
    tracker.ingest_heading("Annexure A")

    assert tracker.in_annexure
    assert tracker.annexure_label == "Annexure A"


def test_ingest_top_level_resets_stack_and_opens_depth_one():
    # A brochure's per-page title (e.g. "Crop Science") — no numbering
    # convention at all, but should behave like CHAPTER n's own reset.
    tracker = SectionTracker("SGS Health & Nutrition")
    tracker.ingest_heading("CHAPTER 2 – Contaminants")
    tracker.ingest_heading("2.3.1 Restriction")

    tracker.ingest_top_level("Crop Science")

    assert tracker.section_path == "SGS Health & Nutrition › Crop Science"
    assert tracker.depth == 1


def test_ingest_top_level_then_subheading_nests_one_level_below():
    tracker = SectionTracker("SGS Molecular Service Catalog")
    tracker.ingest_top_level("Identification of organisms by DNA sequencing")
    tracker.ingest_heading("Sanger sequencing method")

    assert tracker.section_path == (
        "SGS Molecular Service Catalog › Identification of organisms by DNA sequencing "
        "› Sanger sequencing method"
    )


def test_ingest_heading_on_garbled_letter_spaced_text_does_not_crash():
    # Upstream corruption (e.g. a letter-spaced heading that the
    # normalization pass missed) must never crash the tracker. It isn't
    # expected to correctly infer "2.3.1" as the number here — the real fix
    # for letter-spacing is the upstream text_normalize pass, applied
    # before headings ever reach this tracker — but a garbled heading like
    # this must still produce *some* well-formed, non-crashing result.
    tracker = SectionTracker("Doc")
    tracker.ingest_heading("2 . 3 . 1   R e s t r i c t i o n")

    assert tracker.section_path.startswith("Doc › ")
    assert tracker.depth >= 1
