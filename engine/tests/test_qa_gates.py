"""qa_gates 纯判据单测：扫荡窗 / 切幕 / 残影 / 缺墨 / 响度解析（不依赖 ffmpeg）。

运行：engine 目录 `uv run pytest -q`
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from whiteboard_story import qa_gates as Q  # noqa: E402
from whiteboard_story.kernel import Task  # noqa: E402


def T(kind, s, e, length=0.0):
    return Task(kind=kind, start_ms=s, end_ms=e, length=length)


class SweepWindowsTest(unittest.TestCase):
    def test_sweep_pattern_flagged(self):
        # 2s 窗内 travel 合计 1.6s、draw 弧长仅 30px = 手在动而墨不长
        tasks = [T("draw", 0, 100, 10), T("travel", 100, 500),
                 T("draw", 500, 600, 10), T("travel", 600, 1300),
                 T("draw", 1300, 1400, 10), T("travel", 1400, 2100)]
        self.assertGreater(Q.sweep_windows(tasks, 4000), 0)

    def test_normal_reveal_clean(self):
        # 每个 2s 窗都有实质落墨（弧长 >> 60px）
        tasks = []
        for i in range(8):
            s = i * 500
            tasks.append(T("draw", s, s + 450, 400))
            tasks.append(T("travel", s + 450, s + 500))
        self.assertEqual(Q.sweep_windows(tasks, 4000), 0)

    def test_long_narration_gap_clean(self):
        # 纯旁白空档（gaze，无 travel）不算扫荡：手离画，观感正确
        tasks = [T("draw", 0, 800, 500), T("gaze", 800, 6000),
                 T("draw", 6000, 6800, 500)]
        self.assertEqual(Q.sweep_windows(tasks, 8000), 0)


class WipeMetricsTest(unittest.TestCase):
    def test_gradual_wipe_passes(self):
        frames = np.stack([np.full((4, 4), 20 + i * 4, np.int16) for i in range(21)])
        hard, cum = Q.wipe_metrics(frames)
        self.assertLess(hard, Q.WIPE_MAX_FRAME)
        self.assertGreater(cum, Q.WIPE_MIN_CUM)

    def test_hard_cut_flagged(self):
        frames = np.stack([np.full((4, 4), 20, np.int16)] * 10 +
                          [np.full((4, 4), 200, np.int16)] * 10)
        hard, _cum = Q.wipe_metrics(frames)
        self.assertGreaterEqual(hard, Q.WIPE_MAX_FRAME)


class GhostAndInkTest(unittest.TestCase):
    def test_ghost_dev_zero_on_clean_bg(self):
        frame = np.zeros((1080, 1920, 3), np.int16)
        frame[:] = np.array([23, 61, 53], np.int16)
        self.assertLess(Q.ghost_dev(frame, (23, 61, 53)), 1e-9)

    def test_ghost_dev_high_with_residual_ink(self):
        frame = np.zeros((1080, 1920, 3), np.int16)
        frame[:] = np.array([23, 61, 53], np.int16)
        frame[502:930, 400:1200] = 220          # 上一幕残墨
        self.assertGreater(Q.ghost_dev(frame, (23, 61, 53)), Q.GHOST_MAX_DEV)

    def test_missing_ink_ratio(self):
        b = np.zeros((10, 10), bool)
        b[2:8, 2:8] = True
        f = b.copy()
        f[7, 7] = False
        self.assertAlmostEqual(Q.missing_ink_ratio(b, f), 1 / 36, places=6)
        self.assertEqual(Q.missing_ink_ratio(b, b), 0.0)

    def test_bg_estimate_keeps_input_channel_order(self):
        # run_all 拿 RGB 板图估底色、再与 RGB 解码帧比；若调用侧传 BGR 会通道错位
        # 虚高残影约 20（2026-09-18 实盘假阻断），此测试钉住契约。
        from whiteboard_story.kernel import estimate_bg
        img = np.zeros((60, 60, 3), np.uint8)
        img[:] = np.array([23, 61, 53], np.uint8)
        self.assertEqual(tuple(int(c) for c in estimate_bg(img)), (23, 61, 53))


class LufsParseTest(unittest.TestCase):
    def test_parse_summary(self):
        s = ("Summary:\n  Integrated loudness:\n    I:         -16.5 LUFS\n"
             "  True peak:\n    Peak:       -1.5 dBFS\n")
        lufs, tp = Q.parse_lufs(s)
        self.assertEqual((lufs, tp), (-16.5, -1.5))
        self.assertTrue(Q.LUFS_TARGET[0] <= lufs <= Q.LUFS_TARGET[1])
        self.assertTrue(Q.TP_TARGET[0] <= tp <= Q.TP_TARGET[1])


if __name__ == "__main__":
    unittest.main()
