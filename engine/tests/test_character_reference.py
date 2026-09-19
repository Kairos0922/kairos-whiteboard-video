from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from PIL import Image

from whiteboard_story import character_bible, prompt_builder


def _write_character_project(root: Path) -> None:
    (root / "input").mkdir(parents=True)
    (root / "input" / "characters.json").write_text(
        """{
  "schema": "whiteboard-story/characters@2",
  "version": 1,
  "characters": [{
    "id": "child",
    "name": "Child",
    "immutable": {
      "hair": "short dark hair",
      "top": "soft green",
      "proportions": "elementary-school-age"
    },
    "allowed_variations": ["pose", "gesture", "facial expression", "view angle"]
  }]
}""",
        encoding="utf-8",
    )


def test_canonical_sheet_is_required_for_character_scenes(tmp_path):
    _write_character_project(tmp_path)
    chars = character_bible.load_characters(tmp_path)
    assert character_bible.validate_characters(chars) == []
    assert character_bible.validate_canonical_sheet(tmp_path)
    Image.new("RGBA", (1024, 1024), (247, 242, 232, 255)).save(
        tmp_path / "input" / "character-sheet.png"
    )
    assert character_bible.validate_canonical_sheet(tmp_path) == []


def test_scene_manifest_and_prompt_use_canonical_sheet(tmp_path):
    _write_character_project(tmp_path)
    Image.new("RGBA", (1024, 1024), (247, 242, 232, 255)).save(
        tmp_path / "input" / "character-sheet.png"
    )
    chars = character_bible.load_characters(tmp_path)
    manifest = character_bible.character_reference_manifest(
        tmp_path, chars, ["child"]
    )
    assert manifest[0]["canonical_sheet"].endswith("input/character-sheet.png")
    assert manifest[0]["reference_priority"][0] == "canonical_sheet"

    theme = tmp_path / "theme"
    theme.mkdir()
    (theme / "style-block.txt").write_text("warm pencil style", encoding="utf-8")
    payload = prompt_builder.build_scene_payload(
        "scene-01",
        "A child tries independently while a parent stays nearby.",
        theme,
        character_sheet=character_bible.render_prompt_block(chars, ["child"]),
        character_ids=["child"],
        character_references=manifest,
    )
    assert "CHARACTER CONSISTENCY LOCK — HARD:" in payload["prompt"]
    assert "CANONICAL SHEET" in payload["prompt"]
    assert payload["character_ids"] == ["child"]
