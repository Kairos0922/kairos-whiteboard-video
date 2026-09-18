from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from whiteboard_story import character_bible, prompt_builder, review_images


REPO_ROOT = Path(__file__).resolve().parents[2]


class CharacterBibleTest(unittest.TestCase):
    def test_structured_bible_is_stable_and_valid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "input").mkdir()
            (root / "input" / "characters.json").write_text(json.dumps({
                "schema": "whiteboard-story/characters@1",
                "characters": [{
                    "id": "office-man",
                    "name": "Office Man",
                    "immutable": {
                        "hair": "short grouped ink-navy fringe",
                        "face": "tapered warm-peach face",
                        "glasses": "rectangular dark-rim glasses",
                        "outfit": "ink-navy jacket, ivory shirt triangle, muted-violet tie",
                    },
                    "allowed_variations": ["pose", "gesture", "expression", "view angle"]
                }]
            }), encoding="utf-8")
            chars = character_bible.load_characters(root)
            self.assertEqual([], character_bible.validate_characters(chars))
            block = character_bible.render_prompt_block(chars, ["office-man"])
            self.assertIn("CHARACTER ID [office-man]", block)
            self.assertIn("IMMUTABLE hair", block)
            self.assertIn("Do not swap colors", block)

    def test_scene_ids_support_global_and_element_declarations(self):
        ids = character_bible.scene_character_ids({
            "character_ids": ["office-man"],
            "elements": [
                {"characterId": "investigator"},
                {"character_id": "office-man"},
            ],
        })
        self.assertEqual(["office-man", "investigator"], ids)


class ThemeContractTest(unittest.TestCase):
    def test_default_theme_contract_is_consistent(self):
        theme = REPO_ROOT / "themes" / "chalkboard-chibi"
        r = review_images.validate_theme_package(theme)
        self.assertTrue(r["ok"], r)

    def test_probe_no_longer_overrides_navy_character_fill(self):
        probe = json.loads(
            (REPO_ROOT / "themes" / "chalkboard-chibi" / "probe.json")
            .read_text(encoding="utf-8")
        )
        subject = probe["subject"].lower()
        for legacy in ("board-negative hair", "board-negative hair and suit", "hair and suit treatment"):
            self.assertNotIn(legacy, subject)


class ThemeContractCompatibilityTest(unittest.TestCase):
    def test_minimal_temporary_theme_is_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            theme = Path(td)
            (theme / "style-block.txt").write_text("temporary test style", encoding="utf-8")
            result = review_images.validate_theme_package(theme)
            self.assertTrue(result["ok"], result)
            self.assertTrue(result["warnings"])

class CharacterReferenceGateTest(unittest.TestCase):
    def test_unknown_scene_character_id_is_blocked(self):
        chars = [{
            "id": "office-man",
            "immutable": {"hair": "navy", "face": "peach"}
        }]
        scenes = [{"id": "scene-01", "character_ids": ["unknown-person"]}]
        errors = character_bible.validate_scene_refs(chars, scenes)
        self.assertTrue(errors)
        self.assertIn("unknown-person", errors[0])

class PromptBuilderCharacterTest(unittest.TestCase):
    def test_character_contract_and_ids_are_embedded_in_prompt_payload(self):
        with tempfile.TemporaryDirectory() as td:
            theme = Path(td)
            (theme / "style-block.txt").write_text("base style", encoding="utf-8")
            (theme / "character-contract.txt").write_text("CHARACTER DESIGN CONTRACT", encoding="utf-8")
            payload = prompt_builder.build_scene_payload(
                "scene-01",
                "an office scene",
                theme,
                n_islands=2,
                character_sheet="CHARACTER ID [office-man] - locked",
                character_ids=["office-man"],
            )
            self.assertIn("CHARACTER DESIGN CONTRACT", payload["prompt"])
            self.assertIn("CHARACTER ID [office-man]", payload["prompt"])
            self.assertEqual(["office-man"], payload["character_ids"])


if __name__ == "__main__":
    unittest.main()
