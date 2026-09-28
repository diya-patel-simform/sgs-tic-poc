from ticbot_chunking.ingestion.orchestrator import IngestedDocument, ProcessingFailure
from ticbot_chunking.ingestion.report import (
    build_processing_report_json,
    build_processing_report_markdown,
    compute_processing_stats,
)
from ticbot_chunking.ingestion.representative_checks import RepresentativeCheck
from ticbot_chunking.ingestion.source import SourceFile


def _source_files():
    return [
        SourceFile(name="a.pdf", size=1, is_pdf=True, is_excel=False),
        SourceFile(name="b.pdf", size=1, is_pdf=True, is_excel=False),
        SourceFile(name="c.xlsx", size=1, is_pdf=False, is_excel=True),
    ]


def _docs():
    return [
        IngestedDocument(source_name="a.pdf", filename="a.pdf", doc_type="regulation", kind="pdf",
                          parser="local_pdf", local_path="a.pdf", total_pages=5,
                          text_layer_fraction=1.0, text_classification="text-based"),
        IngestedDocument(source_name="b.pdf", filename="b.pdf", doc_type="accreditation_scope", kind="pdf",
                          parser="document_intelligence", local_path="b.pdf", total_pages=3,
                          text_layer_fraction=0.0, text_classification="no usable text layer"),
        IngestedDocument(source_name="c.xlsx", filename="c.xlsx", doc_type="capability_matrix", kind="excel",
                          parser="excel_parser", local_path="c.xlsx", sheets=["S1", "S2"]),
    ]


def _chunks_by_strategy():
    return {
        "hybrid": [
            {"text": "x", "metadata": {"source_file": "a.pdf", "doc_type": "regulation", "parser": "local_pdf",
                                        "tokens": 100, "chunk_type": "text"}},
            {"text": "x", "metadata": {"source_file": "b.pdf", "doc_type": "accreditation_scope",
                                        "parser": "document_intelligence", "tokens": 100,
                                        "chunk_type": "scope_records"}},
            {"text": "x", "metadata": {"source_file": "c.xlsx", "doc_type": "capability_matrix",
                                        "parser": "excel_parser", "tokens": 100, "chunk_type": "sheet_table"}},
        ],
    }


def test_compute_processing_stats_counts_everything_requested():
    stats = compute_processing_stats("blob", _source_files(), _docs(), [], _chunks_by_strategy())

    assert stats["total_files"] == 3
    assert stats["pdfs"] == 2
    assert stats["excel_workbooks"] == 1
    assert stats["text_based_pdfs"] == 1
    assert stats["scanned_pdfs"] == 1
    assert stats["pdfs_processed_locally"] == 1
    assert stats["pdfs_processed_via_document_intelligence"] == 1
    assert stats["excel_sheets_processed"] == 2
    assert stats["total_pages"] == 8
    assert stats["successfully_ingested"] == 3
    assert stats["processing_failures"] == 0
    assert stats["by_strategy"]["hybrid"]["total_chunks"] == 3
    assert stats["by_strategy"]["hybrid"]["chunks_by_doc_type"] == {
        "regulation": 1, "accreditation_scope": 1, "capability_matrix": 1,
    }
    assert stats["by_strategy"]["hybrid"]["chunks_by_parser"] == {
        "local_pdf": 1, "document_intelligence": 1, "excel_parser": 1,
    }


def test_compute_processing_stats_counts_failures():
    failures = [ProcessingFailure(source_name="broken.pdf", reason="parsing failed", parser_attempted="local_pdf",
                                   error="ValueError: bad", retry_recommended=False)]
    stats = compute_processing_stats("blob", _source_files(), _docs(), failures, _chunks_by_strategy())
    assert stats["processing_failures"] == 1


def test_processing_report_json_includes_failure_fields_required_by_the_task():
    failures = [ProcessingFailure(source_name="broken.pdf", reason="parsing failed", parser_attempted="local_pdf",
                                   error="ValueError: bad", retry_recommended=False)]
    stats = compute_processing_stats("blob", _source_files(), _docs(), failures, _chunks_by_strategy())
    checks = [RepresentativeCheck("Excel blocks", "available", "ok")]

    report = build_processing_report_json(stats, _docs(), failures, checks)

    assert len(report["failures"]) == 1
    f = report["failures"][0]
    assert set(f.keys()) == {"filename", "reason", "parser_attempted", "error", "retry_recommended"}
    assert f["filename"] == "broken.pdf"
    assert f["retry_recommended"] is False


def test_processing_report_markdown_renders_key_sections():
    stats = compute_processing_stats("blob", _source_files(), _docs(), [], _chunks_by_strategy())
    checks = [RepresentativeCheck("Excel blocks", "available", "ok")]
    report = build_processing_report_json(stats, _docs(), [], checks)

    md = build_processing_report_markdown(report)

    assert "# TICBot Ingestion Processing Report" in md
    assert "## Processing statistics" in md
    assert "## Documents processed" in md
    assert "## Processing failures" in md
    assert "None." in md  # no failures in this scenario
    assert "## Representative document validation" in md
    assert "Excel blocks" in md
    assert "Azure Blob Storage" in md  # source is always Blob Storage now, stated explicitly
