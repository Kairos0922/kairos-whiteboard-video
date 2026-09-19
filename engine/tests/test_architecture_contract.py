from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
THEMES = ROOT / "themes"


def test_repository_contract_files_exist() -> None:
    required = [
        ROOT / "SKILL.md",
        ROOT / "README.md",
        ROOT / "references" / "architecture.md",
        ROOT / "references" / "whiteboard-video-principles.md",
        ROOT / "references" / "quality-checklist.md",
        ENGINE / "scripts" / "workflow.py",
        ENGINE / "scripts" / "build_video.py",
        ENGINE / "scripts" / "whiteboard_story" / "qa_gates.py",
    ]
    assert all(path.is_file() for path in required)


def test_theme_registry_points_to_existing_theme() -> None:
    registry = json.loads((THEMES / "registry.json").read_text(encoding="utf-8"))
    entries = registry.get("themes", [])
    assert entries, "theme registry must contain at least one validated theme"

    for entry in entries:
        theme_path = ROOT / entry["path"]
        assert theme_path.is_dir(), entry["id"]
        assert (theme_path / "theme.json").is_file(), entry["id"]


def test_default_theme_contract_is_complete() -> None:
    registry = json.loads((THEMES / "registry.json").read_text(encoding="utf-8"))
    default = registry["themes"][0]
    theme = ROOT / default["path"]
    config = json.loads((theme / "theme.json").read_text(encoding="utf-8"))

    assert config["id"] == default["id"]
    assert config.get("renderer_mode")
    assert config.get("resolution") == default["resolution"]
    assert config.get("palette")
    assert config.get("hand")
    assert config.get("character")


def test_skill_routes_engineering_details_to_canonical_document() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "references/architecture.md" in skill
    assert "confirm-content" in skill
    assert "confirm-visual" in skill
    assert "confirm-final" in skill
    assert "words.json" in skill
