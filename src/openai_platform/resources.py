"""OpenAI Files + Vector Stores — used by the OpenAI admin tab."""

from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI, OpenAIError


class OpenAIAdminError(Exception):
    """API or configuration error for admin operations."""


def make_openai_client() -> OpenAI:
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise OpenAIAdminError("OPENAI_API_KEY is not set.")
    base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
    return OpenAI(api_key=key, base_url=base_url) if base_url else OpenAI(api_key=key)


def list_vector_stores(*, limit: int = 50) -> list[dict]:
    client = make_openai_client()
    out: list[dict] = []
    page = client.vector_stores.list(limit=min(limit, 100))
    for vs in page.data or []:
        out.append(
            {
                "id": vs.id,
                "name": getattr(vs, "name", None),
                "status": getattr(vs, "status", None),
                "usage_bytes": getattr(vs, "usage_bytes", None),
                "file_counts": getattr(vs, "file_counts", None),
            }
        )
    return out


def create_vector_store(*, name: str) -> dict:
    client = make_openai_client()
    vs = client.vector_stores.create(name=name.strip() or "vector_store")
    return {"id": vs.id, "name": getattr(vs, "name", None), "status": getattr(vs, "status", None)}


def delete_vector_store(vector_store_id: str) -> None:
    client = make_openai_client()
    client.vector_stores.delete(vector_store_id)


def list_files(*, limit: int = 50) -> list[dict]:
    client = make_openai_client()
    page = client.files.list(limit=min(limit, 100))
    out: list[dict] = []
    for f in page.data or []:
        out.append(
            {
                "id": f.id,
                "filename": getattr(f, "filename", None),
                "bytes": getattr(f, "bytes", None),
                "purpose": getattr(f, "purpose", None),
                "status": getattr(f, "status", None),
            }
        )
    return out


def upload_file_to_openai(path: Path, *, purpose: str = "assistants") -> dict:
    client = make_openai_client()
    if not path.is_file():
        raise OpenAIAdminError(f"Not a file: {path}")
    with path.open("rb") as fh:
        f = client.files.create(file=fh, purpose=purpose)
    return {
        "id": f.id,
        "filename": getattr(f, "filename", None),
        "bytes": getattr(f, "bytes", None),
        "status": getattr(f, "status", None),
    }


def delete_file(file_id: str) -> None:
    client = make_openai_client()
    client.files.delete(file_id)


def list_vector_store_files(vector_store_id: str, *, limit: int = 100) -> list[dict]:
    client = make_openai_client()
    collected: list = []
    page = client.vector_stores.files.list(vector_store_id, limit=min(limit, 100))
    collected.extend(page.data or [])
    while getattr(page, "has_next_page", lambda: False)():
        page = page.get_next_page()
        collected.extend(page.data or [])

    out: list[dict] = []
    for vf in collected:
        fid = str(vf.id)
        row = {
            "id": fid,
            "vector_store_id": vector_store_id,
            "status": getattr(vf, "status", None),
            "usage_bytes": getattr(vf, "usage_bytes", None),
            "filename": None,
        }
        try:
            fobj = client.files.retrieve(fid)
            row["filename"] = getattr(fobj, "filename", None)
        except OpenAIError:
            row["filename"] = None
        out.append(row)
    return out


def attach_file_to_vector_store(vector_store_id: str, file_id: str) -> dict:
    client = make_openai_client()
    vf = client.vector_stores.files.create(vector_store_id=vector_store_id, file_id=file_id)
    return {
        "id": vf.id,
        "status": getattr(vf, "status", None),
        "vector_store_id": vector_store_id,
    }


def delete_vector_store_file(vector_store_id: str, file_id: str) -> None:
    client = make_openai_client()
    client.vector_stores.files.delete(vector_store_id=vector_store_id, file_id=file_id)


def retrieve_vector_store_file(vector_store_id: str, file_id: str) -> dict:
    """Status of a file attached to a vector store (e.g. ``completed``, ``in_progress``, ``failed``)."""
    client = make_openai_client()
    vf = client.vector_stores.files.retrieve(
        vector_store_id=vector_store_id,
        file_id=file_id,
    )
    return {
        "id": getattr(vf, "id", None) or file_id,
        "status": getattr(vf, "status", None),
        "vector_store_id": vector_store_id,
    }
