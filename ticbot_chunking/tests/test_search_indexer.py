"""Tests for the core embedding+upload pipeline
(ticbot_chunking/search/indexer.py). Both the embedding function and the
Azure AI Search client are injected — no real Azure service is contacted.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ticbot_chunking.search.indexer import index_chunks_file, load_chunks_jsonl


def _write_chunks(tmp_path, rows):
    path = tmp_path / "chunks.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    return path


def _row(source_file="a.pdf", text="chunk text", doc_type="regulation", chunk_type="text"):
    return {"text": text, "metadata": {"source_file": source_file, "doc_type": doc_type,
                                        "chunk_type": chunk_type, "parser": "local_pdf",
                                        "access_class": "public", "contains_pii": False}}


def _indexing_result(key: str, status_code: int, succeeded: bool = True, error_message: str | None = None):
    return SimpleNamespace(key=key, status_code=status_code, succeeded=succeeded, error_message=error_message)


def test_index_chunks_file_embeds_embed_text_when_present_not_text(tmp_path):
    # A chunk with embed_text set (the short, spell-normalized copy — see
    # Chunk.embed_text) must be embedded using THAT, not the long
    # citation-oriented `text`, which repeats a full breadcrumb per chunk
    # and was confirmed to bunch vector similarity scores together.
    row_with_embed_text = _row(text="[Regulation] Long breadcrumb...\nBody")
    row_with_embed_text["embed_text"] = "Short prefix | Page 3\nBody"
    row_without_embed_text = _row(text="plain chunk, no embed_text set")
    path = _write_chunks(tmp_path, [row_with_embed_text, row_without_embed_text])

    embedded_texts = []

    def fake_embed(texts):
        embedded_texts.extend(texts)
        return [[0.1] for _ in texts]

    client = MagicMock()
    client.upload_documents.side_effect = lambda documents: [
        _indexing_result(d["chunk_id"], 201) for d in documents
    ]

    index_chunks_file(path, "fixed", "ticbot-chunks-fixed", embed_fn=fake_embed, search_client=client)

    assert embedded_texts == ["Short prefix | Page 3\nBody", "plain chunk, no embed_text set"]


def test_load_chunks_jsonl_skips_blank_lines(tmp_path):
    path = tmp_path / "c.jsonl"
    path.write_text('{"text": "a", "metadata": {}}\n\n{"text": "b", "metadata": {}}\n')
    rows = load_chunks_jsonl(path)
    assert [r["text"] for r in rows] == ["a", "b"]


def test_index_chunks_file_embeds_and_uploads_all_rows(tmp_path):
    rows = [_row(text=f"chunk {i}") for i in range(5)]
    path = _write_chunks(tmp_path, rows)

    embed_calls = []

    def fake_embed(texts):
        embed_calls.append(list(texts))
        return [[0.1] * 3 for _ in texts]

    client = MagicMock()
    client.upload_documents.side_effect = lambda documents: [
        _indexing_result(d["chunk_id"], 201) for d in documents
    ]

    result = index_chunks_file(path, "fixed", "ticbot-chunks-fixed", batch_size=2,
                                embed_fn=fake_embed, search_client=client)

    assert result.chunks_read == 5
    assert result.embeddings_generated == 5
    assert result.documents_uploaded == 5
    assert result.documents_updated == 0
    assert result.embedding_failures == []
    assert result.upload_failures == []
    # batched in groups of 2: [2, 2, 1]
    assert [len(c) for c in embed_calls] == [2, 2, 1]


def test_index_chunks_file_counts_created_vs_updated_by_status_code(tmp_path):
    rows = [_row(text="new chunk"), _row(text="existing chunk")]
    path = _write_chunks(tmp_path, rows)

    client = MagicMock()

    def fake_upload(documents):
        return [_indexing_result(documents[0]["chunk_id"], 201), _indexing_result(documents[1]["chunk_id"], 200)]

    client.upload_documents.side_effect = fake_upload

    result = index_chunks_file(path, "fixed", "ticbot-chunks-fixed", batch_size=10,
                                embed_fn=lambda texts: [[0.1]] * len(texts), search_client=client)

    assert result.documents_uploaded == 1
    assert result.documents_updated == 1


def test_a_failed_embedding_batch_is_recorded_and_does_not_index_a_document(tmp_path):
    rows = [_row(text="ok chunk"), _row(text="bad chunk")]
    path = _write_chunks(tmp_path, rows)

    def flaky_embed(texts):
        if "bad chunk" in texts:
            raise RuntimeError("embedding service exploded")
        return [[0.1]] * len(texts)

    client = MagicMock()
    client.upload_documents.side_effect = lambda documents: [
        _indexing_result(d["chunk_id"], 201) for d in documents
    ]

    result = index_chunks_file(path, "fixed", "ticbot-chunks-fixed", batch_size=1,
                                embed_fn=flaky_embed, search_client=client)

    assert result.embeddings_generated == 1
    assert result.documents_uploaded == 1
    assert len(result.embedding_failures) == 1
    assert "embedding service exploded" in result.embedding_failures[0]["error"]
    assert result.embedding_failures[0]["source_file"] == "a.pdf"
    # the failed chunk was never sent to upload_documents
    uploaded_texts = [call.kwargs["documents"] for call in client.upload_documents.call_args_list]
    assert all(len(docs) == 1 for docs in uploaded_texts)


def test_a_failed_upload_result_is_recorded_without_aborting_the_batch(tmp_path):
    rows = [_row(text="chunk one"), _row(text="chunk two")]
    path = _write_chunks(tmp_path, rows)

    client = MagicMock()

    def fake_upload(documents):
        return [
            _indexing_result(documents[0]["chunk_id"], 201),
            _indexing_result(documents[1]["chunk_id"], 400, succeeded=False, error_message="malformed document"),
        ]

    client.upload_documents.side_effect = fake_upload

    result = index_chunks_file(path, "fixed", "ticbot-chunks-fixed", batch_size=10,
                                embed_fn=lambda texts: [[0.1]] * len(texts), search_client=client)

    assert result.documents_uploaded == 1
    assert len(result.upload_failures) == 1
    assert result.upload_failures[0]["error"] == "malformed document"


def test_a_whole_batch_upload_exception_is_recorded_for_every_chunk_in_it(tmp_path):
    rows = [_row(text="a"), _row(text="b")]
    path = _write_chunks(tmp_path, rows)

    client = MagicMock()
    client.upload_documents.side_effect = RuntimeError("service unavailable")

    result = index_chunks_file(path, "fixed", "ticbot-chunks-fixed", batch_size=10,
                                embed_fn=lambda texts: [[0.1]] * len(texts), search_client=client)

    assert result.documents_uploaded == 0
    assert len(result.upload_failures) == 2
    assert result.total_failures == 2


def test_chunk_ids_used_for_upload_match_compute_chunk_id(tmp_path):
    from ticbot_chunking.search.chunk_id import compute_chunk_id

    rows = [_row(source_file="a.pdf", text="hello")]
    path = _write_chunks(tmp_path, rows)

    captured_docs = []
    client = MagicMock()

    def fake_upload(documents):
        captured_docs.extend(documents)
        return [_indexing_result(d["chunk_id"], 201) for d in documents]

    client.upload_documents.side_effect = fake_upload

    index_chunks_file(path, "fixed", "ticbot-chunks-fixed", batch_size=10,
                       embed_fn=lambda texts: [[0.1]] * len(texts), search_client=client)

    expected_id = compute_chunk_id("fixed", "a.pdf", 0, "hello")
    assert captured_docs[0]["chunk_id"] == expected_id
