"""review_images 回归测试：板图尺寸归一化 + 文字检测假阳性抑制 + 主题包一致性。

运行：本目录 `uv run pytest -q`（或 uv run python -m unittest discover -s tests -v）
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from whiteboard_story import prompt_builder, review_images  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
BOARD_BGR = (18, 58, 50)  # 深绿板底（≈#153A32）


def _board(w: int = 640, h: int = 360) -> np.ndarray:
    return np.full((h, w, 3), BOARD_BGR, dtype=np.uint8)


def _detect(img: np.ndarray) -> dict:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    return review_images._detect_text_regions(gray, h, w)


class NormalizeBoardSizeTest(unittest.TestCase):
    def _write(self, path: Path, w: int, h: int) -> None:
        cv2.imwrite(str(path), np.full((h, w, 3), BOARD_BGR, dtype=np.uint8))

    def test_scales_aspect_correct_small_image(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "scene-01.png"
            self._write(p, 1200, 675)
            r = review_images.normalize_board_size(p)
            self.assertTrue(r["scaled"])
            self.assertEqual(r["size"], (1200, 675))
            img = cv2.imread(str(p))
            self.assertEqual(img.shape[:2], (1080, 1920))

    def test_scales_other_16x9_sizes(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "scene-02.png"
            self._write(p, 1280, 720)
            r = review_images.normalize_board_size(p)
            self.assertTrue(r["scaled"])
            self.assertEqual(cv2.imread(str(p)).shape[:2], (1080, 1920))

    def test_keeps_standard_size(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "scene-03.png"
            self._write(p, 1920, 1080)
            r = review_images.normalize_board_size(p)
            self.assertFalse(r["scaled"])
            self.assertEqual(r["size"], (1920, 1080))

    def test_keeps_wrong_ratio(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "scene-04.png"
            self._write(p, 1200, 700)  # 非 16:9，交 check_board 报错
            r = review_images.normalize_board_size(p)
            self.assertFalse(r["scaled"])
            self.assertEqual(r["size"], (1200, 700))
            self.assertEqual(cv2.imread(str(p)).shape[:2], (700, 1200))

    def test_host_1792x1024_is_cropped_not_stretched(self):
        """宿主生图的 16:9 家族档位（1792×1024=1.75）：居中裁上下再等比放大。"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "scene-05.png"
            self._write(p, 1792, 1024)
            r = review_images.normalize_board_size(p)
            self.assertTrue(r["scaled"])
            self.assertEqual(r["size"], (1792, 1024))
            self.assertEqual(r["cropped"], (1792, 1008))   # 上下各裁 8px，非左右拉伸
            img = cv2.imread(str(p))
            self.assertEqual(img.shape[:2], (1080, 1920))
            self.assertAlmostEqual(img.shape[1] / img.shape[0], 16 / 9, places=6)

    def test_cropped_board_passes_check_board_aspect(self):
        """归一化的目的：让宿主原图能过 check_board 的长宽比闸口（此前必 failed）。"""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "scene-06.png"
            self._write(p, 1792, 1024)
            self.assertFalse(review_images.check_board(p)["ok"])  # 原图：比例不达标
            review_images.normalize_board_size(p)
            self.assertFalse(any("16:9" in e for e in
                                 review_images.check_board(p)["errors"]))

    def test_rejects_ratio_outside_band(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "scene-07.png"
            self._write(p, 1600, 1000)  # 1.60，超出准入带（ASPECT_TOL=0.03）
            r = review_images.normalize_board_size(p)
            self.assertFalse(r["scaled"])
            self.assertIsNone(r["cropped"])
            self.assertEqual(cv2.imread(str(p)).shape[:2], (1000, 1600))

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "nope.png"
            r = review_images.normalize_board_size(p)
            self.assertFalse(r["scaled"])
            self.assertIsNone(r["size"])


class DetectTextRegionsTest(unittest.TestCase):
    """正负对照夹具。定标背景：chalk 主题探针图的密集图示符号在 v0 链式聚类
    下全部误报为"3 行文字"（warning = 不合格），夹具 C/D 复现该形态。"""

    def test_dark_text_line_detected(self):
        img = _board()
        for i in range(8):  # 等高暗色块、等间距 → 真文字行
            cv2.rectangle(img, (80 + i * 60, 160), (100 + i * 60, 180), (5, 5, 5), -1)
        r = _detect(img)
        self.assertTrue(r["likely_text"])
        self.assertEqual(r["text_line_count"], 1)
        box = r["lines"][0]
        self.assertGreaterEqual(box["n"], 8)
        self.assertLess(box["h"], 360 * 0.05 + 2)  # 行高为字形级

    def test_bright_icon_row_not_flagged(self):
        # 板图典型元素：一排亮色小人图标（自适应阈值在均匀深板上不把亮前景
        # 切成独立组件，且图标行不是文字），不得报警
        img = _board()
        for i in range(8):
            cv2.rectangle(img, (80 + i * 60, 150), (94 + i * 60, 190), (200, 220, 210), -1)
        r = _detect(img)
        self.assertFalse(r["likely_text"])

    def test_noisy_scattered_glyphs_not_flagged(self):
        # 噪声板 + 高度参差、随机散布的亮色图形（探针图假阳性形态）
        img = _board().astype(np.float32)
        rng = np.random.default_rng(7)
        img += rng.normal(0, 8, img.shape)
        img = np.clip(img, 0, 255).astype(np.uint8)
        for _ in range(20):
            x = int(rng.integers(40, 560))
            y = int(rng.integers(40, 300))
            hh = int(rng.integers(10, 60))
            cv2.circle(img, (x, y), max(3, hh // 4), (200, 220, 210), 2)
        r = _detect(img)
        self.assertFalse(r["likely_text"])

    def test_dense_diagram_fragments_not_flagged(self):
        # 密集图示区：榴莲刺/箭头碎片式的碎小组件，v0 链式聚类会串成假行
        img = _board()
        rng = np.random.default_rng(11)
        for i in range(30):
            x = 240 + int(rng.integers(0, 200))
            y = 160 + int(rng.integers(0, 120))
            hh = int(rng.integers(8, 40))
            cv2.line(img, (x, y), (x + int(rng.integers(-10, 10)), y + hh),
                     (210, 225, 215), 2)
        r = _detect(img)
        self.assertFalse(r["likely_text"])


class ThemePaletteConsistencyTest(unittest.TestCase):
    """theme.json palette 与 style-block.txt 是同四个颜色的两处登记，
    曾经四个色值全部漂移（校验侧吃 palette、生成侧吃 style-block）。"""

    def _theme_ids(self) -> list[str]:
        registry = json.loads((REPO_ROOT / "themes" / "registry.json")
                              .read_text(encoding="utf-8"))
        return [t["id"] for t in registry["themes"]]

    def test_registered_theme_dirs_complete(self):
        for tid in self._theme_ids():
            tdir = REPO_ROOT / "themes" / tid
            for name in ("theme.json", "style-block.txt", "probe.json"):
                self.assertTrue((tdir / name).exists(), f"{tid} 缺 {name}")

    def test_palette_values_match_style_block(self):
        for tid in self._theme_ids():
            tdir = REPO_ROOT / "themes" / tid
            theme = json.loads((tdir / "theme.json").read_text(encoding="utf-8"))
            style_block = (tdir / "style-block.txt").read_text(encoding="utf-8")
            for key, hexv in (theme.get("palette") or {}).items():
                self.assertIn(hexv.upper(), style_block.upper(),
                              f"{tid}: palette.{key}={hexv} 不在 style-block 中（双源漂移）")


class PromptBuilderGuardTest(unittest.TestCase):
    def test_scene_prompt_forbids_edge_hand(self):
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            (tdir / "style-block.txt").write_text("test style block", encoding="utf-8")
            payload = prompt_builder.build_scene_payload("scene-01", "a cat", tdir)
            self.assertIn("不要画从画面边缘伸入的手臂", payload["prompt"])

    def test_probe_payload_tolerates_note_field(self):
        with tempfile.TemporaryDirectory() as td:
            tdir = Path(td)
            (tdir / "style-block.txt").write_text("test style block", encoding="utf-8")
            (tdir / "probe.json").write_text(
                json.dumps({"_note": "revision note", "subject": "a board scene"}),
                encoding="utf-8")
            payload = prompt_builder.probe_payload(tdir)
            self.assertIn("a board scene", payload["prompt"])


class StripWatermarkTest(unittest.TestCase):
    """角标水印：判据必须是字形形状＋低对比度，不是面积占比。

    回归自一期实盘：宿主在右下角打 "Qoder AI生成"，非背景像素占比约 10%，
    撞上旧版"占比>5% 即视为内容"的安全上限被整块跳过，六张带水印板图静默通过 import。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "scene-01.png"
        self.board = np.zeros((1080, 1920, 3), np.uint8)
        self.board[:] = BOARD_BGR

    def tearDown(self):
        self.tmp.cleanup()

    def _add_content(self):
        """板图真实内容：穿过右下角的板框描线＋板心一组图形（亮象牙，高对比）。"""
        cv2.rectangle(self.board, (120, 90), (1800, 960), (188, 216, 229), 6)
        cv2.circle(self.board, (900, 500), 90, (188, 216, 229), 5)
        cv2.putText(self.board, "0000", (1350, 950), cv2.FONT_HERSHEY_SIMPLEX, 1.2,
                    (188, 216, 229), 4)

    def _add_watermark(self):
        """半透明角标：逐字打，字差约 32/通道（三通道和差 ~96），落在 45-140 窗口内。

        真实宿主角标就是一排等高、彼此分开的字（实测 9 个连通域、meanDist 67-97），
        连成一团的字串不是水印形状。
        """
        wm = tuple(min(255, int(c) + 32) for c in BOARD_BGR)
        for i, ch in enumerate("QoderAI"):
            cv2.putText(self.board, ch, (1600 + i * 40, 1050), cv2.FONT_HERSHEY_SIMPLEX,
                        1.2, wm, 2, cv2.LINE_AA)

    def test_strips_low_contrast_corner_watermark(self):
        self._add_content()
        self._add_watermark()
        before = self.board.copy()
        cv2.imwrite(str(self.path), before)
        r = review_images.strip_watermark(self.path)
        self.assertTrue(r["detected"], "低对比角标必须被检出，不能静默放过")
        self.assertTrue(r["removed"], f"清除应成功：{r}")
        after = cv2.imread(str(self.path))
        self.assertLess(r["residual_ratio"], review_images.WM_RESIDUAL_THRESHOLD)
        # 角标那一行应回到板底色
        band = after[1015:1058, 1595:1900].astype(np.int16)
        self.assertLess(float(np.abs(band - np.array(BOARD_BGR, np.int16)).sum(2).mean()), 12)
        # 内容不许被连坐：板心图形与板框描线原样保留
        self.assertTrue(np.array_equal(after[410:590, 810:990], before[410:590, 810:990]))
        self.assertTrue(np.array_equal(after[86:96, 200:700], before[86:96, 200:700]))

    def test_leaves_bright_content_alone(self):
        """只有高对比板图内容压在角标带上时，不得当成水印填掉。"""
        self._add_content()
        cv2.imwrite(str(self.path), self.board)
        r = review_images.strip_watermark(self.path)
        self.assertFalse(r["detected"], f"亮色描线不是水印：{r}")
        self.assertTrue(np.array_equal(cv2.imread(str(self.path)), self.board))


if __name__ == "__main__":
    unittest.main()
