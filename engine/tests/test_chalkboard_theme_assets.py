"""默认 chalkboard-chibi 主题资源契约测试。"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from whiteboard_story.resource_resolver import ResourceResolver  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
THEME = ROOT / "themes" / "chalkboard-chibi"


class ChalkboardThemeAssetTest(unittest.TestCase):
    def test_reference_theme_hand_asset_contract(self):
        theme = json.loads((THEME / "theme.json").read_text(encoding="utf-8"))
        hand = theme["hands"][0]
        path = THEME / hand["file"]
        self.assertTrue(path.exists(), path)
        with Image.open(path) as img:
            self.assertEqual(img.mode, "RGBA")
            self.assertEqual(list(img.size), hand["size"])
        tip = json.loads((THEME / hand["tip"]).read_text(encoding="utf-8"))["tip"]
        self.assertEqual(tip, [6, 8])
        self.assertLess(tip[0], hand["size"][0])
        self.assertLess(tip[1], hand["size"][1])

    def test_theme_declares_renderer_hand_and_forbids_generated_hand(self):
        theme = json.loads((THEME / "theme.json").read_text(encoding="utf-8"))
        self.assertEqual(theme["renderer_mode"], "chalk")
        self.assertTrue(theme["reference_contract"]["generated_board_must_not_include_hand"])
        self.assertEqual(theme["hands"][0]["id"], "hand-chalk")

    def test_resolver_accepts_canonical_hand(self):
        episode = ROOT / "projects"
        resolver = ResourceResolver(episode)
        # resolver needs an episode state/script to know the theme; validate the
        # canonical asset directly here to keep this test independent of project state.
        resolver._validate_theme_hand(
            THEME / "hands" / "hand-chalk.png",
            THEME,
            json.loads((THEME / "theme.json").read_text(encoding="utf-8"))["hands"][0],
        )


if __name__ == "__main__":
    unittest.main()
