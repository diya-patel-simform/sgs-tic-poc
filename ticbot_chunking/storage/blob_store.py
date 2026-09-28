"""Azure Blob Storage client: the source document store for the TICBot POC.

Scope of this module is deliberately narrow — list blobs, tell PDFs from
Excel files, and read a blob's bytes (or download it to a local file). It
does not touch parsing, chunking, embeddings, or indexing; see
`ticbot_chunking/scripts/ingest_from_blob.py` for how a downloaded blob is
handed to the existing local pipeline (`pipeline.process_pdf` /
`pipeline.process_excel`), unchanged.

Requires AZURE_STORAGE_ACCOUNT_URL / AZURE_STORAGE_ACCOUNT_KEY /
AZURE_STORAGE_CONTAINER_NAME (see .env.example). AZURE_STORAGE_CONTAINER_NAME
may name a single container or a comma-separated list of containers (e.g.
sample docs split across "sample-pdf-data" and "sample-xlsx-data") — every
listed container is scanned and merged, each blob tagged with the container
it came from. No credentials are ever hardcoded — they're read from the
environment via `config.STORAGE`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ticbot_chunking.config import STORAGE

PDF_EXTENSIONS = {".pdf"}
EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}


@dataclass
class BlobInfo:
    name: str  # full blob path within the container, e.g. "FSSAI Regulation/Contaminants_Regulations.pdf"
    container: str = ""  # which configured container this blob was found in
    size: int | None = None
    content_type: str | None = None
    last_modified: str | None = None

    @property
    def extension(self) -> str:
        return PurePosixPath(self.name).suffix.lower()

    @property
    def is_pdf(self) -> bool:
        return self.extension in PDF_EXTENSIONS

    @property
    def is_excel(self) -> bool:
        return self.extension in EXCEL_EXTENSIONS


def _looks_like_connection_string(value: str) -> bool:
    """AZURE_STORAGE_ACCOUNT_URL is documented as a plain endpoint
    (https://<account>.blob.core.windows.net), but a full Azure connection
    string (DefaultEndpointsProtocol=...;AccountName=...;AccountKey=...) is
    a common copy-paste from the Azure portal, so it's accepted too."""
    return "AccountName=" in value and ("AccountKey=" in value or "SharedAccessSignature=" in value)


def _require_service_client():
    if not STORAGE.is_configured:
        raise RuntimeError(
            "Azure Blob Storage is not configured. Set AZURE_STORAGE_ACCOUNT_URL, "
            "AZURE_STORAGE_ACCOUNT_KEY, and AZURE_STORAGE_CONTAINER_NAME (see .env.example) "
            "before using blob storage."
        )
    from azure.storage.blob import BlobServiceClient

    if _looks_like_connection_string(STORAGE.account_url):
        return BlobServiceClient.from_connection_string(STORAGE.account_url)
    return BlobServiceClient(account_url=STORAGE.account_url, credential=STORAGE.account_key)


def _require_container_client(container: str | None = None):
    """Container defaults to the first configured container when not given
    (the common single-container case)."""
    service_client = _require_service_client()
    if container is None:
        container = STORAGE.container_names[0]
    return service_client.get_container_client(container)


def list_blobs(prefix: str | None = None, container: str | None = None) -> list[BlobInfo]:
    """Lists every blob in the configured container(s) (optionally filtered
    to a name prefix, e.g. a folder), regardless of file type. When
    AZURE_STORAGE_CONTAINER_NAME names more than one container (comma
    separated) and `container` isn't given, every configured container is
    listed and merged, each blob tagged with the container it came from."""
    service_client = _require_service_client()
    containers = [container] if container else STORAGE.container_names
    blobs = []
    for container_name in containers:
        container_client = service_client.get_container_client(container_name)
        for b in container_client.list_blobs(name_starts_with=prefix):
            content_type = b.content_settings.content_type if getattr(b, "content_settings", None) else None
            blobs.append(
                BlobInfo(
                    name=b.name,
                    container=container_name,
                    size=getattr(b, "size", None),
                    content_type=content_type,
                    last_modified=str(b.last_modified) if getattr(b, "last_modified", None) else None,
                )
            )
    return blobs


def list_pdf_blobs(prefix: str | None = None) -> list[BlobInfo]:
    return [b for b in list_blobs(prefix) if b.is_pdf]


def list_excel_blobs(prefix: str | None = None) -> list[BlobInfo]:
    return [b for b in list_blobs(prefix) if b.is_excel]


def download_blob_bytes(blob_name: str, container: str | None = None) -> bytes:
    """Reads a single blob's content into memory."""
    container_client = _require_container_client(container)
    stream = container_client.download_blob(blob_name)
    return stream.readall()


def download_blob_to_file(blob_name: str, dest_dir: str | Path, container: str | None = None) -> Path:
    """Downloads a blob to a local file, named after the blob's own basename
    (so the existing filename-based doc-type hints in
    `metadata/classifier.py` still work unchanged), and returns the local
    path. The caller is responsible for restoring the full blob path as
    `source_file` metadata afterwards — see `scripts/ingest_from_blob.py`."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    local_path = dest_dir / PurePosixPath(blob_name).name
    local_path.write_bytes(download_blob_bytes(blob_name, container=container))
    return local_path
