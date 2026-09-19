from __future__ import annotations

import json
from pathlib import Path

from whiteboard_story.artifact_fingerprint import (
    fingerprint_files,
    read_fingerprint,
    write_fingerprint,
)


def test_fingerprint_changes_when_content_changes(tmp_path: Path) -> None:
    dep = tmp_path / "dep.txt"
    dep.write_text("v1", encoding="utf-8")
    first = fingerprint_files([dep], metadata={"renderer": "v1"})
    dep.write_text("v2", encoding="utf-8")
    second = fingerprint_files([dep], metadata={"renderer": "v1"})
    assert first != second


def test_fingerprint_roundtrip(tmp_path: Path) -> None:
    dep = tmp_path / "dep.txt"
    dep.write_text("v1", encoding="utf-8")
    fp = fingerprint_files([dep])
    out = tmp_path / "fingerprint.json"
    write_fingerprint(out, fp, inputs=[str(dep)])
    assert read_fingerprint(out) == fp
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema"] == "whiteboard-story/render-fingerprint@1"
