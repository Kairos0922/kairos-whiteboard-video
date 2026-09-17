#!/usr/bin/env python3
"""版式层：虚线外框 + 分格圆角边框 + 编号圈。坐标来自当期 input/layout.json。

板图 1920x1080。编号与标签由本层叠加，不进生图。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
DASH = (71, 111, 139)
PANEL_COLORS = {
    "blue": (142, 110, 78), "red": (78, 94, 166), "orange": (74, 123, 176),
    "green": (90, 142, 107), "purple": (153, 92, 122),
}
BORDER_W, RADIUS, INSET = 4, 30, 30
BADGE_R = 48
INK = (229, 216, 188)  # 主题象牙白 #E5D8BC：标签叠在黑板绿上，纸面墨色几乎不可见
FONT_DIGIT = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")
FONT_CN = Path("/System/Library/Fonts/STHeiti Medium.ttc")

# 测试可 patch；正式路径读 input/layout.json。
SCENE_PANELS: dict[str, list] = {}
SCENE_TEXTS: dict[str, list] = {}


def load_scene_layout(scene_id: str, episode_dir: Path | None = None) -> dict:
    panels: list = list(SCENE_PANELS.get(scene_id, []))
    texts: list = list(SCENE_TEXTS.get(scene_id, []))
    if episode_dir:
        p = Path(episode_dir) / "input" / "layout.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            sc = data.get(scene_id) or data.get("scenes", {}).get(scene_id) or {}
            file_panels = []
            for pan in sc.get("panels", []):
                file_panels.append((
                    "panel", int(pan["x"]), int(pan["y"]),
                    int(pan["w"]), int(pan["h"]), pan.get("color", "blue"),
                ))
            if file_panels:
                panels = file_panels
            file_texts = []
            for t in sc.get("texts", []):
                font = FONT_CN if t.get("font") == "cn" else FONT_DIGIT
                file_texts.append((t["text"], int(t["cx"]), int(t["cy"]),
                                   int(t.get("size", 80)), font,
                                   int(t.get("panel", 0))))
            if file_texts:
                texts = file_texts
    return {"panels": panels, "texts": texts}


def draw_dashed_rect(d: ImageDraw, x0, y0, x1, y1, dash=34, gap=26, width=6):
    def seg(a, b):
        length = abs(b - a)
        pos = 0
        while pos < length:
            end = min(pos + dash, length)
            yield a + pos, a + end
            pos = end + gap

    for s, e in seg(x0, x1):
        d.line([s, y0, e, y0], fill=DASH, width=width)
        d.line([s, y1, e, y1], fill=DASH, width=width)
    for s, e in seg(y0, y1):
        d.line([x0, s, x0, e], fill=DASH, width=width)
        d.line([x1, s, x1, e], fill=DASH, width=width)


def _draw_texts(d: ImageDraw.ImageDraw, layout: dict) -> list[dict]:
    """叠标签并返回标签清单（[{text, bbox, panel}]），供渲染内核按 panel 延迟揭示。"""
    out: list[dict] = []
    for item in layout["texts"]:
        text, cx, cy, size, font_path = item[:5]
        panel = int(item[5]) if len(item) > 5 else 0
        f = ImageFont.truetype(str(font_path), size)
        tb = d.textbbox((0, 0), text, font=f)
        x = cx - (tb[2] - tb[0]) / 2 - tb[0]
        y = cy - (tb[3] - tb[1]) / 2 - tb[1]
        d.text((x, y), text, font=f, fill=INK)
        out.append({"text": text, "panel": panel,
                    "bbox": [int(x + tb[0]) - 6, int(y + tb[1]) - 6,
                             int(tb[2] - tb[0]) + 12, int(tb[3] - tb[1]) + 12]})
    return out


def apply_layout(board_path: Path, scene_id: str, out_path: Path,
                 episode_dir: Path | None = None,
                 out_raw: Path | None = None,
                 out_preview: Path | None = None) -> Path:
    """版式层三路输出（2026-09-04 拆分，修"成片带编号框"问题）：

    - out_raw     内容原图（重定尺寸，无任何叠加）——渲染的墨迹来源；
    - out_path    渲染 overlay：raw + 标签文字（layout.texts，如 9/10）。
                  分区框/编号圈是二审预览件，不进成片；
    - out_preview 二审预览图：raw + 虚线外框 + 分区框 + 编号圈 + 标签，
                  供人工核对绘制顺序（confirm-boards 用）。
    """
    img = cv2.imread(str(board_path))
    assert img is not None, f"{board_path} 不存在"
    if img.shape[:2] != (H, W):
        img = cv2.resize(img, (W, H))
    if out_raw is not None:
        out_raw.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_raw), img)

    layout = load_scene_layout(scene_id, episode_dir)

    # 渲染 overlay：只叠标签；旁车输出标签清单供内核按 panel 延迟揭示
    canvas = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    label_spec = _draw_texts(ImageDraw.Draw(canvas), layout)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), cv2.cvtColor(np.array(canvas), cv2.COLOR_RGB2BGR))
    (out_path.parent / f"{out_path.stem}.labels.json").write_text(
        json.dumps(label_spec, ensure_ascii=False, indent=1), encoding="utf-8")

    # 二审预览：全量标注
    if out_preview is not None:
        prev = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        d = ImageDraw.Draw(prev)
        draw_dashed_rect(d, INSET, INSET, W - INSET, H - INSET)
        font = ImageFont.truetype(str(FONT_DIGIT), int(BADGE_R * 1.15))
        for idx, (_, x, y, w, h, color_name) in enumerate(layout["panels"], start=1):
            color = PANEL_COLORS.get(color_name, PANEL_COLORS["blue"])[::-1]
            d.rounded_rectangle([x, y, x + w, y + h], radius=RADIUS, outline=color, width=BORDER_W)
            bx, by = x - 12, y - 12
            d.ellipse([bx - BADGE_R, by - BADGE_R, bx + BADGE_R, by + BADGE_R],
                      outline=color, width=4)
            t = str(idx)
            tb = d.textbbox((0, 0), t, font=font)
            d.text((bx - (tb[2] - tb[0]) / 2, by - (tb[3] - tb[1]) / 2 - tb[1]),
                   t, font=font, fill=INK)
        _draw_texts(d, layout)
        out_preview.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_preview), cv2.cvtColor(np.array(prev), cv2.COLOR_RGB2BGR))
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--board", required=True, type=Path)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--episode-dir", type=Path, default=None)
    args = ap.parse_args()
    out = apply_layout(args.board, args.scene, args.out, args.episode_dir)
    print(f"OK {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
