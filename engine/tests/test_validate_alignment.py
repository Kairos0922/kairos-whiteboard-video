"""validate P2 对齐护栏测试：words.json 词表质量 + 标注词级调度零降级。

只断言新增护栏的阻断/警告子串是否出现；三件套缺失等既有阻断与本组用例无关。
运行：本目录 `uv run pytest -q`
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from whiteboard_story.validate import validate  # noqa: E402

NARRATION = ("你有没有觉得AI做的页面都长一个样。"
             "作者把同一条提示丢给四个助手，得到四张几乎一样的图。")


def _words_doc(*, scene_start: int = 500, scene_end: int = 6000,
               granularity: str = "word", shuffle_last_two: bool = False,
               shift_last_out: bool = False,
               text_override: list[str] | None = None) -> dict:
    base = NARRATION.replace("。", "").replace(",", "").replace("？", "")
    if text_override is None:
        # 把旁白字符切成 4 字词，时间从 scene_start 起每个 180ms
        chars = [c for c in base]
        texts = ["".join(chars[i:i + 4]) or "词" for i in range(0, len(chars), 4)][:20]
    else:
        texts = text_override
    words = []
    t = scene_start + 100
    for i, tx in enumerate(texts):
        ws, we = t, t + 180
        if shift_last_out and i == len(texts) - 1:
            ws, we = scene_end + 500, scene_end + 700  # 越出幕窗
        words.append({"scene_index": 0, "text": tx, "start_ms": ws, "end_ms": we})
        t = we
    if shuffle_last_two and len(words) >= 2:  # 交换最后两词的时间 → 乱序
        words[-1]["start_ms"], words[-2]["start_ms"] = \
            words[-2]["start_ms"], words[-1]["start_ms"]
        words[-1]["end_ms"], words[-2]["end_ms"] = words[-2]["end_ms"], words[-1]["end_ms"]
    return {"voice": "YunxiaNeural", "granularity": granularity,
            "scenes": [{"scene_index": 0, "start_ms": scene_start, "end_ms": scene_end}],
            "words": words}


def _annotation(*, schedule: str | None = "words", matched: str = "3/3",
                warnings: list[str] | None = None) -> dict:
    doc = {"canvas": {"width": 1920, "height": 1080}, "sceneDurationMs": 6000,
           "elements": [{"id": f"panel-{i}", "sequence": i,
                         "region": {"x": i * 100, "y": 0, "width": 90, "height": 90},
                         "reveal": {"startMs": 100 * i, "durationMs": 500,
                                    "protectedRegions": []},
                         "handPath": {"start": [0, 0], "end": [1, 1]},
                         "kind": "panel"} for i in range(1, 4)]}
    if schedule is not None:
        doc["meta"] = {"schedule": schedule, "granularity": "word",
                       "matched": matched, "warnings": warnings or []}
    return doc


class AlignmentGuardTest(unittest.TestCase):
    def _episode(self, tmp: str, words_doc: dict | None, annotation: dict | None,
                 narration: str = NARRATION) -> tuple[Path, list[str], list[str]]:
        ep = Path(tmp) / "ep"
        inp = ep / "input"
        inp.mkdir(parents=True)
        (inp / "script.json").write_text(json.dumps({
            "title": "t", "scenes": [
                {"id": "scene-01", "narration": narration,
                 "board_subject": "s",
                 "elements": [{"id": "panel-1", "phrase": "都长一个样"},
                              {"id": "panel-2", "phrase": "四个助手"},
                              {"id": "panel-3", "phrase": "几乎一样"}]}]},
            ensure_ascii=False), encoding="utf-8")
        if words_doc is not None:
            (inp / "words.json").write_text(json.dumps(words_doc, ensure_ascii=False),
                                            encoding="utf-8")
        ann_dir = ep / "build" / "annotations"
        ann_dir.mkdir(parents=True)
        if annotation is not None:
            (ann_dir / "scene-01.annotation.json").write_text(
                json.dumps(annotation, ensure_ascii=False), encoding="utf-8")
        blockers, warnings, _info = validate(ep)
        return ep, blockers, warnings

    def _assert_contains(self, haystack: list[str], needle: str) -> None:
        self.assertTrue(any(needle in h for h in haystack),
                        f"未找到含「{needle}」的条目；实际：{haystack}")

    # ---- words.json 词表质量 ----

    def test_healthy_words_pass_alignment_guards(self):
        _, blockers, _w = self._episode(tempfile.mkdtemp(),
                                        _words_doc(), _annotation())
        self.assertFalse([b for b in blockers if "words.json" in b and
                          ("乱序" in b or "越出" in b or "相似度" in b or "空" in b)],
                         blockers)
        self.assertFalse([b for b in blockers if "词级锚降级" in b or "对齐降级" in b],
                         blockers)

    def test_out_of_order_words_block(self):
        _, blockers, _w = self._episode(tempfile.mkdtemp(),
                                        _words_doc(shuffle_last_two=True), _annotation())
        self._assert_contains(blockers, "乱序")

    def test_word_beyond_scene_window_blocks(self):
        _, blockers, _w = self._episode(tempfile.mkdtemp(),
                                        _words_doc(shift_last_out=True), _annotation())
        self._assert_contains(blockers, "越出所属幕窗口")

    def test_empty_word_list_blocks(self):
        doc = _words_doc()
        doc["words"] = []
        _, blockers, _w = self._episode(tempfile.mkdtemp(), doc, _annotation())
        self._assert_contains(blockers, "词表为空")

    def test_sentence_granularity_warns(self):
        _, _b, warnings = self._episode(tempfile.mkdtemp(),
                                        _words_doc(granularity="sentence"), _annotation())
        self._assert_contains(warnings, "granularity=sentence")

    def test_mismatched_text_blocks_on_coverage(self):
        wrong = _words_doc(text_override=["完全", "不同", "的词表"] * 4)
        _, blockers, _w = self._episode(tempfile.mkdtemp(), wrong, _annotation())
        self._assert_contains(blockers, "相似度")

    # ---- 标注词级调度零降级 ----

    def test_non_words_schedule_blocks(self):
        _, blockers, _w = self._episode(tempfile.mkdtemp(), _words_doc(),
                                        _annotation(schedule="legacy"))
        self._assert_contains(blockers, "非词级调度")

    def test_partial_matched_blocks(self):
        _, blockers, _w = self._episode(tempfile.mkdtemp(), _words_doc(),
                                        _annotation(matched="2/3"))
        self._assert_contains(blockers, "词级锚降级")

    def test_degrade_warning_keywords_block(self):
        _, blockers, _w = self._episode(
            tempfile.mkdtemp(), _words_doc(),
            _annotation(warnings=["scene-01：panel-2 短语未命中 → 退回区内均分"]))
        self._assert_contains(blockers, "对齐降级")

    def test_annotation_without_meta_blocks_when_words_present(self):
        _, blockers, _w = self._episode(tempfile.mkdtemp(), _words_doc(),
                                        _annotation(schedule=None))
        self._assert_contains(blockers, "非词级调度")


if __name__ == "__main__":
    unittest.main()
