"""Parser-agnostic text normalization: collapses letter-spacing artifacts
(individual glyphs rendered with wide tracking) that would otherwise
corrupt heading/section-numbering detection and show up as visible junk in
chunk text. Applied once, after parsing (see `parsers/page_router.py`,
right after `_merge`), to every paragraph's text regardless of which
parser produced it — letter-spacing is a source-PDF/OCR-rendering
property, not something either parser (local_pdf.py, azure_docintel.py)
is uniquely responsible for.

Two independent patterns are collapsed, since a real letter-spaced heading
can come through either way depending on how the source PDF places
individual glyphs:

1. A run of >= MIN_RUN_LETTERS single-letter tokens, space-separated, e.g.
   "C O N T A M I N A N T S" -> "CONTAMINANTS".
2. A single leading capital letter split off from the rest of an all-caps
   word by one space, e.g. "C ONTAMINANTS" -> "CONTAMINANTS" — the exact
   real-world artifact manual testing found ("C ONTAMINANTS , T OXINS A ND
   R ESIDUES"). This pattern alone is deliberately NOT collapsed on a
   single occurrence — legitimate text can contain one instance of "capital
   letter, space, all-caps word" (e.g. "ANNEXURE A SCOPE", "PART B RULES"),
   and collapsing that would corrupt a real, correctly-formed heading. Only
   collapsed when it recurs >= MIN_SPLIT_INITIAL_OCCURRENCES times in the
   same paragraph — a genuine letter-spacing artifact repeats throughout a
   whole heading, a legitimate section-letter reference does not.
"""
from __future__ import annotations

import re

MIN_RUN_LETTERS = 4
MIN_SPLIT_INITIAL_OCCURRENCES = 2

# Pattern 1: a run of single-letter "words" separated by spaces.
_LETTER_RUN_RE = re.compile(r"\b(?:[A-Za-z]\s+){" + str(MIN_RUN_LETTERS - 1) + r",}[A-Za-z]\b")

# Pattern 2: an isolated single capital letter, one space, then a run of
# >= 2 further uppercase letters.
_SPLIT_INITIAL_RE = re.compile(r"\b([A-Z])\s+(?=[A-Z]{2,}\b)")

# A space immediately before a comma/period is the same underlying
# artifact family (a punctuation glyph rendered as its own tracked-out
# "word") — only cleaned up alongside an actual letter-spacing collapse
# (see normalize_letter_spacing), never unconditionally, since a lone
# " ," could plausibly appear for unrelated reasons elsewhere.
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.])")


def _collapse_whitespace(match: re.Match) -> str:
    return re.sub(r"\s+", "", match.group(0))


def normalize_letter_spacing(text: str) -> str:
    """Collapses both letter-spacing patterns described in the module
    docstring. Idempotent — running it twice on already-normal text is a
    no-op."""
    if not text:
        return text

    original = text
    text = _LETTER_RUN_RE.sub(_collapse_whitespace, text)

    occurrences = list(_SPLIT_INITIAL_RE.finditer(text))
    if len(occurrences) >= MIN_SPLIT_INITIAL_OCCURRENCES:
        text = _SPLIT_INITIAL_RE.sub(lambda m: m.group(1), text)

    if text != original:
        text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)

    return text


def normalize_paragraphs(paragraphs) -> None:
    """Normalizes every paragraph's `.text` in place. `Paragraph` is a plain
    mutable dataclass and every caller already holds this same list
    reference, so mutating in place (rather than returning a new list) is
    sufficient and avoids the caller needing to thread a replacement
    LayoutDocument back through."""
    for p in paragraphs:
        if p.text:
            p.text = normalize_letter_spacing(p.text)
