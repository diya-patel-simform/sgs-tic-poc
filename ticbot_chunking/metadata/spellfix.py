"""A small, curated spell-fix list applied only when building a chunk's
`embed_text` (Task 3.8) — never the citation-authoritative `text` field,
which always preserves the source PDF's original wording exactly, typos
included. Deliberately not a general-purpose spellchecker: regulatory and
technical documents are full of legitimate uncommon terms, codes, and
proper nouns a generic spellchecker would "correct" incorrectly. Only
confirmed real source typos go in this list.
"""
from __future__ import annotations

import re

SPELL_FIXES = {
    "pipeapple": "pineapple",
    "patially": "partially",
    "alignates": "alginates",
    "multilple": "multiple",
}

_FIX_PATTERNS = [(re.compile(re.escape(wrong), re.IGNORECASE), right) for wrong, right in SPELL_FIXES.items()]


def spell_normalize(text: str) -> str:
    result = text
    for pattern, right in _FIX_PATTERNS:
        result = pattern.sub(right, result)
    return result
