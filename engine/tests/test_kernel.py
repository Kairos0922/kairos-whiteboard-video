"""内核单元与冒烟测试：合成夹具小图全链路渲染。

运行：本工具目录 `uv run python -m unittest discover -s tests -v`
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from whiteboard_story import kernel as K  # noqa: E402

W, H = 640, 360
BG = (245, 242, 235)
INK = (72, 62, 54)


def make_fixture(td: str):
    """纸面合成板：layout 边框 + 区A(方框/箭头/色块) + 区B(双横线)。"""
    root = Path(td)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, W - 9, H - 9], outline=INK, width=4)          # layout 边框
    # 区A：方框 + 箭头 + 填充圆
    ax, ay, aw, ah = 30, 50, 250, 250
    d.rectangle([ax, ay, ax + aw, ay + ah], outline=INK, width=4)
    d.line([ax + 20, ay + 40, ax + 200, ay + 40], fill=INK, width=5)
    d.polygon([(ax + 220, ay + 40), (ax + 195, ay + 28), (ax + 195, ay + 52)], fill=INK)
    d.ellipse([ax + 60, ay + 140, ax + 180, ay + 230], fill=(178, 58, 58))
    # 区B：两条横线
    bx, by = 360, 80
    d.line([bx, by, bx + 240, by], fill=INK, width=6)
    d.line([bx, by + 90, bx + 240, by + 90], fill=INK, width=6)

    def elem(eid, seq, r, start, dur):
        return {"id": eid, "sequence": seq,
                "region": {"x": r[0], "y": r[1], "width": r[2], "height": r[3]},
                "reveal": {"startMs": start, "durationMs": dur, "protectedRegions": []},
                "handPath": {"start": [W // 2, 20], "end": [W // 2, H - 20]}, "kind": "panel"}

    ann = {"canvas": {"width": W, "height": H}, "sceneDurationMs": 3800,
           "elements": [
               elem("layout", 0, (0, 0, W, H), 100, 500),
               elem("panel-1", 1, (20, 40, 270, 270), 700, 1300),
               elem("panel-2", 2, (350, 60, 260, 140), 2100, 1100),
           ]}
    board_p, ann_p, hand_p = root / "b.png", root / "a.json", root / "h.png"
    img.save(board_p)
    ann_p.write_text(json.dumps(ann), encoding="utf-8")
    himg = Image.new("RGBA", (48, 96), (0, 0, 0, 0))
    hd = ImageDraw.Draw(himg)
    hd.rectangle([14, 10, 34, 86], fill=(120, 90, 60, 255))          # 笔杆
    hd.polygon([(17, 2), (31, 2), (24, 18)], fill=(40, 40, 40, 255))  # 笔尖朝上
    himg.save(hand_p)
    return board_p, ann_p, hand_p


def np_img(color):
    arr = np.zeros((H, W, 3), dtype=np.uint8)
    arr[:] = color
    return arr


class InkExtractionTest(unittest.TestCase):
    def test_bg_adaptive_and_ink_mask(self):
        img = np_img((255, 255, 255))
        img[H // 2 - 20:H // 2 + 20, W // 2 - 20:W // 2 + 20] = (40, 40, 40)
        mask = K.extract_ink_mask(img)
        self.assertFalse(mask[:10, :10].any())          # 纯背景处无墨
        self.assertTrue(mask[H // 2, W // 2])           # 深色方块判墨

    def test_dark_board_uses_light_ink(self):
        img = np_img((32, 58, 48))                      # 黑板绿底
        img[H // 2 - 20:H // 2 + 20, W // 2 - 20:W // 2 + 20] = (245, 245, 245)
        mask = K.extract_ink_mask(img)
        self.assertTrue(mask[H // 2, W // 2])           # 深底上的亮笔判墨
        self.assertFalse(mask[:10, :10].any())


class ScheduleTest(unittest.TestCase):
    def test_assign_and_windows(self):
        with tempfile.TemporaryDirectory() as td:
            b, a, _h = make_fixture(td)
            from whiteboard_story.kernel import (build_tasks, load_board_layers,
                                                 parse_annotation)
            board, _ink, skel = load_board_layers(b)
            strokes = K_board_strokes(b)
            ann = parse_annotation(a)
            tasks = build_tasks(ann.elements, board, strokes, skeleton=skel)
            draws = [t for t in tasks if t.kind == "draw"]
            travels = [t for t in tasks if t.kind == "travel"]
            self.assertGreater(len(draws), 4)
            self.assertGreater(len(travels), 0)
            # 每个绘制任务的点必须落在其归属元素矩形内（Task.eid 是编排真值）
            by_id = {e.eid: e for e in ann.elements}
            for t in tasks:
                if t.kind != "draw":
                    continue
                self.assertTrue(t.eid, "绘制任务缺少 eid 归属")
                cx = float(t.pts[:, 0].mean())
                cy = float(t.pts[:, 1].mean())
                self.assertTrue(by_id[t.eid].contains(cx, cy),
                                f"{t.start_ms}ms 点({cx},{cy}) 不在 {t.eid} 矩形内")
            # 时间单调不回退
            ends = [t.end_ms for t in tasks]
            self.assertEqual(ends, sorted(ends))


def K_npy_board(p: Path):
    import numpy as np
    return np.asarray(Image.open(p).convert("RGB"))


def K_board_strokes(p: Path):
    from whiteboard_story.kernel import board_to_strokes
    return board_to_strokes(p)


class RenderSmokeTest(unittest.TestCase):
    def test_full_chain_small(self):
        with tempfile.TemporaryDirectory() as td:
            b, a, h = make_fixture(td)
            out = Path(td) / "scene.mp4"
            K.render_region_scene(b, a, out, h, fps=12)
            self.assertTrue(out.exists() and out.stat().st_size > 10_000)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(out)],
                capture_output=True, text=True, check=True)
            duration = float(probe.stdout.strip())
            self.assertAlmostEqual(duration, 3.8, delta=0.45)


class ClipStrokesTest(unittest.TestCase):
    def test_protected_points_removed_and_runs_split(self):
        s = np.asarray([(10, 10), (20, 10), (30, 10), (55, 10), (90, 10), (100, 10)],
                       dtype=np.int32)
        out = K._clip_strokes([s], ((40, 0, 30, 20),))          # 55 在保护区内
        self.assertEqual(2, len(out))
        self.assertEqual([(10, 10), (20, 10), (30, 10)], [tuple(p) for p in out[0]])
        self.assertEqual([(90, 10), (100, 10)], [tuple(p) for p in out[1]])

    def test_single_kept_point_dropped(self):
        s = np.asarray([(10, 10), (55, 10), (60, 10)], dtype=np.int32)
        self.assertEqual([], K._clip_strokes([s], ((40, 0, 30, 20),)))

    def test_no_protected_passthrough(self):
        s = np.asarray([(1, 1), (2, 2)], dtype=np.int32)
        self.assertEqual([s], K._clip_strokes([s], ()))


def _make_ops_fixture(td: str, protected: bool, ops_count: int):
    """两分区（或单分区）合成板，供方案 A 两个测试使用。"""
    root = Path(td)
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, W - 9, H - 9], outline=INK, width=4)
    p1 = (20, 40, 200, 280)
    p2 = (320, 40, 280, 280)
    # panel-2 内三个分离对象（或一条横线）
    if ops_count >= 3:
        for x0 in (340, 430, 520):
            d.rectangle([x0, 70, x0 + 60, 130], outline=INK, width=4)
            d.line([x0 + 10, 200, x0 + 50, 200], fill=INK, width=5)
    else:
        d.line([330, 100, 590, 100], fill=INK, width=6)
        d.line([140, 250, 560, 250], fill=INK, width=6)   # 穿越 panel-1 的长横
    # panel-1 内一个方框（被保护区覆盖的对象）
    d.rectangle([40, 60, 180, 200], outline=INK, width=4)

    def elem(eid, seq, r, start, dur, ops=0, prot=()):
        el = {"id": eid, "sequence": seq,
              "region": {"x": r[0], "y": r[1], "width": r[2], "height": r[3]},
              "reveal": {"startMs": start, "durationMs": dur,
                         "protectedRegions": [
                             {"x": pr[0], "y": pr[1], "width": pr[2], "height": pr[3]}
                             for pr in prot]},
              "handPath": {"start": [W // 2, 20], "end": [W // 2, H - 20]},
              "kind": "panel"}
        if ops:
            el["ops"] = [{"op": "DRAW", "target": f"obj-{i}", "bound_span": i}
                         for i in range(ops)]
        return el

    ann = {"canvas": {"width": W, "height": H}, "sceneDurationMs": 4000,
           "elements": [
               elem("layout", 0, (0, 0, W, H), 100, 500),
               elem("panel-1", 1, p1, 700, 1200),
               elem("panel-2", 2, p2, 2000, 1500, ops=ops_count,
                    prot=(p1,) if protected else ()),
           ]}
    board_p, ann_p, hand_p = root / "b.png", root / "a.json", root / "h.png"
    img.save(board_p)
    ann_p.write_text(json.dumps(ann), encoding="utf-8")
    himg = Image.new("RGBA", (48, 96), (0, 0, 0, 0))
    himg.save(hand_p)
    return board_p, ann_p, hand_p


class ProtectedRegionsTest(unittest.TestCase):
    def test_later_panel_does_not_reink_protected_region(self):
        with tempfile.TemporaryDirectory() as td:
            b, a, _h = _make_ops_fixture(td, protected=True, ops_count=1)
            board, _ink, skel = K.load_board_layers(b)
            ann = K.parse_annotation(a)
            self.assertEqual(1, len(ann.elements[2].protected))
            tasks = K.build_tasks(ann.elements, board, K.board_to_strokes(b),
                                  skeleton=skel)
            px, py, pw, ph = ann.elements[2].protected[0]
            for t in tasks:
                if t.kind != "draw" or t.eid != "panel-2":
                    continue
                inside = ((t.pts[:, 0] >= px) & (t.pts[:, 0] < px + pw)
                          & (t.pts[:, 1] >= py) & (t.pts[:, 1] < py + ph))
                self.assertFalse(inside.any(),
                                 f"panel-2 在保护区复墨：{int(inside.sum())} 点")

    def test_without_protection_crossing_stroke_survives(self):
        with tempfile.TemporaryDirectory() as td:
            b, a, _h = _make_ops_fixture(td, protected=False, ops_count=1)
            board, _ink, skel = K.load_board_layers(b)
            ann = K.parse_annotation(a)
            tasks = K.build_tasks(ann.elements, board, K.board_to_strokes(b),
                                  skeleton=skel)
            px, py, pw, ph = 20, 40, 200, 280
            hit = False
            for t in tasks:
                if t.kind == "draw" and t.eid == "panel-2":
                    inside = ((t.pts[:, 0] >= px) & (t.pts[:, 0] < px + pw)
                              & (t.pts[:, 1] >= py) & (t.pts[:, 1] < py + ph))
                    hit = hit or bool(inside.any())
            self.assertTrue(hit, "未设保护区时，跨界笔画应原样保留（对照组）")


class OpsSubwindowTest(unittest.TestCase):
    def test_three_ops_yield_three_ordered_subwindows(self):
        with tempfile.TemporaryDirectory() as td:
            b, a, _h = _make_ops_fixture(td, protected=True, ops_count=3)
            board, _ink, skel = K.load_board_layers(b)
            ann = K.parse_annotation(a)
            self.assertEqual(3, ann.elements[2].ops_count)
            tasks = K.build_tasks(ann.elements, board, K.board_to_strokes(b),
                                  skeleton=skel)
            p2 = [t for t in tasks if t.eid == "panel-2"]
            self.assertGreater(len(p2), 2)
            # 逐对象完成（2026-09-04 口径）：夹具有 6 个连通对象（3 方框 + 3 横线），
            # 每个对象一个相继时间槽，槽间留 SUB_WINDOW_GAP_MS（120ms）> 抬笔间隙 90ms
            clusters: list[list] = []
            cur: list = []
            for t in p2:
                if cur and t.start_ms > cur[-1].end_ms + 100:
                    clusters.append(cur)
                    cur = []
                cur.append(t)
            if cur:
                clusters.append(cur)
            self.assertEqual(6, len(clusters), "6 个对象应各占一个时间子窗")
            for c in clusters:
                self.assertEqual("panel-2", c[0].eid)
            # 子窗严格时序：后一簇起点晚于前一簇终点（含间隔）
            for prev, nxt in zip(clusters, clusters[1:]):
                self.assertLess(prev[-1].end_ms, nxt[0].start_ms)
                self.assertGreaterEqual(nxt[0].start_ms - prev[-1].end_ms,
                                        K.SUB_WINDOW_GAP_MS - 5)
            # 全部任务仍在 panel-2 窗口内
            el = ann.elements[2]
            self.assertGreaterEqual(min(t.start_ms for t in p2), el.start_ms)
            self.assertLessEqual(max(t.end_ms for t in p2),
                                 el.start_ms + el.duration_ms + 1)

    def test_outline_then_fill_per_object(self):
        """鬼影修复的行为验证（逐对象推进）：下方对象（y=200 横线）的完成时间
        早于上方最后对象完成后再画完全部的旧模式——具体断言：每个对象槽起笔
        时，之前所有槽都已收尾（不存在两对象同时进行），且总跨度覆盖全部笔画。"""
        with tempfile.TemporaryDirectory() as td:
            b, a, _h = _make_ops_fixture(td, protected=True, ops_count=3)
            board, _ink, skel = K.load_board_layers(b)
            ann = K.parse_annotation(a)
            tasks = K.build_tasks(ann.elements, board, K.board_to_strokes(b),
                                  skeleton=skel)
            p2 = sorted([t for t in tasks if t.eid == "panel-2" and t.kind == "draw"],
                        key=lambda x: x.start_ms)
            self.assertGreaterEqual(len(p2), 6)
            # 严格串行：下一笔起笔不早于上一笔收尾（同槽内也无重叠）
            for prev, nxt in zip(p2, p2[1:]):
                self.assertLessEqual(prev.end_ms, nxt.start_ms + 1)
            # 阅读顺序推进：先完成的笔画 y 均值不大于后完成的 + 容差（上→下）
            ys = [t.pts[:, 1].mean() for t in p2]
            for i in range(len(ys) - 1):
                self.assertLessEqual(ys[i], ys[i + 1] + 15,
                                     "对象应按阅读顺序（上→下）逐个完成")


if __name__ == "__main__":
    unittest.main()
