"""End-to-end CLI test for scripts/run_validation.py.

Runs as a real subprocess, first generating real strategy output via
scripts/run_chunking_experiments.py against a synthetic local .xlsx (never
a real PDF, so this never risks a live Azure Document Intelligence call),
then validating it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run(module: str, args: list[str]):
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
    )


def _make_input_dir(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Category", "Service"])
    for i in range(1, 15):
        ws.append([f"Category {i}", f"Service description number {i} with a bit more detail for tokens."])
    wb.save(input_dir / "capability.xlsx")
    return input_dir


def test_validation_cli_produces_edge_case_and_inspection_reports(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    output_dir = tmp_path / "experiments"

    gen = _run("ticbot_chunking.scripts.run_chunking_experiments",
                ["--input", str(input_dir), "--output-dir", str(output_dir)])
    assert gen.returncode == 0, gen.stderr

    val = _run("ticbot_chunking.scripts.run_validation", ["--experiments-dir", str(output_dir)])
    assert val.returncode == 0, val.stderr

    assert (output_dir / "edge_case_report.md").exists()
    assert (output_dir / "edge_case_report.json").exists()
    for strategy in ("fixed", "recursive", "structure_aware", "hybrid"):
        assert (output_dir / strategy / "inspection_report.md").exists()

    report_md = (output_dir / "edge_case_report.md").read_text()
    assert "Edge Case | Expected | Actual | Pass/Fail" in report_md
    assert "does not declare a best strategy" in report_md.lower() or "not declare" in report_md.lower()
    # all four strategies' fixture-based checks ran regardless of the (excel-only) corpus
    for strategy in ("fixed", "recursive", "structure_aware", "hybrid"):
        assert f"## {strategy}" in report_md

    with open(output_dir / "edge_case_report.json") as f:
        report_json = json.load(f)
    assert any(r["edge_case"] == "Table rows being split" for r in report_json)
    assert any(r["edge_case"] == "Incorrect Excel block separation" for r in report_json)


def test_validation_cli_works_with_no_experiments_dir_yet(tmp_path):
    # Fixture-based checks must still run and produce a report even when no
    # scripts/run_chunking_experiments.py output exists at all.
    output_dir = tmp_path / "experiments_empty"

    val = _run("ticbot_chunking.scripts.run_validation", ["--experiments-dir", str(output_dir)])

    assert val.returncode == 0, val.stderr
    assert (output_dir / "edge_case_report.md").exists()
    report_md = (output_dir / "edge_case_report.md").read_text()
    assert "Rowspan/merged-label carry-forward" in report_md
