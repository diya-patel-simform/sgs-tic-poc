"""Parses heading text into a numbering-aware hierarchy: CHAPTER n -> 2.3 ->
2.3.1, plus Annexure/Appendix/Schedule as a new top-level branch.

Implements section 4 ("How document hierarchy is preserved") of
TICbot_Chunking_Strategy_Answers.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CHAPTER_RE = re.compile(r"^\s*CHAPTER\s+([0-9IVXLC]+)\s*[–\-:]?\s*(.*)$", re.IGNORECASE)
NUMBERED_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*[.:\-–]?\s*(.*)$")
ANNEXURE_RE = re.compile(
    r"^\s*(Annexure|Appendix|Schedule)\b\s*([A-Za-z0-9]*)\s*[.:\-–]?\s*(.*)$", re.IGNORECASE
)


@dataclass
class SectionNode:
    number: str | None
    title: str
    depth: int
    is_annexure: bool = False

    def formatted(self) -> str:
        if self.is_annexure:
            return f"{self.number} {self.title}".strip()
        if self.number and self.number.upper().startswith("CHAPTER"):
            return f"{self.number} – {self.title}" if self.title else self.number
        if self.number:
            return f"{self.number}: {self.title}" if self.title else self.number
        return self.title


def parse_heading(text: str, current_depth: int) -> SectionNode:
    """Parse a single heading paragraph. `current_depth` is the depth of the
    innermost currently-open section, used to nest un-numbered headings."""
    text = text.strip()

    m = ANNEXURE_RE.match(text)
    if m:
        kind, label, title = m.groups()
        number = f"{kind.title()} {label}".strip()
        return SectionNode(number=number, title=title.strip(), depth=1, is_annexure=True)

    m = CHAPTER_RE.match(text)
    if m:
        num, title = m.groups()
        return SectionNode(number=f"CHAPTER {num}", title=title.strip(), depth=1)

    m = NUMBERED_RE.match(text)
    if m:
        num, title = m.groups()
        depth = num.count(".") + 2  # "2" -> 2, "2.3" -> 3, "2.3.1" -> 4 (chapter is depth 1)
        return SectionNode(number=num, title=title.strip(), depth=depth)

    return SectionNode(number=None, title=text, depth=current_depth + 1)


class SectionTracker:
    """Maintains the open-heading stack as paragraphs are walked in document
    order, exposing the current breadcrumb (`section_path`) and innermost
    numbering (`section_number`)."""

    def __init__(self, document_title: str):
        self.document_title = document_title
        self._stack: list[SectionNode] = []

    def ingest_heading(self, text: str) -> SectionNode:
        current_depth = self._stack[-1].depth if self._stack else 0
        node = parse_heading(text, current_depth)
        while self._stack and self._stack[-1].depth >= node.depth:
            self._stack.pop()
        self._stack.append(node)
        return node

    def ingest_top_level(self, text: str) -> SectionNode:
        """Resets the whole stack and opens a new, un-numbered depth-1
        node — the same reset `CHAPTER n` already causes via `ingest_heading`
        (parse_heading gives every CHAPTER/Annexure match depth=1), just for
        callers that don't have a numbering convention of their own (e.g. a
        brochure's per-page title, "Crop Science" on a page with no chapter
        numbering at all). A following `ingest_heading` call for an
        un-numbered sub-heading nests one level below this automatically,
        since `parse_heading`'s un-numbered fallback is `depth = current_depth + 1`."""
        node = SectionNode(number=None, title=text.strip(), depth=1)
        self._stack = [node]
        return node

    @property
    def stack(self) -> list[SectionNode]:
        return list(self._stack)

    @property
    def section_path(self) -> str:
        parts = [self.document_title] + [n.formatted() for n in self._stack]
        return " › ".join(p for p in parts if p)

    @property
    def section_number(self) -> str | None:
        for n in reversed(self._stack):
            if n.number and not n.is_annexure:
                return n.number
        return None

    @property
    def in_annexure(self) -> bool:
        return any(n.is_annexure for n in self._stack)

    @property
    def annexure_label(self) -> str | None:
        for n in self._stack:
            if n.is_annexure:
                return n.number
        return None

    @property
    def parent_key(self) -> tuple:
        """Identity of the parent section, used to decide whether two
        sibling sections are "under the same parent" for the small-section
        merge rule."""
        return tuple(n.formatted() for n in self._stack[:-1])

    @property
    def depth(self) -> int:
        return self._stack[-1].depth if self._stack else 0
