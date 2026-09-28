import importlib
import os


def test_narrative_limits_are_overridable_via_env(monkeypatch):
    monkeypatch.setenv("CHUNK_NARRATIVE_MAX_TOKENS", "123")
    monkeypatch.setenv("CHUNK_TABLE_MAX_TOKENS", "999")
    import ticbot_chunking.config as config
    importlib.reload(config)
    try:
        assert config.NARRATIVE.max_tokens == 123
        assert config.REGULATION_TABLE.max_tokens == 999
    finally:
        monkeypatch.delenv("CHUNK_NARRATIVE_MAX_TOKENS", raising=False)
        monkeypatch.delenv("CHUNK_TABLE_MAX_TOKENS", raising=False)
        importlib.reload(config)


def test_retrieval_mode_defaults_to_vector(monkeypatch):
    monkeypatch.delenv("RETRIEVAL_MODE", raising=False)
    import ticbot_chunking.config as config
    importlib.reload(config)
    try:
        assert config.SEARCH.retrieval_mode == "vector"
    finally:
        importlib.reload(config)


def test_retrieval_mode_is_overridable_via_env(monkeypatch):
    monkeypatch.setenv("RETRIEVAL_MODE", "hybrid")
    import ticbot_chunking.config as config
    importlib.reload(config)
    try:
        assert config.SEARCH.retrieval_mode == "hybrid"
    finally:
        monkeypatch.delenv("RETRIEVAL_MODE", raising=False)
        importlib.reload(config)


def test_narrative_limits_default_when_unset(monkeypatch):
    monkeypatch.delenv("CHUNK_NARRATIVE_MAX_TOKENS", raising=False)
    import ticbot_chunking.config as config
    importlib.reload(config)
    assert config.NARRATIVE.max_tokens == 700
    assert config.NARRATIVE.min_tokens == 60


def test_storage_container_names_splits_a_comma_separated_list(monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://fakeaccount.blob.core.windows.net")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "fake-key")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "sample-pdf-data, sample-xlsx-data")
    import ticbot_chunking.config as config
    importlib.reload(config)
    try:
        assert config.STORAGE.container_names == ["sample-pdf-data", "sample-xlsx-data"]
        assert config.STORAGE.is_configured is True
    finally:
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "")
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "")
        monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "")
        importlib.reload(config)


def test_openai_sdk_endpoint_strips_the_v1_suffix(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://sgs-poc.openai.azure.com/openai/v1")
    import ticbot_chunking.config as config
    importlib.reload(config)
    try:
        assert config.OPENAI.sdk_endpoint == "https://sgs-poc.openai.azure.com"
    finally:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
        importlib.reload(config)


def test_openai_sdk_endpoint_strips_the_bare_openai_suffix(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://sgs-poc.openai.azure.com/openai/")
    import ticbot_chunking.config as config
    importlib.reload(config)
    try:
        assert config.OPENAI.sdk_endpoint == "https://sgs-poc.openai.azure.com"
    finally:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
        importlib.reload(config)


def test_openai_sdk_endpoint_leaves_a_bare_resource_root_unchanged(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://sgs-poc.openai.azure.com/")
    import ticbot_chunking.config as config
    importlib.reload(config)
    try:
        assert config.OPENAI.sdk_endpoint == "https://sgs-poc.openai.azure.com"
    finally:
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "")
        importlib.reload(config)


def test_storage_container_names_empty_when_unset(monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "")
    import ticbot_chunking.config as config
    importlib.reload(config)
    try:
        assert config.STORAGE.container_names == []
        assert config.STORAGE.is_configured is False
    finally:
        importlib.reload(config)
