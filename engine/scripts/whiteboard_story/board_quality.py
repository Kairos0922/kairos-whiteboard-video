#!/usr/bin/env python3
"""板图质量自动化检查（2026-09-05 新增）。

在板图 import 后、layout/annotate 前自动运行，拦截已知问题：
- 分辨率/比例错误
- 底色不均（渐变/杂色，不是干净的黑板/纸本）
- 四角水印（平台残留）
- 墨迹不足（纯背景/生图失败）
- layout panels 重叠（区域划分错误）
- layout panels 间距不足（导致对象分组失效、元素互相连接）

检查结果分 error（阻断，必须重生成）和 warning（提示，人工确认）。
用法：checks = run_board_checks(board_png, layout_json) → list of {level, code, message}
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

# 标准分辨率（16:9）
STANDARD_WIDTH = 1920
STANDARD_HEIGHT = 1080
STANDARD_RATIO = 16 / 9

# 水印检测：四角检查区域大小
WATERMARK_CORNER_SIZE = 150
WATERMARK_INK_RATIO_THRESHOLD = 0.08  # 四角区域墨迹占比超过此值警告

# 墨迹检测：整图墨迹占比下限
INK_RATIO_MIN = 0.01  # 低于 1% 视为墨迹不足（纯背景/生图失败）

# 底色检测：四边中位色与中心色的差异阈值
BG_UNIFORMITY_THRESHOLD = 30  # 三通道总差异超过此值视为底色不均

# panel 间距检查
PANEL_MIN_GAP = 20  # 相邻 panels 之间最小间距（px）


def _estimate_bg(img: np.ndarray) -> tuple[int, int, int]:
    """四边中位色估背景。"""
    bands = np.concatenate([
        img[:8].reshape(-1, 3), img[-8:].reshape(-1, 3),
        img[:, :8].reshape(-1, 3), img[:, -8:].reshape(-1, 3),
    ])
    return tuple(int(v) for v in np.median(bands, axis=0))


def _ink_mask(img: np.ndarray) -> np.ndarray:
    """色距判墨：|px-bg| 三通道总距离 > 阈值×3。"""
    bg = np.array(_estimate_bg(img))
    dist = np.abs(img.astype(np.int16) - bg).sum(axis=2)
    return dist > 60 * 3  # INK_THRESHOLD=60


def check_resolution(img: np.ndarray) -> dict | None:
    """检查分辨率是否为 1920x1080（16:9）。"""
    h, w = img.shape[:2]
    ratio = w / h if h > 0 else 0
    if w == STANDARD_WIDTH and h == STANDARD_HEIGHT:
        return None
    if abs(ratio - STANDARD_RATIO) < 0.01:
        return {"level": "warning", "code": "RESOLUTION_NONSTANDARD",
                "message": f"分辨率 {w}x{h} 非标准 1920x1080（比例正确，建议缩放）"}
    return {"level": "error", "code": "RESOLUTION_WRONG_RATIO",
            "message": f"分辨率 {w}x{h} 比例 {ratio:.2f} 非 16:9（标准 {STANDARD_RATIO:.2f}），必须重生成"}


def check_background(img: np.ndarray) -> dict | None:
    """检查底色是否均匀（四边中位色 vs 中心区域色）。"""
    h, w = img.shape[:2]
    bg_edges = _estimate_bg(img)
    # 中心区域（排除边缘 10%）
    cy0, cy1 = int(h * 0.1), int(h * 0.9)
    cx0, cx1 = int(w * 0.1), int(w * 0.9)
    center = img[cy0:cy1, cx0:cx1]
    bg_center = tuple(int(v) for v in np.median(center.reshape(-1, 3), axis=0))
    diff = sum(abs(a - b) for a, b in zip(bg_edges, bg_center))
    if diff > BG_UNIFORMITY_THRESHOLD:
        return {"level": "warning", "code": "BG_NONUNIFORM",
                "message": f"底色不均：边缘 {bg_edges} vs 中心 {bg_center}（差异 {diff} > {BG_UNIFORMITY_THRESHOLD}），可能是渐变背景"}
    return None


def check_watermark(img: np.ndarray) -> list[dict]:
    """检查四角是否有水印（小区域墨迹占比过高）。"""
    h, w = img.shape[:2]
    s = min(WATERMARK_CORNER_SIZE, h // 4, w // 4)
    ink = _ink_mask(img)
    corners = [
        ("top-left", 0, 0, s, s),
        ("top-right", w - s, 0, w, s),
        ("bottom-left", 0, h - s, s, h),
        ("bottom-right", w - s, h - s, w, h),
    ]
    results = []
    for name, x0, y0, x1, y1 in corners:
        region = ink[y0:y1, x0:x1]
        ratio = region.sum() / region.size if region.size > 0 else 0
        if ratio > WATERMARK_INK_RATIO_THRESHOLD:
            results.append({"level": "warning", "code": f"WATERMARK_{name.upper()}",
                            "message": f"{name} 角 {s}x{s} 区域墨迹占比 {ratio:.1%} > {WATERMARK_INK_RATIO_THRESHOLD:.0%}，可能有水印"})
    return results


def check_ink_presence(img: np.ndarray) -> dict | None:
    """检查板图是否有足够墨迹（不是纯背景/生图失败）。"""
    ink = _ink_mask(img)
    ratio = ink.sum() / ink.size
    if ratio < INK_RATIO_MIN:
        return {"level": "error", "code": "INK_INSUFFICIENT",
                "message": f"整图墨迹占比 {ratio:.2%} < {INK_RATIO_MIN:.0%}，可能是纯背景或生图失败"}
    return None


def check_panel_overlap(panels: list[dict]) -> list[dict]:
    """检查 layout panels 是否重叠。"""
    results = []
    for i in range(len(panels)):
        for j in range(i + 1, len(panels)):
            p1, p2 = panels[i], panels[j]
            x1, y1, w1, h1 = p1["x"], p1["y"], p1["width"], p1["height"]
            x2, y2, w2, h2 = p2["x"], p2["y"], p2["width"], p2["height"]
            # 矩形相交检测
            overlap_x = max(0, min(x1 + w1, x2 + w2) - max(x1, x2))
            overlap_y = max(0, min(y1 + h1, y2 + h2) - max(y1, y2))
            if overlap_x > 0 and overlap_y > 0:
                area = overlap_x * overlap_y
                results.append({"level": "error", "code": "PANEL_OVERLAP",
                                "message": f"panel-{i + 1} 与 panel-{j + 1} 重叠 {overlap_x}x{overlap_y}px（面积 {area}），必须调整 layout"})
    return results


def check_panel_gap(panels: list[dict]) -> list[dict]:
    """检查相邻 panels 之间是否有足够留白（防止对象分组失效、元素互相连接）。"""
    results = []
    for i in range(len(panels)):
        for j in range(i + 1, len(panels)):
            p1, p2 = panels[i], panels[j]
            x1, y1, w1, h1 = p1["x"], p1["y"], p1["width"], p1["height"]
            x2, y2, w2, h2 = p2["x"], p2["y"], p2["width"], p2["height"]
            # 计算两个矩形之间的最小间距
            # 水平间距
            if x1 + w1 <= x2:
                gap_x = x2 - (x1 + w1)
            elif x2 + w2 <= x1:
                gap_x = x1 - (x2 + w2)
            else:
                gap_x = 0  # 水平重叠
            # 垂直间距
            if y1 + h1 <= y2:
                gap_y = y2 - (y1 + h1)
            elif y2 + h2 <= y1:
                gap_y = y1 - (y2 + h2)
            else:
                gap_y = 0  # 垂直重叠
            # 如果两个矩形在水平或垂直方向上相邻（不重叠），检查间距
            if gap_x > 0 and gap_y == 0:
                # 水平相邻
                if gap_x < PANEL_MIN_GAP:
                    results.append({"level": "warning", "code": "PANEL_GAP_SMALL",
                                    "message": f"panel-{i + 1} 与 panel-{j + 1} 水平间距 {gap_x}px < {PANEL_MIN_GAP}px，可能导致元素互相连接"})
            elif gap_y > 0 and gap_x == 0:
                # 垂直相邻
                if gap_y < PANEL_MIN_GAP:
                    results.append({"level": "warning", "code": "PANEL_GAP_SMALL",
                                    "message": f"panel-{i + 1} 与 panel-{j + 1} 垂直间距 {gap_y}px < {PANEL_MIN_GAP}px，可能导致元素互相连接"})
    return results


def run_board_checks(board_png: Path, layout_json: Path | None = None) -> list[dict]:
    """运行全部板图质量检查，返回检查结果列表。

    Args:
        board_png: 板图 PNG 路径
        layout_json: layout.json 路径（可选，提供时运行 panels 重叠/间距检查）

    Returns:
        list of {level: "error"|"warning", code: str, message: str}
        空列表表示全部通过。
    """
    results: list[dict] = []
    img = np.asarray(Image.open(board_png).convert("RGB"))

    # 图像级检查
    for check_fn in (check_resolution, check_background, check_ink_presence):
        result = check_fn(img)
        if result:
            results.append(result)
    results.extend(check_watermark(img))

    # layout 级检查
    if layout_json is not None and Path(layout_json).exists():
        layout = json.loads(Path(layout_json).read_text(encoding="utf-8"))
        panels = layout.get("panels") or []
        if panels:
            results.extend(check_panel_overlap(panels))
            results.extend(check_panel_gap(panels))

    return results


def format_checks(checks: list[dict]) -> str:
    """格式化检查结果为可读文本。"""
    if not checks:
        return "全部通过 ✓"
    errors = [c for c in checks if c["level"] == "error"]
    warnings = [c for c in checks if c["level"] == "warning"]
    lines = []
    if errors:
        lines.append(f"❌ {len(errors)} 个错误（阻断）：")
        for e in errors:
            lines.append(f"  [{e['code']}] {e['message']}")
    if warnings:
        lines.append(f"⚠️  {len(warnings)} 个警告（人工确认）：")
        for w in warnings:
            lines.append(f"  [{w['code']}] {w['message']}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python board_quality.py <board.png> [layout.json]")
        sys.exit(1)
    board = Path(sys.argv[1])
    layout = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    checks = run_board_checks(board, layout)
    print(format_checks(checks))
    sys.exit(1 if any(c["level"] == "error" for c in checks) else 0)
