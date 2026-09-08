#!/usr/bin/env python3
"""magenta 底 AI 生图 → 透明 RGBA 手素材 + 笔尖锚点自动校准 + 板底色合成预览。

主题手素材生产链（theme-onboarding.md §6）：宿主文生图（纯 magenta 底、
按主题配色、笔尖朝左下、袖口出右下）→ 本脚本抠图/清水印/裁边/定锚 →
拷入 themes/<id>/hands/（.png 与 .tip.json 成对）。
默认值取 chalkboard-chibi（板底 #123D35、渲染宽 288px=1920×15%），其他主题用参数覆盖。

用法：
  cd engine && uv run python scripts/whiteboard_story/make_hand_asset.py \
      <in.png> <out-prefix> [--margin 12] [--board-hex 123D35] [--render-w 288]

产出（在 out-prefix 同目录）：
  <prefix>.png             透明底 RGBA 手素材（已裁边）
  <prefix>.tip.json        {"tip":[x,y]} 裁边后素材自身坐标
  <prefix>.preview.png     板底色合成 + 渲染尺寸 + 笔尖十字标记
  <prefix>.preview-full.png 板底色合成（全尺寸）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

BOARD = (0x12, 0x3D, 0x35)   # 主题板底（默认 chalkboard-chibi）
RENDER_W = 288               # 内核渲染宽 = 画面宽 15%


def sample_bg(rgb: np.ndarray) -> np.ndarray:
    """magenta 背景色：四角逐通道中位数（右下角可能被袖口污染，中位数抗单点离群）。"""
    corners = np.stack([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]]).astype(float)
    return np.median(corners, axis=0)


def sample_sleeve(rgb: np.ndarray, bg: np.ndarray) -> np.ndarray:
    """袖口参考色：右下角区域内、离 magenta 足够远像素的中位色。"""
    h, w = rgb.shape[:2]
    reg = rgb[int(h * 0.72):, int(w * 0.68):].reshape(-1, 3).astype(float)
    far = np.linalg.norm(reg - bg, axis=1) > 120
    if far.sum() < 500:
        raise SystemExit("右下角找不到袖口色，检查构图")
    return np.median(reg[far], axis=0)


def denoise_watermark(rgb: np.ndarray, bg: np.ndarray, sleeve: np.ndarray) -> np.ndarray:
    """清「AI生成」水印：水印 = 半透明白色叠在局部底色上。
    右下角区域内逐像素做「底色→白」连线检测（b∈{magenta, 参考色}，
    残差 < 14 且 0.10 < t < 0.96 判为水印）→ mask 膨胀 → cv2 修复。
    不直接吸附还原：写实素材的皮肤高光也近似落在肤色→白 连线上，
    吸附会抹平高光，修复只平滑水印笔画、保留纹理。"""
    import cv2
    out = rgb.copy()
    h, w = rgb.shape[:2]
    y0, x0 = int(h * 0.78), int(w * 0.68)
    reg = out[y0:, x0:]
    flat = reg.reshape(-1, 3).astype(float)
    wm = np.zeros(len(flat), dtype=bool)
    for b in (bg.astype(float), sleeve.astype(float)):
        v = 255.0 - b
        t = ((flat - b) @ v) / (v @ v)
        tc = t.clip(0.0, 1.0)
        proj = b + tc[:, None] * v
        res = np.linalg.norm(flat - proj, axis=1)
        wm |= (res < 14) & (t > 0.10) & (t < 0.96)
    mask = wm.reshape(reg.shape[:2]).astype(np.uint8) * 255
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
    print(f"水印像素 {int((mask > 0).sum())}（区域 {y0},{x0} 起）")
    if int((mask > 0).sum()) < 1500:
        print("警告：水印像素过少，可能未清干净，请目检", file=sys.stderr)
    bgr = cv2.cvtColor(reg, cv2.COLOR_RGB2BGR)
    repaired = cv2.inpaint(bgr, mask, 3, cv2.INPAINT_TELEA)
    out[y0:, x0:] = cv2.cvtColor(repaired, cv2.COLOR_BGR2RGB)
    return out


def key_magenta(rgb: np.ndarray, bg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """自适应 magenta 抠图：距离阈值出 alpha，并做溢色抑制。"""
    corners = np.stack([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]]).astype(float)
    dists = sorted(np.linalg.norm(corners - bg, axis=1))
    spread = float(dists[2])            # 最大离群角（袖口）不计入
    print(f"背景色≈{bg.round(0)} 有效角点离散={spread:.1f}")

    d = np.linalg.norm(rgb.astype(float) - bg, axis=2)
    lo = max(30.0, spread * 0.6)          # 完全透明阈值
    hi = min(200.0, lo + 110.0)           # 完全不透明阈值
    alpha = np.clip((d - lo) / (hi - lo), 0, 1) * 255.0
    # 压掉背景微噪声半透明雾（<60 一律全透明）
    alpha = np.clip((alpha - 60) * (255.0 / (255.0 - 60.0)), 0, 255)

    # 溢色抑制：边缘像素被 magenta 污染（R、G 同时远高于 B 之外的分量）→ 拉回
    out = rgb.astype(float)
    magenta_cast = np.minimum(out[:, :, 0], out[:, :, 2]) - out[:, :, 1]
    spill = magenta_cast > 24
    out[spill, 0] = out[spill, 0] * 0.55 + out[spill, 1] * 0.45
    out[spill, 2] = out[spill, 2] * 0.55 + out[spill, 1] * 0.45
    return out.clip(0, 255).astype(np.uint8), alpha.astype(np.uint8)


def find_chalk_tip(rgb: np.ndarray, alpha: np.ndarray) -> tuple[int, int]:
    """笔尖 = 暖白粉笔像素集中 (y - x) 最大者（左下方向极值）。"""
    f = rgb.astype(int)
    bright = (f.min(axis=2) > 175) & (np.abs(f[:, :, 0] - f[:, :, 2]) < 55)
    mask = bright & (alpha > 200)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        raise SystemExit("找不到粉笔亮色像素，检查配色/抠图阈值")
    score = ys - xs
    i = int(np.argmax(score))
    # 取极值附近邻域中心，避免锯齿单像素
    near = (np.abs(ys - ys[i]) < 8) & (np.abs(xs - xs[i]) < 8) & (score >= score.max() - 16)
    return int(xs[near].mean().round()), int(ys[near].mean().round())


def main() -> int:
    global BOARD, RENDER_W
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("prefix", type=Path)
    ap.add_argument("--margin", type=int, default=12)
    ap.add_argument("--board-hex", default="123D35", help="预览板底色（默认 chalkboard-chibi）")
    ap.add_argument("--render-w", type=int, default=288, help="内核渲染宽（画面宽×15%%）")
    args = ap.parse_args()
    BOARD = tuple(int(args.board_hex[i:i + 2], 16) for i in (0, 2, 4))
    RENDER_W = args.render_w

    im = Image.open(args.src).convert("RGB")
    rgb = np.asarray(im)
    bg = sample_bg(rgb)
    sleeve = sample_sleeve(rgb, bg)
    print(f"袖口参考色≈{sleeve.round(0)}")
    rgb = denoise_watermark(rgb, bg, sleeve)
    out_rgb, alpha = key_magenta(rgb, bg)
    tip = find_chalk_tip(out_rgb, alpha)
    print(f"全图笔尖候选 {tip}")

    img = Image.fromarray(np.dstack([out_rgb, alpha]), "RGBA")

    # 裁边（含 margin），以实心像素为准，tip 平移
    ys, xs = np.nonzero(alpha > 100)
    box = (max(0, xs.min() - args.margin), max(0, ys.min() - args.margin),
           min(img.width, xs.max() + 1 + args.margin), min(img.height, ys.max() + 1 + args.margin))
    img = img.crop(box)
    tip = (int(tip[0] - box[0]), int(tip[1] - box[1]))
    print(f"裁边 {box} → {img.size}，笔尖 {tip}")

    args.prefix.parent.mkdir(parents=True, exist_ok=True)
    png = args.prefix.with_suffix(".png")
    img.save(png)
    args.prefix.with_name(png.stem + ".tip.json").write_text(
        json.dumps({"tip": list(tip)}), encoding="utf-8")

    # 预览：板底色合成（全尺寸 + 288px 渲染尺寸），均带笔尖十字
    def board_view(target: Image.Image, scale: float) -> Image.Image:
        big = Image.new("RGBA", target.size, (*BOARD, 255))
        big.alpha_composite(target)
        rgb_im = big.convert("RGB")
        d = ImageDraw.Draw(rgb_im)
        cx, cy = tip[0] * scale, tip[1] * scale
        d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], outline=(255, 80, 80), width=2)
        d.line([(cx - 14, cy), (cx + 14, cy)], fill=(255, 80, 80), width=2)
        d.line([(cx, cy - 14), (cx, cy + 14)], fill=(255, 80, 80), width=2)
        return rgb_im

    full_prev = board_view(img, 1.0)
    full_prev_path = args.prefix.with_name(png.stem + ".preview-full.png")
    full_prev.save(full_prev_path)

    scale = RENDER_W / img.width
    small = img.resize((RENDER_W, max(1, int(img.height * scale))), Image.LANCZOS)
    thumb = board_view(small, scale)
    canvas = Image.new("RGB", (RENDER_W + 80, thumb.height + 80), (30, 30, 30))
    canvas.paste(thumb, (40, 40))
    prev = args.prefix.with_name(png.stem + ".preview.png")
    canvas.save(prev)
    print(f"OK {png}\nOK {png.stem}.tip.json\nOK {prev}\nOK {full_prev_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
