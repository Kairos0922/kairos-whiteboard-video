"""标注器方案 A 测试：ops[] 切片与 protectedRegions 生成（ir-alignment §5 定论 A）。

运行：本工具目录 `uv run python -m unittest discover -s tests -v`
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from whiteboard_story import make_annotations_v2 as MA  # noqa: E402  (先导入：注册平铺 apply_layout)
import apply_layout  # noqa: E402  # 平铺模块——load_scene_layout 读的是这一份全局


def _units(texts: list[str], scene_index: int, t0: int = 100, step: int = 100):
    out = []
    t = t0
    for chunk in texts:
        for c in chunk:
            out.append({"scene_index": scene_index, "text": c,
                        "start_ms": t, "end_ms": t + step})
            t += step
    return out


def _doc():
    beat = {
        "id": "b1",
        "state_before": "空", "state_after": "有",
        "cognitive_operation": "EXPLAIN", "obstacle": "MISSING",
        "narration_goal": "x", "visual_goal": "x",
        "expression_goal": {"attention_target": "x"},
        "narrative": {"function": "EXPLAIN",
                      "spans": ["第一步开始了。", "第二步也来了。", "收尾了。"]},
        "visual": {"state_before": "空", "state_after": "满"},
        "reveal": [
            {"op": "DRAW", "target": "a", "bound_span": 0},
            {"op": "CONNECT", "target": "b", "bound_span": 1},
            {"op": "DRAW", "target": "c", "bound_span": 2},
        ],
        "channel_allocation": {"verbal": ["x"], "visual": ["x"], "shared": ["x"]},
        "elements": [{"id": "a", "semantic_role": "x", "cognitive_function": "x",
                      "introduced_at": "b1", "used_by": ["b1"]}],
        "scene_slice": ["scene-01", "scene-02"],
    }
    return {
        "scenes": [
            {"id": "scene-01", "beat_refs": ["b1"], "beats": [beat],
             "narration": "第一步开始了。第二步也来了。",
             "elements": [{"id": "panel-1", "phrase": "第一步"},
                           {"id": "panel-2", "phrase": "第二步"}]},
            {"id": "scene-02", "beat_refs": ["b1"], "beats": [],
             "narration": "收尾了。",
             "elements": [{"id": "panel-1", "phrase": "收尾"}]},
        ]
    }


class AnnotatorOpsTest(unittest.TestCase):
    def setUp(self):
        self._old = dict(apply_layout.SCENE_PANELS)
        apply_layout.SCENE_PANELS.update({
            "scene-01": [("panel", 40, 60, 600, 400, "blue"),
                         ("panel", 700, 60, 600, 400, "red")],
            "scene-02": [("panel", 40, 60, 1200, 400, "blue")],
        })

    def tearDown(self):
        apply_layout.SCENE_PANELS.clear()
        apply_layout.SCENE_PANELS.update(self._old)

    def test_cross_scene_beat_ops_sliced_by_sentence_count(self):
        doc = _doc()
        warnings: list[str] = []
        ann1 = MA.build_annotation_words(
            "scene-01", 12000, doc["scenes"][0]["elements"],
            _units(["第一步开始了", "第二步也来了"], 0), warnings,
            scene_window={"start_ms": 0, "end_ms": 12000},
            episode_dir=None, script_doc=doc)
        p1 = ann1["elements"][1]
        p2 = ann1["elements"][2]
        # scene-01 两句 → b1 的 bound_span 0/1 两个 op，一一分区对应
        self.assertEqual([{"op": "DRAW", "target": "a", "bound_span": 0}], p1["ops"])
        self.assertEqual([{"op": "CONNECT", "target": "b", "bound_span": 1}], p2["ops"])
        # 保护区：panel-2 覆盖 panel-1 的 region（版式层不算）
        self.assertEqual([], p1["reveal"]["protectedRegions"])
        self.assertEqual([p1["region"]], p2["reveal"]["protectedRegions"])

        ann2 = MA.build_annotation_words(
            "scene-02", 6000, doc["scenes"][1]["elements"],
            _units(["收尾了"], 1), warnings,
            scene_window={"start_ms": 12000, "end_ms": 18000},
            episode_dir=None, script_doc=doc)
        q1 = ann2["elements"][1]
        self.assertEqual([{"op": "DRAW", "target": "c", "bound_span": 0}], q1["ops"])

    def test_no_script_doc_keeps_legacy_shape(self):
        warnings: list[str] = []
        ann = MA.build_annotation_words(
            "scene-01", 12000,
            [{"id": "panel-1", "phrase": "第一步"},
             {"id": "panel-2", "phrase": "第二步"}],
            _units(["第一步开始了", "第二步也来了"], 0), warnings,
            scene_window={"start_ms": 0, "end_ms": 12000},
            episode_dir=None, script_doc=None)
        for el in ann["elements"][1:]:
            self.assertNotIn("ops", el)                       # 旧期次零侵入
            self.assertEqual([], el["reveal"]["protectedRegions"])


if __name__ == "__main__":
    unittest.main()
