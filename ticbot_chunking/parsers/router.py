"""Chooses between the local PDF parser and Azure Document Intelligence,
automatically, based on whether a PDF has a usable text layer.

    PDF -> inspect_text_layer() -> text-based? --yes--> local_pdf.parse_pdf_local()   -\\
                                              \\--no---> azure_docintel.parse_pdf()    -+-> same LayoutDocument IR -> chunking
                                                                                       -/

Both paths return the exact same `LayoutDocument` IR (see `parsers/ir.py`),
so `pipeline.py`, the chunking-experiments framework, and all four chunking
strategies are unchanged — none of them know or care which parser ran.

This is the single entry point PDF parsing should go through from here on;
`pipeline.process_pdf` and `experiments.common.parse_input_dir` both call
`parse_pdf_auto` instead of calling either parser directly.
"""
from __future__ import annotations

from ticbot_chunking.parsers import azure_docintel, local_pdf
from ticbot_chunking.parsers.ir import LayoutDocument
from ticbot_chunking.parsers.local_pdf import TextLayerStats


def parse_pdf_auto(file_path: str) -> LayoutDocument:
    stats = local_pdf.inspect_text_layer(file_path)
    if stats.has_usable_text_layer:
        return local_pdf.parse_pdf_local(file_path)
    return azure_docintel.parse_pdf(file_path, text_layer_stats=stats)


def describe_routing(file_path: str) -> tuple[str, TextLayerStats]:
    """Returns (parser_name, stats) without actually parsing — useful for
    diagnostics/tests that want to confirm the routing decision cheaply."""
    stats = local_pdf.inspect_text_layer(file_path)
    parser_name = "local" if stats.has_usable_text_layer else "azure_document_intelligence"
    return parser_name, stats
