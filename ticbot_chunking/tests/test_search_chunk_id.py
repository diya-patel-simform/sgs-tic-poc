from ticbot_chunking.search.chunk_id import compute_chunk_id


def test_chunk_id_is_stable_for_identical_inputs():
    a = compute_chunk_id("hybrid", "sample-pdf-data/a.pdf", 3, "some chunk text")
    b = compute_chunk_id("hybrid", "sample-pdf-data/a.pdf", 3, "some chunk text")
    assert a == b


def test_chunk_id_is_a_safe_search_key():
    chunk_id = compute_chunk_id("hybrid", "Food and Multi lab testing capability/a.xlsx", 0, "text")
    assert all(c.isalnum() for c in chunk_id)  # hex digest only — no spaces/slashes


def test_chunk_id_differs_when_strategy_differs():
    a = compute_chunk_id("fixed", "a.pdf", 0, "text")
    b = compute_chunk_id("hybrid", "a.pdf", 0, "text")
    assert a != b


def test_chunk_id_differs_when_source_file_differs():
    a = compute_chunk_id("fixed", "a.pdf", 0, "text")
    b = compute_chunk_id("fixed", "b.pdf", 0, "text")
    assert a != b


def test_chunk_id_differs_when_index_in_file_differs():
    a = compute_chunk_id("fixed", "a.pdf", 0, "text")
    b = compute_chunk_id("fixed", "a.pdf", 1, "text")
    assert a != b


def test_chunk_id_differs_when_text_differs():
    a = compute_chunk_id("fixed", "a.pdf", 0, "text one")
    b = compute_chunk_id("fixed", "a.pdf", 0, "text two")
    assert a != b
