"""Deterministic fingerprints for generated episode artifacts.

Render cache is content-addressed, not mtime-based. A render is reusable only
when every declared input and the renderer implementation itself are unchanged.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint_files(paths: Iterable[Path], *, metadata: dict | None = None) -> str:
    manifest = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            manifest.append({"path": str(path), "missing": True})
            continue
        manifest.append({
            "path": str(path.resolve()),
            "sha256": file_sha256(path),
            "size": path.stat().st_size,
        })
    payload = {"files": manifest, "metadata": metadata or {}}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_fingerprint(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = data.get("fingerprint")
    return str(value) if value else None


def write_fingerprint(path: Path, fingerprint: str, *, inputs: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema": "whiteboard-story/render-fingerprint@1",
             "fingerprint": fingerprint, "inputs": inputs},
            ensure_ascii=False, indent=2,
        ) + "\n",
        encoding="utf-8",
    )
