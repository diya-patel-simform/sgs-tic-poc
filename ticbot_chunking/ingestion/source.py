"""Source document listing + fetching for the end-to-end ingestion pipeline.

Azure Blob Storage (`storage/blob_store.py`) is the sole ingestion source:
Blob Storage -> parser routing -> chunking -> validation. There is no local
directory fallback — if Blob Storage isn't configured, inaccessible, or
returns no files, this fails clearly instead of silently reading local
files. `source_kind` is still returned/reported alongside results (always
`"blob"`) so downstream reporting code doesn't need to change.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ticbot_chunking.config import STORAGE
from ticbot_chunking.storage import blob_store


@dataclass
class SourceFile:
    name: str  # "<container>/<blob path>" — the full provenance path
    size: int | None
    is_pdf: bool
    is_excel: bool
    container: str | None = None  # which container this came from
    blob_name: str | None = None  # the raw blob path within `container`, used to fetch it


def list_source_files(prefix: str | None = None, container: str | None = None) -> tuple[str, list[SourceFile]]:
    """Returns (source_kind, files). source_kind is always "blob" — Azure
    Blob Storage is the sole ingestion source, kept as part of the return
    shape so downstream reporting code doesn't need to change.

    `container` restricts the blob listing to that one container for this
    call only (e.g. to test against a different document set) — it does
    not require changing AZURE_STORAGE_CONTAINER_NAME.

    Raises RuntimeError with an actionable message if Blob Storage isn't
    configured. There is no local-directory fallback."""
    if not STORAGE.is_configured:
        raise RuntimeError(
            "Azure Blob Storage is not configured (set AZURE_STORAGE_ACCOUNT_URL / "
            "AZURE_STORAGE_ACCOUNT_KEY / AZURE_STORAGE_CONTAINER_NAME — see .env.example). "
            "Azure Blob Storage is the sole ingestion source; there is no local fallback."
        )

    blobs = [b for b in blob_store.list_blobs(prefix=prefix, container=container) if b.is_pdf or b.is_excel]
    files = [
        SourceFile(
            name=f"{b.container}/{b.name}", size=b.size, is_pdf=b.is_pdf, is_excel=b.is_excel,
            container=b.container, blob_name=b.name,
        )
        for b in blobs
    ]
    return "blob", files


def fetch_to_local(source_kind: str, name: str, dest_dir: str,
                    container: str | None = None, blob_name: str | None = None) -> Path:
    """Fetches one source file to a local path, named after its own
    basename (so filename-based doc-type routing works the same regardless
    of source). `blob_name`/`container` (from the matching SourceFile)
    select the exact blob; `name` alone is not enough once more than one
    container is configured.

    Azure Blob Storage is the only supported `source_kind` — there is no
    local-directory fallback."""
    if source_kind != "blob":
        raise ValueError(
            f"Unsupported source_kind: {source_kind!r} — Azure Blob Storage is the sole ingestion source."
        )
    return blob_store.download_blob_to_file(blob_name or name, dest_dir, container=container)
