"""Reusable Azure AI Search index manager: create an index, check whether
it already exists, optionally delete/recreate it (only when explicitly
requested — never automatically), and fetch an existing index for
validation. Does not upload documents, generate embeddings, or run
queries — see `scripts/create_search_index.py` for the CLI built on top of
this, and the project README for what comes after this step.
"""
from __future__ import annotations

from ticbot_chunking.config import SEARCH


def _require_client():
    if not SEARCH.is_configured:
        raise RuntimeError(
            "Azure AI Search is not configured. Set AZURE_SEARCH_ENDPOINT and "
            "AZURE_SEARCH_ADMIN_KEY (see .env.example) before managing indexes."
        )
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents.indexes import SearchIndexClient

    return SearchIndexClient(endpoint=SEARCH.endpoint, credential=AzureKeyCredential(SEARCH.admin_key))


def index_exists(index_name: str) -> bool:
    client = _require_client()
    return index_name in set(client.list_index_names())


def get_index(index_name: str):
    """Fetches the live index definition. Raises azure.core.exceptions.ResourceNotFoundError
    if it doesn't exist."""
    client = _require_client()
    return client.get_index(index_name)


def create_index(index, *, recreate: bool = False) -> str:
    """Creates `index` in the configured Azure AI Search service.

    Returns "created" (didn't exist, now does), "exists" (already existed,
    left untouched — the default, safe behavior), or "recreated" (already
    existed, was deleted and rebuilt, only when `recreate=True` was passed
    explicitly). Never deletes an existing index otherwise."""
    client = _require_client()
    already_exists = index.name in set(client.list_index_names())

    if already_exists and not recreate:
        return "exists"

    if already_exists and recreate:
        client.delete_index(index.name)
        client.create_index(index)
        return "recreated"

    client.create_index(index)
    return "created"
