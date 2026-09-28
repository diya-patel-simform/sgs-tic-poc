"""End-to-end CLI tests for scripts/create_search_index.py, run as a real
subprocess with --dry-run so no live Azure AI Search service is ever
contacted, regardless of what's configured in the real environment's .env.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = "ticbot_chunking.scripts.create_search_index"


def _run(args, env_overrides=None):
    import os

    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run([sys.executable, "-m", SCRIPT, *args], cwd=PROJECT_ROOT,
                           capture_output=True, text=True, timeout=60, env=env)


def test_dry_run_all_four_strategies_succeeds_without_touching_azure():
    result = _run(["--strategy", "all", "--dry-run"])

    assert result.returncode == 0, result.stderr
    for index_name in ("ticbot-chunks-fixed", "ticbot-chunks-recursive",
                        "ticbot-chunks-structure", "ticbot-chunks-hybrid"):
        assert index_name in result.stdout
    assert "not connecting to Azure AI Search" in result.stdout
    assert "OK  " in result.stdout
    assert "FAIL" not in result.stdout


def test_dry_run_single_strategy_with_explicit_index_name():
    result = _run(["--strategy", "fixed", "--index", "my-custom-index", "--dry-run"])

    assert result.returncode == 0, result.stderr
    assert "my-custom-index" in result.stdout
    assert "ticbot-chunks-recursive" not in result.stdout


def test_explicit_index_name_rejected_with_strategy_all():
    result = _run(["--strategy", "all", "--index", "one-index-for-everything", "--dry-run"])

    assert result.returncode != 0
    assert "cannot be used with --strategy all" in result.stderr


def test_missing_vector_dimension_is_a_clear_error_not_a_guess():
    env_overrides = {
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "some-custom-deployment-name",
        "AZURE_OPENAI_EMBEDDING_DIMENSIONS": "",
    }
    result = _run(["--strategy", "fixed", "--dry-run"], env_overrides=env_overrides)

    assert result.returncode != 0
    assert "Could not determine the embedding vector dimension" in result.stderr


def test_explicit_vector_dimensions_flag_overrides_config():
    result = _run(["--strategy", "fixed", "--dry-run", "--vector-dimensions", "1536"])

    assert result.returncode == 0, result.stderr
    assert "vector dimension 1536" in result.stdout


def test_dry_run_never_requires_live_azure_credentials():
    # Even with Azure AI Search fully unconfigured, --dry-run must still
    # succeed — it only builds and locally validates the schema.
    env_overrides = {"AZURE_SEARCH_ENDPOINT": "", "AZURE_SEARCH_ADMIN_KEY": ""}
    result = _run(["--strategy", "hybrid", "--dry-run"], env_overrides=env_overrides)

    assert result.returncode == 0, result.stderr
    assert "Schema OK" in result.stdout
