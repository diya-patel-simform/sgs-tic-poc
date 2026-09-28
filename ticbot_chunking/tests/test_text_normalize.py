"""Tests for parsers/text_normalize.py — letter-spacing artifact collapsing.
Deliberately includes several "must NOT collapse" cases alongside the real
manual-testing example, since a too-aggressive normalizer would corrupt
legitimate ALL-CAPS section references (e.g. "ANNEXURE A SCOPE").
"""
from __future__ import annotations

from ticbot_chunking.parsers.text_normalize import normalize_letter_spacing, normalize_paragraphs


def test_collapses_the_real_manual_testing_example():
    assert normalize_letter_spacing("C ONTAMINANTS , T OXINS A ND R ESIDUES") == "CONTAMINANTS, TOXINS AND RESIDUES"


def test_collapses_a_fully_letter_spaced_run():
    assert normalize_letter_spacing("C O N T A M I N A N T S") == "CONTAMINANTS"


def test_does_not_collapse_a_single_legitimate_section_letter_reference():
    # Exactly one "capital letter, space, all-caps word" occurrence — a real
    # section reference, not a repeated artifact.
    assert normalize_letter_spacing("ANNEXURE A SCOPE OF ACCREDITATION") == "ANNEXURE A SCOPE OF ACCREDITATION"
    assert normalize_letter_spacing("PART B RULES AND REGULATIONS") == "PART B RULES AND REGULATIONS"


def test_does_not_touch_ordinary_prose():
    text = "The quick brown fox jumps over the lazy dog."
    assert normalize_letter_spacing(text) == text


def test_does_not_touch_a_chapter_heading():
    text = "CHAPTER 2 – Contaminants, Toxins And Residues"
    assert normalize_letter_spacing(text) == text


def test_empty_and_none_safe():
    assert normalize_letter_spacing("") == ""


def test_is_idempotent():
    once = normalize_letter_spacing("C ONTAMINANTS , T OXINS A ND R ESIDUES")
    twice = normalize_letter_spacing(once)
    assert once == twice


def test_normalize_paragraphs_mutates_in_place():
    from ticbot_chunking.parsers.ir import Paragraph

    paragraphs = [Paragraph(text="C ONTAMINANTS , T OXINS A ND R ESIDUES", role="text")]
    normalize_paragraphs(paragraphs)
    assert paragraphs[0].text == "CONTAMINANTS, TOXINS AND RESIDUES"
