"""CLI argument-handling tests for scripts/index_chunks.py that don't need
a live Azure service: strategy/--all mutual exclusion, --index restriction,
and missing chunks.jsonl handling. Run as real subprocesses so the actual
argparse logic in main() is exercised.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = "ticbot_chunking.scripts.index_chunks"


def _run(args):
    return subprocess.run([sys.executable, "-m", SCRIPT, *args], cwd=PROJECT_ROOT,
                           capture_output=True, text=True, timeout=60)


def test_requires_exactly_one_of_strategy_or_all():
    result = _run([])
    assert result.returncode != 0
    assert "specify exactly one of --strategy" in result.stderr


def test_rejects_both_strategy_and_all():
    result = _run(["--strategy", "fixed", "--all"])
    assert result.returncode != 0
    assert "specify exactly one of --strategy" in result.stderr


def test_rejects_explicit_index_with_all():
    result = _run(["--all", "--index", "one-index-for-everything"])
    assert result.returncode != 0
    assert "--index cannot be used with --all" in result.stderr


def test_missing_chunks_file_is_reported_and_does_not_crash(tmp_path):
    empty_chunks_dir = tmp_path / "no_such_experiments"
    result = _run(["--strategy", "fixed", "--chunks-dir", str(empty_chunks_dir)])

    assert result.returncode != 0
    assert "does not exist" in result.stdout
    assert "FAIL" in result.stdout
