from unittest.mock import MagicMock

from ticbot_chunking.search.index_content_validation import validate_indexed_content


def _client(count, documents):
    client = MagicMock()
    client.get_document_count.return_value = count
    client.search.return_value = documents
    return client


def test_reports_ok_when_count_matches_and_fields_are_populated():
    docs = [{"chunk_id": "a", "text": "x", "chunk_vector": [0.1], "source_file": "a.pdf"},
            {"chunk_id": "b", "text": "y", "chunk_vector": [0.2], "source_file": "b.pdf"}]
    client = _client(2, docs)

    report = validate_indexed_content(client, expected_chunk_count=2, index_name="ticbot-chunks-fixed")

    assert report.count_matches is True
    assert report.vector_field_populated is True
    assert report.text_field_populated is True
    assert report.source_metadata_populated is True
    assert report.chunk_ids_unique_in_sample is True
    assert report.ok is True
    assert report.problems == []


def test_detects_a_document_count_mismatch():
    client = _client(3, [{"chunk_id": "a", "text": "x", "chunk_vector": [0.1], "source_file": "a.pdf"}])

    report = validate_indexed_content(client, expected_chunk_count=5, index_name="ticbot-chunks-fixed")

    assert report.count_matches is False
    assert any("document count mismatch" in p for p in report.problems)


def test_detects_an_empty_vector_field():
    docs = [{"chunk_id": "a", "text": "x", "chunk_vector": [], "source_file": "a.pdf"}]
    client = _client(1, docs)

    report = validate_indexed_content(client, expected_chunk_count=1, index_name="ticbot-chunks-fixed")

    assert report.vector_field_populated is False
    assert any("chunk_vector" in p for p in report.problems)


def test_detects_duplicate_chunk_ids_in_sample():
    docs = [{"chunk_id": "same", "text": "x", "chunk_vector": [0.1], "source_file": "a.pdf"},
            {"chunk_id": "same", "text": "y", "chunk_vector": [0.2], "source_file": "b.pdf"}]
    client = _client(2, docs)

    report = validate_indexed_content(client, expected_chunk_count=2, index_name="ticbot-chunks-fixed")

    assert report.chunk_ids_unique_in_sample is False
    assert any("duplicate chunk_id" in p for p in report.problems)


def test_detects_no_documents_sampled():
    client = _client(0, [])

    report = validate_indexed_content(client, expected_chunk_count=0, index_name="ticbot-chunks-fixed")

    assert report.count_matches is True
    assert any("no documents could be sampled" in p for p in report.problems)
