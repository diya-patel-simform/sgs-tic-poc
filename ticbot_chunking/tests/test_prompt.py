"""Tests for the grounded-answering system prompt (rag/prompt.py). Confirms
the new rules added after manual testing (never blend sectors/documents,
quote values/qualifiers exactly, preserve "Nil" literally, always state
units, include reference/page, handle an unlisted item honestly, say
plainly when something isn't stated) are present, and that the existing
citation/refusal contract `rag_service.py` depends on verbatim is untouched.
"""
from __future__ import annotations

from ticbot_chunking.rag.prompt import NO_CONTEXT_ANSWER, SYSTEM_PROMPT, build_messages


def test_no_context_answer_sentence_is_unchanged():
    assert NO_CONTEXT_ANSWER == "I couldn't find enough information in the provided documents to answer this question."
    assert NO_CONTEXT_ANSWER in SYSTEM_PROMPT


def test_citation_marker_rule_is_still_present():
    assert "[1]" in SYSTEM_PROMPT
    assert "cite" in SYSTEM_PROMPT.lower()


def test_new_rule_never_blend_sectors_or_documents():
    lower = SYSTEM_PROMPT.lower()
    assert "never blend" in lower


def test_new_rule_preserve_nil_literally():
    assert '"Nil"' in SYSTEM_PROMPT


def test_new_rule_always_state_units():
    assert "unit" in SYSTEM_PROMPT.lower()


def test_new_rule_unlisted_item_handled_honestly():
    lower = SYSTEM_PROMPT.lower()
    assert "isn't listed" in lower or "not listed" in lower
    assert "default" in lower


def test_new_rule_says_plainly_when_not_stated():
    assert "isn't stated" in SYSTEM_PROMPT.lower()


def test_build_messages_unchanged_shape():
    messages = build_messages("What is the limit?", "Sources:\n\nSource [1]...")
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[1]["role"] == "user"
    assert "Source [1]" in messages[1]["content"]


def test_build_messages_handles_no_sources():
    messages = build_messages("q", "")
    assert "No sources were retrieved" in messages[1]["content"]
