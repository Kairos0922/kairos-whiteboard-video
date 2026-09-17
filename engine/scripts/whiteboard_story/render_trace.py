"""笔迹渲染封装：委托自有分区同步内核 kernel.py（2026-08-26 起可用）。

API 签名与原内核保持一致，build_video 上游零改动：
- board_style 仅保留参数位：底色方向（paper/chalk）由内核背景自适应判定，无需显式指定；
- cap_long_edge 当前信息性参数（v1 按板图原分辨率渲染，1920×1080 即原生尺寸）；
- ink_path 固定 skeleton 路线。
"""
from __future__ import annotations

from pathlib import Path

from .kernel import render_region_scene

# 缺省手笔：当期项目 assets/hand-pen.png。没有就让调用方显式传 --hand。
DEFAULT_HAND = Path("assets/hand-pen.png")


def render_scene(board_png: Path, annotation_json: Path, out_mp4: Path,
                 hand_png: Path, total_ms: int | None = None,
                 board_style: str = "paper", fps: int = 30,
                 cap_long_edge: int = 1920, ink_path: str = "skeleton",
                 overlay_png: Path | None = None,
                 fade_from_png: Path | None = None,
                 hand_follow: float = 1.0,
                 labels_json: Path | None = None) -> Path:
    """单幕渲染；成功返回输出路径，失败抛显式异常。"""
    return render_region_scene(Path(board_png), Path(annotation_json), Path(out_mp4),
                               Path(hand_png), fps=fps, total_ms=total_ms,
                               overlay_png=overlay_png, fade_from_png=fade_from_png,
                               hand_follow=hand_follow, labels_json=labels_json)
