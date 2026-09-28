"""Shared narrative-text splitting, used by both the regulation and brochure
chunkers (section 3, "Inside a long section split into parts: one sentence").

`split_paragraph_units` operates on a section's own paragraphs (each with
its own page numbers already attached) rather than one flattened string —
this is what lets every split PART carry only the page numbers of the
paragraphs it actually contains, instead of the whole section's page range
(see chunkers/regulation.py and chunkers/brochure.py). A paragraph that
alone exceeds `max_tokens` (e.g. a whole unheaded brochure page with little
punctuation, collapsed into one "paragraph") is recursively hard-split at
progressively finer natural boundaries — the same cascade
`experiments/recursive.py` already uses for its own oversized-unit case —
rather than being left as one oversized chunk.
"""
from __future__ import annotations

from ticbot_chunking.tokenizer import count_tokens

MIN_CONTENT_TOKENS = 5

# Coarsest to finest — paragraph, line, sentence, word. Ported from
# experiments/recursive.py's proven oversized-unit fallback, which
# chunkers/text_utils.py's own splitter never had (the confirmed root cause
# of "one giant chunk" for a whole unheaded/low-punctuation document).
SEPARATORS = ["\n\n", "\n", ". ", " "]


def _split_text_recursive(text: str, max_tokens: int, seps: list[str]) -> list[str]:
    if count_tokens(text) <= max_tokens or not seps:
        return [text] if text.strip() else []

    sep = seps[0]
    raw_parts = text.split(sep)
    parts = [p + sep if i < len(raw_parts) - 1 else p for i, p in enumerate(raw_parts)]

    pieces: list[str] = []
    for part in parts:
        if not part.strip():
            continue
        if count_tokens(part) > max_tokens:
            pieces.extend(_split_text_recursive(part, max_tokens, seps[1:]))
        else:
            pieces.append(part)
    return pieces


def split_paragraph_units(
    units: list[tuple[str, list[int]]], target: int, max_tokens: int, overlap_max: int, min_tokens: int = 0
) -> list[tuple[str, list[int]]]:
    """Paragraph-boundary-first greedy splitter over `(paragraph_text, pages)`
    units. Packs whole paragraphs up to `target` tokens per part (falling
    back to `max_tokens` only when a part hasn't reached `target` yet),
    carries the last paragraph forward as overlap when starting a new part,
    and folds a trailing part smaller than `min_tokens` back into the
    previous part rather than emitting an orphan tiny chunk — the same
    packing contract the old sentence-level `split_long_text` had. Any
    single paragraph that alone exceeds `max_tokens` is hard-split first via
    `_split_text_recursive`, inheriting that paragraph's own pages
    unchanged (no finer page signal exists below paragraph granularity).

    Returns one `(text, pages)` pair per output part, `pages` computed only
    from the units actually included in that part.
    """
    if not units:
        return []

    expanded: list[tuple[str, list[int]]] = []
    for text, pages in units:
        if count_tokens(text) > max_tokens:
            for piece in _split_text_recursive(text, max_tokens, SEPARATORS):
                expanded.append((piece, pages))
        else:
            expanded.append((text, pages))

    parts: list[list[tuple[str, list[int]]]] = []
    current: list[tuple[str, list[int]]] = []
    current_tokens = 0
    for text, pages in expanded:
        t = count_tokens(text)
        over_target = current and current_tokens + t > target
        over_max = current and current_tokens + t > max_tokens
        if over_max or (over_target and current_tokens >= target):
            parts.append(current)
            overlap_unit = current[-1]
            if count_tokens(overlap_unit[0]) <= overlap_max:
                current = [overlap_unit]
                current_tokens = count_tokens(overlap_unit[0])
            else:
                current = []
                current_tokens = 0
        current.append((text, pages))
        current_tokens += t
    if current:
        parts.append(current)

    if min_tokens and len(parts) > 1:
        last_tokens = sum(count_tokens(u[0]) for u in parts[-1])
        if last_tokens < min_tokens:
            parts[-2].extend(parts[-1])
            parts.pop()

    result: list[tuple[str, list[int]]] = []
    for part in parts:
        text = "\n\n".join(u[0] for u in part)
        pages = sorted({p for u in part for p in u[1]})
        result.append((text, pages))
    return result


def split_long_text(full_text: str, target: int, max_tokens: int, overlap_max: int, min_tokens: int = 0) -> list[str]:
    """Plain-string wrapper over `split_paragraph_units` for callers with no
    per-paragraph page information to preserve (kept for backward
    compatibility; regulation.py/brochure.py use `split_paragraph_units`
    directly instead, for accurate per-part pages)."""
    units = [(p, []) for p in full_text.split("\n\n") if p.strip()] or [(full_text, [])]
    parts = split_paragraph_units(units, target, max_tokens, overlap_max, min_tokens=min_tokens)
    return [text for text, _ in parts]
