"""narration_spans 派生的行为测试（迁移第 3 步，ir-alignment §8）。

运行：本工具目录 `uv run python -m unittest discover -s tests -v`
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from whiteboard_story import spans as S  # noqa: E402


class SplitSentencesTest(unittest.TestCase):
    def test_split_keeps_delimiters_and_concat_equals_origin(self):
        text = "为什么？因为AI是词语接龙：每写一个词，都挑最多人满意的。结果呢？一模一样。"
        parts = S.split_sentences(text)
        self.assertEqual(["为什么？", "因为AI是词语接龙：每写一个词，都挑最多人满意的。",
                          "结果呢？", "一模一样。"], parts)
        self.assertEqual(text, "".join(parts))

    def test_no_delimiter_tail_kept(self):
        self.assertEqual(["收尾没有句号"], S.split_sentences("收尾没有句号"))

    def test_empty(self):
        self.assertEqual([], S.split_sentences(""))
        self.assertEqual([], S.split_sentences("   "))


def _units(texts: list[str], step_ms: int = 200, scene_index: int = 0) -> list[dict]:
    """逐字单元：每字 step_ms，顺序铺排（模拟 edge-tts words.json 形状）。"""
    out = []
    t = 100
    for ch in texts:
        for c in ch:
            out.append({"scene_index": scene_index, "text": c,
                        "start_ms": t, "end_ms": t + step_ms})
            t += step_ms
    return out


class DeriveSceneSpansTest(unittest.TestCase):
    def test_sentence_boundaries_from_word_units(self):
        narration = "先跑一段代码。再请独立评审，打到九分。"
        units = _units(["先跑一段代码", "再请独立评审打到九分"])
        warnings: list[str] = []
        spans = S.derive_scene_spans(units, narration, warnings, "scene-01")
        self.assertEqual([], warnings)
        self.assertEqual(2, len(spans))
        self.assertEqual("先跑一段代码。", spans[0]["text"])
        self.assertEqual(100, spans[0]["start_ms"])
        self.assertEqual(100 + 6 * 200, spans[0]["end_ms"])
        self.assertEqual(spans[0]["end_ms"], spans[1]["start_ms"])
        self.assertEqual("再请独立评审，打到九分。", spans[1]["text"])

    def test_unmatched_sentence_warns_not_fabricated(self):
        units = _units(["只有这一句"])
        warnings: list[str] = []
        spans = S.derive_scene_spans(units, "只有这一句。凭空第二句。", warnings, "scene-02")
        self.assertEqual(1, len(spans))
        self.assertEqual(1, len(warnings))
        self.assertIn("凭空第二句", warnings[0])


class EpisodeRoundTripTest(unittest.TestCase):
    def test_write_spans_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            ep = Path(td)
            (ep / "input").mkdir()
            narration = "我把提示词发出去。四张页面一模一样。"
            words = {"version": 1, "granularity": "word",
                     "scenes": [{"scene_index": 0, "start_ms": 0, "end_ms": 6000}],
                     "words": _units(["我把提示词发出去", "四张页面一模一样"])}
            script = {"scenes": [{"id": "scene-01", "narration": narration}]}
            (ep / "input" / "words.json").write_text(
                json.dumps(words, ensure_ascii=False), encoding="utf-8")
            (ep / "input" / "script.json").write_text(
                json.dumps(script, ensure_ascii=False), encoding="utf-8")

            r1, w1 = S.write_spans(ep)
            r2, w2 = S.write_spans(ep)          # 幂等：二次运行结果一致
            self.assertEqual(r1, r2)
            self.assertEqual(w1, w2)
            doc = json.loads((ep / "input" / "words.json").read_text(encoding="utf-8"))
            self.assertIn("narration_spans", doc)
            self.assertEqual(2, len(doc["narration_spans"]["scene-01"]))


if __name__ == "__main__":
    unittest.main()
