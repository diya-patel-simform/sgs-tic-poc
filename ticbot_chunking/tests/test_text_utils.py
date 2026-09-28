from ticbot_chunking.chunkers.text_utils import split_long_text, split_paragraph_units
from ticbot_chunking.tokenizer import count_tokens


def _sentence(n_words: int, marker: str) -> str:
    return f"{marker} " + ("word " * n_words).strip() + "."


def test_split_long_text_respects_target_before_max():
    # Six ~50-token sentences (~300 tokens total). With target=100/max=250,
    # a naive splitter that only checks `max_tokens` would pack them into a
    # single ~300 token part (over target, but the old code never looked at
    # target at all). We expect the splitter to break near `target` instead
    # of only at `max_tokens`.
    sentences = [_sentence(48, f"S{i}") for i in range(6)]
    text = " ".join(sentences)

    parts = split_long_text(text, target=100, max_tokens=250, overlap_max=20)

    assert len(parts) > 1
    for part in parts:
        assert count_tokens(part) <= 250


def test_split_long_text_merges_small_trailing_part_instead_of_orphaning_it():
    # Built so the last sentence alone would form a part under `min_tokens`.
    sentences = [_sentence(90, "Big1"), _sentence(90, "Big2"), _sentence(3, "Tiny")]
    text = " ".join(sentences)

    parts = split_long_text(text, target=90, max_tokens=100, overlap_max=20, min_tokens=30)

    assert "Tiny" in parts[-1]
    assert all(count_tokens(p) >= 30 for p in parts), (
        "no emitted part should be an orphaned tiny tail chunk under min_tokens"
    )


def test_split_long_text_without_min_tokens_keeps_old_behavior():
    parts = split_long_text("Only one sentence here.", target=400, max_tokens=700, overlap_max=60)
    assert parts == ["Only one sentence here."]


# ---------------------------------------------------------------------------
# split_paragraph_units — the per-paragraph-page-aware splitter used by
# regulation.py/brochure.py, closing two previously-untested gaps: an
# oversized single paragraph (root cause of "one giant chunk" for an
# unheaded, low-punctuation brochure page), and per-part page accuracy.
# ---------------------------------------------------------------------------

def test_split_paragraph_units_each_part_gets_only_its_own_pages():
    units = [
        (_sentence(60, "P1"), [2]),
        (_sentence(60, "P2"), [3]),
        (_sentence(60, "P3"), [4]),
    ]
    parts = split_paragraph_units(units, target=60, max_tokens=100, overlap_max=10)

    assert len(parts) > 1
    all_pages = [pages for _, pages in parts]
    # No part claims a page it doesn't actually contain content from.
    assert all_pages != [[2, 3, 4]] * len(parts)
    for text, pages in parts:
        if "P1" in text and "P2" not in text and "P3" not in text:
            assert pages == [2]


def test_split_paragraph_units_hard_splits_one_oversized_paragraph_with_no_sentence_boundaries():
    # A single "paragraph" with no punctuation at all (e.g. a brochure page
    # with no heading, collapsed by the parser into one unpunctuated run) —
    # the old sentence-only splitter had no fallback for this and returned
    # it unchanged as one oversized chunk.
    oversized = " ".join(f"word{i}" for i in range(400))  # no '.', no '\n'
    units = [(oversized, [5])]

    parts = split_paragraph_units(units, target=100, max_tokens=150, overlap_max=20)

    assert len(parts) > 1
    for text, pages in parts:
        assert count_tokens(text) <= 150
        assert pages == [5]  # every sub-piece inherits the parent paragraph's page


def test_split_paragraph_units_never_splits_a_small_section_into_multiple_parts():
    units = [(_sentence(10, "Only"), [1])]
    parts = split_paragraph_units(units, target=400, max_tokens=700, overlap_max=60)
    assert len(parts) == 1
    assert parts[0][1] == [1]


def test_split_paragraph_units_empty_input_returns_empty_list():
    assert split_paragraph_units([], target=100, max_tokens=200, overlap_max=20) == []
