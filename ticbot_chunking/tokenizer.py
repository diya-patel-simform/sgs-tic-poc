"""Token counting against the text-embedding-3 tokenizer (cl100k_base)."""
from __future__ import annotations

from functools import lru_cache

import tiktoken

from ticbot_chunking.config import TOKENIZER_MODEL


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(TOKENIZER_MODEL)
    except KeyError:
        return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_encoding().encode(text))


def get_encoding() -> tiktoken.Encoding:
    """Public accessor for the same cached encoding `count_tokens` uses —
    needed by callers that encode/decode raw token id windows directly
    (e.g. the fixed-size experiment strategy)."""
    return _encoding()
