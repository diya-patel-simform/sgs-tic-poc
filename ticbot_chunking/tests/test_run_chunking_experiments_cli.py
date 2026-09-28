"""End-to-end CLI tests for scripts/run_chunking_experiments.py.

Run as a real subprocess (not imported in-process) so the module-level
environment-variable pre-parsing at the top of the script — which must run
before any `ticbot_chunking` import — is exercised exactly as a real
invocation would. Input is a synthetic local .xlsx built in the test, never
a real PDF, so this never risks a live Azure Document Intelligence call.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook

SCRIPT = "ticbot_chunking.scripts.run_chunking_experiments"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _make_input_dir(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["Category", "Service"])
    for i in range(1, 20):
        ws.append([f"Category {i}", f"Service description number {i} with a bit more detail to add tokens."])
    wb.save(input_dir / "capability.xlsx")
    return input_dir


def _run(args):
    # cwd is always the project root: `python -m` needs `ticbot_chunking` to
    # be importable, and it isn't pip-installed here — --input/--output-dir
    # are always passed as absolute (pytest tmp_path) paths regardless.
    return subprocess.run(
        [sys.executable, "-m", SCRIPT, *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
    )


def test_cli_runs_all_strategies_and_writes_expected_layout(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    output_dir = tmp_path / "experiments"

    result = _run(["--input", str(input_dir), "--output-dir", str(output_dir)])

    assert result.returncode == 0, result.stderr
    for strategy in ("fixed", "recursive", "structure_aware", "hybrid"):
        assert (output_dir / strategy / "chunks.jsonl").exists()
        assert (output_dir / strategy / "stats.json").exists()
        with open(output_dir / strategy / "chunks.jsonl") as f:
            lines = [json.loads(line) for line in f if line.strip()]
        assert lines, f"{strategy} produced no chunks"
        assert all(row["metadata"]["strategy"] == strategy for row in lines)

    assert (output_dir / "comparison_report.json").exists()
    with open(output_dir / "comparison_report.json") as f:
        report = json.load(f)
    assert len(report["strategies"]) == 4
    assert "does not" in report["note"].lower()


def test_cli_selects_a_single_strategy(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    output_dir = tmp_path / "experiments"

    result = _run(["--input", str(input_dir), "--output-dir", str(output_dir), "--strategy", "recursive"],)

    assert result.returncode == 0, result.stderr
    assert (output_dir / "recursive" / "chunks.jsonl").exists()
    assert not (output_dir / "fixed").exists()
    assert not (output_dir / "hybrid").exists()


def test_cli_chunk_size_and_max_chunk_size_are_actually_applied(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    output_dir = tmp_path / "experiments"

    result = _run(
        ["--input", str(input_dir), "--output-dir", str(output_dir), "--strategy", "fixed",
         "--chunk-size", "30", "--overlap", "5", "--max-chunk-size", "30"],
    )

    assert result.returncode == 0, result.stderr
    with open(output_dir / "fixed" / "stats.json") as f:
        strategy_stats = json.load(f)
    assert strategy_stats["chunk_size"] == 30
    assert strategy_stats["max_chunk_size"] == 30
    # a small window should produce noticeably more, smaller chunks than the defaults
    assert strategy_stats["total_chunks"] > 3
    assert strategy_stats["tokens_max"] <= 30 + 15  # window budget plus a small header allowance


def test_cli_comparison_report_accumulates_across_separate_invocations(tmp_path):
    input_dir = _make_input_dir(tmp_path)
    output_dir = tmp_path / "experiments"

    r1 = _run(["--input", str(input_dir), "--output-dir", str(output_dir), "--strategy", "fixed"])
    assert r1.returncode == 0, r1.stderr
    with open(output_dir / "comparison_report.json") as f:
        report_after_one = json.load(f)
    assert len(report_after_one["strategies"]) == 1

    r2 = _run(["--input", str(input_dir), "--output-dir", str(output_dir), "--strategy", "recursive"])
    assert r2.returncode == 0, r2.stderr
    with open(output_dir / "comparison_report.json") as f:
        report_after_two = json.load(f)
    assert {s["strategy"] for s in report_after_two["strategies"]} == {"fixed", "recursive"}
