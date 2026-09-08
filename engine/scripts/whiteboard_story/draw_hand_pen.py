#!/usr/bin/env python3
"""程序化生成「白马克笔 + 卡通手」笔尖遮罩素材（中性设计，无文字无品牌，可随工具开源）。

产出：PNG（RGBA alpha），笔尖位于内容 bbox 左上角（渲染器 tip_anchor=(0,0) 约定）。
背景透明；白马克笔；暖肤色卡通手；无任何文字/贴纸/logo。
用法：<python> draw_hand_pen.py --out <path.png> [--scale 1.0] [--preview 预览底色hex]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

SS = 3                      # 超采样倍数（抗锯齿）
W, H = 560, 840             # 设计画布（垂直构图：笔尖朝上）
OUTLINE = (74, 60, 48, 255)     # 深棕描边
SKIN = (242, 194, 155, 255)     # 暖肤色
SKIN_SHADE = (226, 165, 120, 255)
SKIN_HI = (255, 235, 215, 220)
PEN = (250, 250, 248, 255)      # 马克笔白
PEN_SHADE = (214, 210, 201, 255)
PEN_HI = (255, 255, 255, 255)
TIP = (238, 236, 229, 255)      # 笔尖白
OW = 5 * SS                     # 描边宽


def _capsule(d: ImageDraw, p0, p1, w, fill, outline=None):
    """画胶囊（两端圆头的粗线段），outline>0 时整体描边。"""
    (x0, y0), (x1, y1) = p0, p1
    r = w / 2
    d.line([p0, p1], fill=fill, width=int(w + 2))
    d.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=fill)
    d.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=fill)
    if outline:
        # 外描边：同位置画粗线在下层即可（素材缩后视觉可接受）
        d.line([p0, p1], fill=outline, width=int(w + 2 * OW))
        d.ellipse([x0 - r - OW, y0 - r - OW, x0 + r + OW, y0 + r + OW], fill=outline)
        d.ellipse([x1 - r - OW, y1 - r - OW, x1 + r + OW, y1 + r + OW], fill=outline)
        d.line([p0, p1], fill=fill, width=int(w))
        d.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=fill)
        d.ellipse([x1 - r, y1 - r, x1 + r, y1 + r], fill=fill)


def pen_hand_layer() -> Image.Image:
    """垂直构图：白马克笔（笔尖朝上）+ 卡通手握住中下段，透明底。"""
    im = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    s = SS
    cx = W / 2 * s

    def p(x, y):                       # 设计坐标 → 像素
        return (x * s, y * s)

    cx_d = W / 2                     # 设计坐标圆心（p() 收设计坐标）
    # ══ 1. 手底层：腕根 + 手掌（在笔杆后面，右侧）═════════════
    _capsule(d, p(cx_d + 96, 620), p(cx_d + 60, 470), 86 * s, SKIN, OUTLINE)      # 腕根（右下）
    _capsule(d, p(cx_d + 14, 268), p(cx_d + 66, 428), 96 * s, SKIN, OUTLINE)      # 掌（贴杆右侧）

    # ══ 2. 白马克笔（无文字）═══════════════════════════════════════
    half_t, half_m, half_b = 17, 26, 24
    top_y, bot_y, cap_y, cap_bot = 96, 520, 520, 648

    # 笔身（两段锥度 + 上下圆头）
    d.polygon([(cx - half_t * s, top_y * s), (cx + half_t * s, top_y * s),
               (cx + half_m * s, (top_y + bot_y) / 2 * s), (cx - half_m * s, (top_y + bot_y) / 2 * s)],
              fill=PEN)
    d.polygon([(cx - half_m * s, (top_y + bot_y) / 2 * s), (cx + half_m * s, (top_y + bot_y) / 2 * s),
               (cx + half_b * s, bot_y * s), (cx - half_b * s, bot_y * s)], fill=PEN)
    # 笔尖（钝头楔形）
    d.polygon([(cx - 5 * s, 28 * s), (cx + 5 * s, 28 * s),
               (cx + 13 * s, 92 * s), (cx - 13 * s, 92 * s)], fill=TIP)
    # 笔帽（一体圆角 + 卡口线）
    d.rounded_rectangle([(cx - 27 * s), cap_y * s, (cx + 27 * s), cap_bot * s],
                        radius=24 * s, fill=PEN)

    # 光影
    d.line([p(cx - half_t + 8, top_y + 6), p(cx - half_b + 8, bot_y - 4)], fill=PEN_SHADE, width=4 * s)
    d.line([p(cx + half_t - 9, top_y + 6), p(cx + half_b - 9, bot_y - 4)], fill=PEN_HI, width=5 * s)
    d.line([p(cx - 18, cap_y + 8), p(cx - 18, cap_bot - 18)], fill=PEN_SHADE, width=4 * s)
    # 卡口线
    d.line([p(cx - 27, cap_y + 26), p(cx + 27, cap_y + 26)], fill=PEN_SHADE, width=4 * s)
    # 描边（笔身轮廓 + 尖分界 + 帽轮廓）
    d.line([p(cx - half_t, top_y), p(cx - half_m, (top_y + bot_y) / 2), p(cx - half_b, bot_y)],
           fill=OUTLINE, width=OW)
    d.line([p(cx + half_t, top_y), p(cx + half_m, (top_y + bot_y) / 2), p(cx + half_b, bot_y)],
           fill=OUTLINE, width=OW)
    d.arc([p(cx - half_t - 2, 78), p(cx + half_t + 2, 122)], 180, 360, fill=OUTLINE, width=OW)
    d.arc([p(cx - half_b - 2, bot_y - 42), p(cx + half_b + 2, bot_y + 6)], 0, 180, fill=OUTLINE, width=OW)
    d.line([p(cx - 5, 28), p(cx - 13, 92)], fill=OUTLINE, width=4 * s)
    d.line([p(cx + 5, 28), p(cx + 13, 92)], fill=OUTLINE, width=4 * s)
    d.line([p(cx - 5, 28), p(cx + 5, 28)], fill=OUTLINE, width=4 * s)
    d.line([p(cx - 14, 92), p(cx + 14, 92)], fill=OUTLINE, width=4 * s)
    d.arc([p(cx - 29, cap_y - 4), p(cx + 29, cap_y + 60)], 180, 360, fill=OUTLINE, width=OW)
    d.arc([p(cx - 29, cap_bot - 56), p(cx + 29, cap_bot + 8)], 0, 180, fill=OUTLINE, width=OW)

    # ══ 3. 指尖（在笔杆左侧前方，从掌绕过杆）════════════════════════
    for (y0, ln, wdt) in [(388, 74, 36), (424, 70, 34), (458, 64, 31)]:
        _capsule(d, p(cx_d + 8, y0 + 16), p(cx_d - 58, y0 + 28), wdt * s, SKIN, OUTLINE)
    # 指尖关节阴影
    for (y0, wdt) in [(388, 36), (424, 34), (458, 31)]:
        d.arc([p(cx_d - 62, y0 - 6), p(cx_d + 4, y0 + 56)], 240, 20, fill=OUTLINE, width=int(3 * s))

    # ══ 4. 拇指（横跨笔杆前方）═══════════════════════════════════════
    _capsule(d, p(cx_d + 72, 300), p(cx_d - 40, 366), 56 * s, SKIN, OUTLINE)
    # 拇指阴影（贴着笔杆左缘）
    d.line([p(cx_d - 38, 362), p(cx_d + 62, 306)], fill=SKIN_SHADE, width=7 * s)
    # 高光
    for (hx, hy, r) in [(cx_d + 30, 322, 8), (cx_d - 16, 342, 9)]:
        d.ellipse([p(hx - r, hy - r), p(hx + r, hy + r)], fill=SKIN_HI)

    # ── 降采样（抗锯齿）──
    im = im.resize((W, H), Image.LANCZOS)
    return im


def rotate_to_writing(im: Image.Image) -> Image.Image:
    """整体旋转 45°（逆时针），让笔尖指向左上、笔身向右下延伸（书写姿态）。"""
    return im.rotate(45, expand=True, resample=Image.BICUBIC)


def crop_anchor(im: Image.Image) -> Image.Image:
    """裁剪到内容 bbox：笔尖（最左上 alpha 像素）成为素材左上角 (0,0)。"""
    bbox = im.getbbox()
    assert bbox, "空图"
    return im.crop(bbox)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--scale", type=float, default=1.0, help="输出放大倍数")
    ap.add_argument("--preview", default="#203A30", help="预览底板色（hex），输出 <out>.preview.png")
    args = ap.parse_args()

    layer = pen_hand_layer()
    layer = rotate_to_writing(layer)
    layer = crop_anchor(layer)
    if args.scale != 1.0:
        layer = layer.resize((max(1, int(layer.width * args.scale)),
                              max(1, int(layer.height * args.scale))), Image.LANCZOS)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    layer.save(args.out)
    print(f"OK {args.out}  {layer.width}x{layer.height}")

    if args.preview:
        bg = Image.new("RGBA", layer.size, args.preview + "ff")
        bg.alpha_composite(layer)
        prev = args.out.with_suffix(".preview.png")
        bg.convert("RGB").save(prev)
        print(f"OK {prev}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
