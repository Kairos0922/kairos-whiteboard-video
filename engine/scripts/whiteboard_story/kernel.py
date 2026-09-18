#!/usr/bin/env python3
"""分区同步白板渲染内核 v1（自有实现，2026-08-26）。

设计决策与重跑矩阵见 references/kernel-design.md。核心思路：
- 数学底座复用上游 MIT 引擎 whiteboard-video-engine（pyproject 按 commit 锁定）：
  zhang_suen_skeleton / trace_8connected（骨架化、八邻接追踪、分叉直行优先）；
- 时间调度层自研：按 annotation.json 的元素窗口逐区揭示，保证「视觉顺序=讲解顺序」，
  这是上游整幕渲染不具备的能力；
- 上色策略：描线沿骨架按弧长推进并直接拷贝板图原始像素（保留彩铅纹理）；
  填色用蛇形扫描线；描线/填色时长按路径长度比例分配；
- 抬笔状态：笔画间与跨区间手部快速滑动帧，只更新手位置不新增墨迹；
- 收尾完整化：全部绘制任务结束后整图呈现一小段（骨架+扫描线可能漏掉的零星像素
  在此兜底），对应教程「最后一幕保留完整结论」。

坐标系约定：点为 (x, y)；掩码索引为 [y, x]。底色自适应：亮纸/深板均可用。
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

from whiteboard_skill.preprocess import trace_8connected, zhang_suen_skeleton
from whiteboard_skill.whiteboard import _open_ffmpeg_rawvideo_writer

HAND_TIP_RATIO = (0.075, 0.885)  # 手素材笔尖锚点占素材宽高比例；换手素材必须重新校准
INK_THRESHOLD = 60               # 与背景色的亮度距离阈值（单通道口径 0-255）
FILL_ROW_STEP = 6                # 蛇形填色行距 px（收紧：配 6px 刷宽基本连成实面）
CHAIN_MAX_PX = 48                # 笔画端点距 ≤ 此值直接连画不抬笔：纹理骨架碎段
                                # 拼回连续笔迹（修"一卡一卡"：碎段间 90ms 抬笔预算
                                # 让落墨成簇爆点，连画后笔迹成流）
FRAGMENT_MERGE_PX = 28           # 端点距 ≤ 此值且切向对齐的碎段贪心并进同一条折线：
                                # 同一粉笔行被骨架化碎成多段时，弧长降序下它们不相邻，
                                # 每段各占 draw+travel 任务 → 手可见地扫荡而墨不长
REDUNDANT_COVER_PX = 9           # 覆盖剔除掩膜半径 = BRUSH_RADIUS + 粉笔线半宽：
                                # 贴主线的平行偏移残段/重描冗余落进去判剔除
REDUNDANT_COV_RATIO = 0.9        # 笔画 ≥90% 点被已保留笔画掩膜覆盖 → 冗余剔除
TRAVEL_SPEED_PX_MS = 2.8         # 抬笔移动速度
SUB_WINDOW_GAP_MS = 120          # 揭示单元内对象子窗间隔（方案 A：把对象组分开）
REGION_GAP_MS = 150               # 区域间抬笔移动间隙（区域严格串行：前一区域结束后隔这么久再开始下一区域）
CLUSTER_DILATE = 18              # 对象聚类膨胀半径 px（连通域判定用；18px 确保人物的脸/头发/身体
                                # 等间距 <18px 的部分视为同一对象，避免人物被拆成多组导致骷髅头）
DETAIL_MAX_LEN = 70              # 弧长 < 此值且 bbox < DETAIL_MAX_BOX 的描线判为细节
DETAIL_MAX_BOX = 50              # （五官/腮红/小装饰）：排到本组填色之后上墨，
                                # 杜绝"脸还是板底深色、眼眶先出"的骷髅中间态
LABEL_FADE_MS = 300              # 标签随所属岛画完淡入的时长（废 chrome 常驻：
                                # 标签未画先挂是"黑板上一直有三个字"的根因）
BRUSH_RADIUS = 3                 # 描画笔刷半径 px：沿骨架/填色路径复制原图像素时
                                # 带刷宽落墨（修"鬼影后换图"：1px 骨架线是草稿感，
                                # 刷宽 6px 与板图线宽一致，画的过程就是原图的样子）
HAND_FOLLOW_RANGE = (0.08, 1.0)  # 手部显示位置单侧 lerp 系数范围（1.0=硬贴笔尖，
                                # 越小手越"跟手缓动"，吸收骨架点列噪声抖动；
                                # 参照 nikola hand-follow，只影响显示不影响落墨时序）
FADE_IN_MS = 700                 # 幕首自上一幕板面淡入背景的时长（擦黑板式切幕；
                                # 380ms 太短读起来像硬切）
HAND_FADE_MS = 240               # 手出入画淡入淡出时长（硬切会弹跳感）
HAND_LEAD_MS = 350               # 落笔前这么久手才淡入：空档/位移段手一律离画，
                                # 杜绝"手拿着粉笔来回动却不落墨"的空转观感


# ---------------------------------------------------------------- 前景提取

def estimate_bg(img: np.ndarray) -> tuple[int, int, int]:
    """四边中位色估背景：paper 自动取米白，chalkboard 自动取墨绿。"""
    bands = np.concatenate([
        img[:8].reshape(-1, 3), img[-8:].reshape(-1, 3),
        img[:, :8].reshape(-1, 3), img[:, -8:].reshape(-1, 3),
    ])
    return tuple(int(v) for v in np.median(bands, axis=0))


def extract_ink_mask(img: np.ndarray, threshold: int = INK_THRESHOLD) -> np.ndarray:
    """色距判墨：|px-bg| 三通道总距离 > 阈值×3。对任意底色方向成立。"""
    dist = np.abs(img.astype(np.int16) - np.array(estimate_bg(img))).sum(axis=2)
    return dist > threshold * 3


def _trace_merged(skel: np.ndarray, size: tuple[int, int],
                  min_points: int = 6) -> list[np.ndarray]:
    """骨架 → 笔画点列，并按端点切向兼容性近邻合并（减少碎笔画）。"""
    from whiteboard_skill.preprocess import Stroke, merge_nearby_strokes

    raw = trace_8connected(skel, min_points=min_points)
    if not raw:
        return []
    wrapped = [Stroke(points=[(int(x), int(y)) for x, y in pts])
               for pts in raw]
    merged = merge_nearby_strokes(wrapped, canvas_size=size)
    return [np.asarray(s.points, dtype=np.int32) for s in merged]


def board_to_strokes(board_png: Path, min_points: int = 6) -> list[np.ndarray]:
    """板图 → 墨迹掩码 → 一像素骨架 → 合并后笔画点列（每项 Nx2 int32）。"""
    _img, _ink, skel = load_board_layers(board_png)
    strokes = _trace_merged(skel, skel.shape[::-1], min_points=min_points)
    if not strokes:
        raise RuntimeError(f"骨架追踪零笔画：{board_png}")
    return strokes


def load_board_layers(board_png: Path, min_points: int = 6):
    """一次性产出（RGB 数组, 墨迹掩码, 骨架）；供渲染主流程复用避免重复 IO。"""
    img = np.asarray(Image.open(board_png).convert("RGB"))
    ink = extract_ink_mask(img)
    if not ink.any():
        raise RuntimeError(f"板图无可提取墨迹（阈值 {INK_THRESHOLD}）：{board_png}")
    return img, ink, zhang_suen_skeleton(ink)


# ---------------------------------------------------------------- 区域模型

@dataclass
class Element:
    eid: str
    seq: int
    rect: tuple[int, int, int, int]      # x, y, w, h
    start_ms: int
    duration_ms: int
    ops_count: int = 1                   # 揭示单元内的离散操作数（方案 A，≤3；>1 时区内分子窗）
    protected: tuple = ()                # 已揭示分区矩形：本单元绘制时不得复墨
    ops: tuple = ()                      # annotation 中的 ops 列表（含 MOVE 等转场操作）

    def contains(self, x: float, y: float) -> bool:
        rx, ry, rw, rh = self.rect
        return rx <= x < rx + rw and ry <= y < ry + rh

    def area(self) -> int:
        return self.rect[2] * self.rect[3]


@dataclass(frozen=True)
class Annotation:
    elements: list[Element]
    scene_duration_ms: int


def parse_annotation(annotation_json: Path) -> Annotation:
    ann = json.loads(annotation_json.read_text(encoding="utf-8"))
    els = sorted(ann["elements"], key=lambda e: e.get("sequence", 0))
    out = []
    for el in els:
        r, rv = el["region"], el["reveal"]
        protected = tuple((int(p["x"]), int(p["y"]), int(p["width"]), int(p["height"]))
                          for p in rv.get("protectedRegions") or []
                          if isinstance(p, dict))
        ops = tuple(el.get("ops") or [])
        out.append(Element(el["id"], el.get("sequence", 0),
                           (int(r["x"]), int(r["y"]), int(r["width"]), int(r["height"])),
                           int(rv["startMs"]), int(rv["durationMs"]),
                           ops_count=max(1, len(ops)),
                           protected=protected,
                           ops=ops))
    return Annotation(out, int(ann.get("sceneDurationMs", 0)))


def assign_element(pt: tuple[float, float], elements: list[Element]) -> Element | None:
    """归属最小面积包含矩形；无包含则丢弃该笔画（防串区，v1 策略）。"""
    hits = [e for e in elements if e.contains(*pt)]
    return min(hits, key=Element.area) if hits else None


def _clip_strokes(strokes: list[np.ndarray],
                  protected: tuple) -> list[np.ndarray]:
    """保护区过滤：删去落在已揭示分区内的点，被删处在断裂处重新分段（留 ≥2 点的段）。

    protectedRegions 真正生效的落点（ir-alignment §5 定论 A）：后揭示单元的
    笔画即便越过先揭示分区边界，也不会在已上墨的区域复画。
    """
    if not protected:
        return strokes
    out: list[np.ndarray] = []
    for s in strokes:
        keep = np.ones(len(s), dtype=bool)
        for (px, py, pw, ph) in protected:
            keep &= ~((s[:, 0] >= px) & (s[:, 0] < px + pw)
                      & (s[:, 1] >= py) & (s[:, 1] < py + ph))
        bounds = np.where(np.diff(keep) != 0)[0] + 1
        state = bool(keep[0]) if len(s) else False
        prev = 0
        for b in list(bounds) + [len(s)]:
            if state and b - prev >= 2:
                out.append(s[prev:b])
            state = not state
            prev = b
    return out


# ---------------------------------------------------------------- 蛇形填色

def dilate_mask(mask: np.ndarray, radius: int = 3) -> np.ndarray:
    import cv2
    kern = np.ones((radius * 2 + 1, radius * 2 + 1), dtype=np.uint8)
    return cv2.dilate(mask.astype(np.uint8), kern).astype(bool)


def build_fill_strokes(board: np.ndarray, element: Element,
                       exclude_mask: np.ndarray | None = None,
                       protected: tuple = ()) -> list[np.ndarray]:
    """元素矩形内按行蛇形生成填色路径点列。

    填色候选 = 与背景色距超标 且 不属于描线骨架膨胀区 —— 区分「色块」与「线条」，
    否则暗线会被当成待填色块产生海量假路径冲爆时间窗（2026-08-26 冒烟教训）。
    protected 矩形（先揭示分区）内的像素一律不填色。
    """
    x, y, w, h = element.rect
    img = board[y:y + h, x:x + w]
    bg = np.array(estimate_bg(board))
    colored = np.abs(img.astype(np.int16) - bg).sum(axis=2) > INK_THRESHOLD * 3
    if exclude_mask is not None:
        colored &= ~exclude_mask[y:y + h, x:x + w]
    for (px, py, pw, ph) in protected:
        lx0, ly0 = max(0, px - x), max(0, py - y)
        lx1, ly1 = min(w, px + pw - x), min(h, py + ph - y)
        if lx1 > lx0 and ly1 > ly0:
            colored[ly0:ly1, lx0:lx1] = False
    paths: list[np.ndarray] = []
    for i, row in enumerate(range(FILL_ROW_STEP // 2, h, FILL_ROW_STEP)):
        flip = i % 2 == 1
        cols = range(w - 1, -1, -1) if flip else range(w)
        run: list[tuple[int, int]] = []
        for col in cols:
            if colored[row, col]:
                run.append((x + col, y + row))
            elif len(run) >= 3:
                paths.append(np.asarray(run[::-1] if not flip else run, dtype=np.int32))
                run = []
        if len(run) >= 3:
            paths.append(np.asarray(run[::-1] if not flip else run, dtype=np.int32))
    return paths


# ---------------------------------------------------------------- 时序编排

@dataclass
class Task:
    kind: str                       # draw | travel | gaze | move
    start_ms: int
    end_ms: int
    pts: np.ndarray | None = None   # draw 专用点列
    cum: np.ndarray | None = None   # draw 弧长累进表
    length: float = 0.0
    painted: int = 0                # 已上到画布的点数游标
    target: tuple[float, float] | None = None   # travel 终点
    eid: str = ""                   # 所属元素 id（编排真值，测试与校验用）
    # move 专用字段（转场操作：物体从 from 移动到 to，其他元素静止）
    move_object: np.ndarray | None = None   # 物体像素（RGBA，含 alpha mask）
    move_bg: np.ndarray | None = None       # 移动路径区域的背景（RGB，物体已被抠除）
    move_from: tuple[int, int] = (0, 0)    # 起点（物体左上角）
    move_to: tuple[int, int] = (0, 0)      # 终点（物体左上角）
    move_rect: tuple[int, int, int, int] = (0, 0, 0, 0)  # 物体矩形 (x,y,w,h)


def _arc_cum(pts: np.ndarray) -> tuple[np.ndarray, float]:
    d = np.diff(pts.astype(np.float64), axis=0)
    seg = np.hypot(d[:, 0], d[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    return cum, float(cum[-1])


def _end_outward(pts: np.ndarray, side: int) -> tuple[float, float]:
    """折线端点外切向（side 0=首 1=尾）；不足两点退水平向。"""
    if len(pts) < 2:
        return (1.0, 0.0)
    a, b = (pts[0], pts[1]) if side == 0 else (pts[-2], pts[-1])
    dx, dy = float(b[0] - a[0]), float(b[1] - a[1])
    n = math.hypot(dx, dy) or 1.0
    dx, dy = dx / n, dy / n
    return (dx, dy) if side == 1 else (-dx, -dy)


def _drop_covered(strokes: list[np.ndarray],
                  radius: int = REDUNDANT_COVER_PX,
                  ratio: float = REDUNDANT_COV_RATIO) -> list[np.ndarray]:
    """剔除被已保留笔画刷宽掩膜覆盖 ≥ratio 的冗余笔画（须按弧长降序输入）。

    骨架化会给同一条粉笔线产出贴主线平行偏移的卫星残段；它们独立成任务后
    只做重描（视觉零新墨），却各带一段 travel 扫荡。主线先入掩膜，残段后测
    覆盖即被剔除；真正补缺口/独立内容的笔画落在掩膜外，原样保留。
    """
    import cv2
    if not strokes:
        return strokes
    x0 = int(min(p[:, 0].min() for p in strokes)) - radius - 1
    y0 = int(min(p[:, 1].min() for p in strokes)) - radius - 1
    w = int(max(p[:, 0].max() for p in strokes)) + radius + 2 - x0
    h = int(max(p[:, 1].max() for p in strokes)) + radius + 2 - y0
    mask = np.zeros((h, w), np.uint8)
    kept: list[np.ndarray] = []
    for p in strokes:
        xs = (p[:, 0] - x0).astype(np.int32)
        ys = (p[:, 1] - y0).astype(np.int32)
        if len(xs) and float(mask[ys, xs].mean()) >= ratio:
            continue
        kept.append(p)
        for i in range(len(p) - 1):
            cv2.line(mask, (int(xs[i]), int(ys[i])), (int(xs[i + 1]), int(ys[i + 1])),
                     1, thickness=2 * radius + 1)
    return kept


def _merge_fragments(strokes: list[np.ndarray],
                     max_gap_px: float = FRAGMENT_MERGE_PX) -> list[np.ndarray]:
    """端点邻近且切向对齐的碎段贪心接成连续折线（弧长降序种子）。

    同一粉笔行碎成多段时，合并后＝单个 draw 任务：笔以恒速走过段间缺口
    （十余毫秒无墨，不可感知），travel 扫荡任务随之消失。切向对齐（两端外
    切向与缺口方向夹角 ≤60°）防止把垂直相交的邻近笔画误接。
    """
    merged: list[np.ndarray] = []
    for p in sorted(strokes, key=lambda s: _arc_cum(s)[1], reverse=True):
        best = None
        for mi, m in enumerate(merged):
            for si in (0, 1):
                sp = p[si]
                for mj in (0, 1):
                    mp = m[mj]
                    gx, gy = float(mp[0] - sp[0]), float(mp[1] - sp[1])
                    d = math.hypot(gx, gy)
                    if d > max_gap_px:
                        continue
                    if d < 1e-6:
                        align = 1.0
                    else:
                        ux, uy = gx / d, gy / d
                        ox, oy = _end_outward(p, si)
                        mx, my = _end_outward(m, mj)
                        align = min(ox * ux + oy * uy, mx * -ux + my * -uy)
                    if align >= 0.5 and (best is None or d < best[0]):
                        best = (d, mi, si, mj)
        if best is None:
            merged.append(p)
            continue
        _d, mi, si, mj = best
        pa = p if si == 1 else p[::-1]      # pa 尾端＝接点
        mb = merged[mi] if mj == 0 else merged[mi][::-1]   # mb 首端＝接点
        merged[mi] = np.concatenate([pa, mb])
    return merged


def ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, t)))


def hand_follow_step(display: tuple[float, float], target: tuple[float, float],
                     follow: float) -> tuple[float, float]:
    """手部显示位置单侧 lerp：display += (target - display) × follow。

    follow 钳制到 HAND_FOLLOW_RANGE：1.0 = 每帧硬贴笔尖（默认，观感与旧版一致）；
    <1.0 做指数平滑，吸收骨架点列的逐像素噪声抖动（参照 nikola hand-follow）。
    只平滑显示位置——落墨、时序、cursor 真值均不受影响。
    """
    f = min(HAND_FOLLOW_RANGE[1], max(HAND_FOLLOW_RANGE[0], follow))
    return (display[0] + (target[0] - display[0]) * f,
            display[1] + (target[1] - display[1]) * f)


def _paint_points(canvas: np.ndarray, src: np.ndarray,
                  ys: np.ndarray, xs: np.ndarray,
                  r: int = BRUSH_RADIUS) -> None:
    """以 (ys, xs) 为中心、半径 r 的圆盘内整片复制 src 像素到 canvas。

    刷宽描画：骨架是 1px，直接描 1px 得到"草稿鬼影"；带刷宽复制原图像素，
    线条粗细、颜色与板图一致，揭示过程即原图逐步成形，收尾兜底只补零星。
    """
    if len(ys) == 0:
        return
    h, w = canvas.shape[:2]
    r2 = r * r
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy * dy + dx * dx > r2:
                continue
            yy = ys + dy
            xx = xs + dx
            m = (yy >= 0) & (yy < h) & (xx >= 0) & (xx < w)
            canvas[yy[m], xx[m]] = src[yy[m], xx[m]]


def _schedule_group(eid: str, start_ms: int, end_ms: int,
                    prep: list, tasks: list[Task]) -> None:
    """单个时间窗内的排程：弧长比例时长 + 邻接碎段零间隔连画。

    恒速连续流（2026-09-16 修"一卡一卡"）：纹理粉笔线骨架化后碎成几百段，
    旧算法给每段插 ≤90ms 抬笔预算 + 逐段缓动，落墨成簇爆点。现在端点距
    ≤ CHAIN_MAX_PX 的碎段直接连画（零间隔、线性推进），只有真正的跨区跳跃
    才产生 travel 帧；窗口装不下时整体等比加速，不逐段扭曲。
    """
    if not prep:
        return
    before = len(tasks)
    duration_ms = max(1, end_ms - start_ms)
    total_len = sum(max(1e-6, float(c[-1])) for _p, c, _ln in prep)
    n = len(prep)
    # 先按弧长比例算出各段时长与段间跳跃，求总占用后再统一收敛到窗口
    items: list[tuple[str, int, int, tuple[float, float] | None]] = []
    total = 0
    for i, (pts, cum, _ln) in enumerate(prep):
        d = max(1, int(duration_ms * float(cum[-1]) / total_len))
        items.append(("draw", i, d, None))
        total += d
        if i < n - 1:
            nxt_first = prep[i + 1][0][0]
            dist_px = math.hypot(nxt_first[0] - pts[-1][0], nxt_first[1] - pts[-1][1])
            if dist_px > CHAIN_MAX_PX:
                g = max(40, int(dist_px / TRAVEL_SPEED_PX_MS))
                items.append(("travel", i, g, (float(nxt_first[0]), float(nxt_first[1]))))
                total += g
    scale = duration_ms / total if total > duration_ms else 1.0
    t = start_ms
    for kind, i, d, target in items:
        d = max(1, int(d * scale))
        if kind == "draw":
            pts, cum, _ln = prep[i]
            tasks.append(Task("draw", t, t + d, pts, cum, float(cum[-1]), eid=eid))
        else:
            tasks.append(Task("travel", t, t + d, target=target, eid=eid))
        t += d
    # 窗口硬约束：收尾不得越界（整数截断误差压回）
    group = tasks[before:]
    last_end = max((tk.end_ms for tk in group), default=start_ms)
    if group and last_end > end_ms:
        k = (end_ms - start_ms) / max(1, last_end - start_ms)
        for tk in group:
            s = start_ms + int((tk.start_ms - start_ms) * k)
            e = start_ms + int((tk.end_ms - start_ms) * k)
            tk.start_ms, tk.end_ms = s, max(e, s + 1)


def _object_groups(prep: list, el: Element) -> list[list]:
    """把单元内笔画集合按连通域聚成对象组，阅读顺序（上→下、左→右）返回。

    方案 A 的区内子窗依据（ir-alignment §5）：一个揭示单元含 1–3 个 op 时，
    各对象组依次占一个时间子窗，运动更接近真人作画，而不是整块一次性上墨。
    """
    import cv2
    x, y, w, h = el.rect
    if w <= 2 or h <= 2 or len(prep) < 2:
        return [list(prep)]
    mask = np.zeros((h, w), dtype=np.uint8)
    for (pts, _c, _ln) in prep:
        xs = np.clip(pts[:, 0] - x, 0, w - 1)
        ys = np.clip(pts[:, 1] - y, 0, h - 1)
        mask[ys, xs] = 1
    mask = cv2.dilate(mask, np.ones((CLUSTER_DILATE, CLUSTER_DILATE), np.uint8))
    n_labels, labels = cv2.connectedComponents(mask)
    if n_labels <= 2:
        return [list(prep)]
    groups: dict[int, list] = {}
    for item in prep:
        pts = item[0]
        mid = pts[len(pts) // 2]
        lab = int(labels[max(0, min(int(mid[1]) - y, h - 1)),
                         max(0, min(int(mid[0]) - x, w - 1))])
        if lab == 0:                              # 中点落在膨胀间隙：取笔画采样里首个非零标签
            sample = pts[::max(1, len(pts) // 16)]
            labs = labels[np.clip(sample[:, 1] - y, 0, h - 1),
                          np.clip(sample[:, 0] - x, 0, w - 1)]
            nz = labs[labs > 0]
            lab = int(nz[0]) if nz.size else 1
        groups.setdefault(lab, []).append(item)
    ordered = []
    for lab, items in groups.items():
        allpts = np.concatenate([it[0] for it in items])
        ordered.append((int(allpts[:, 1].min()), int(allpts[:, 0].min()), lab))
    ordered.sort()
    return [groups[lab] for _ty, _tx, lab in ordered]


def _build_move_task(el: Element, op: dict, board: np.ndarray) -> Task:
    """从 MOVE op 构建物体移动任务（转场操作：物体从 from 移动到 to，其他元素静止）。

    op 格式：{"op": "MOVE", "target": "人物", "rect": [x,y,w,h], "from": [x1,y1], "to": [x2,y2], "object_png": "base64"}
    - rect: 物体尺寸（用于移动计算；从板图裁剪时也是裁剪区域）
    - from/to: 物体左上角的起点/终点坐标
    - object_png: 可选，base64 编码的 RGBA PNG 物体像素（转场物体独立于板图，前后场景复用同一像素）
    - 时间窗口 = element 的 reveal 窗口

    实现：物体像素优先用嵌入的 object_png，否则从 board 裁剪 + alpha mask；
    移动路径区域的背景 = board 中该区域（从板图裁剪时物体原始位置替换为背景色）；
    每帧恢复路径区域背景 + 贴物体到当前位置。
    """
    x, y, w, h = [int(v) for v in op.get("rect", [0, 0, 100, 100])]
    from_xy = tuple(int(v) for v in op.get("from", [x, y]))
    to_xy = tuple(int(v) for v in op.get("to", [x, y]))
    h_img, w_img = board.shape[:2]

    # 物体像素：优先使用嵌入的 object_png（base64 RGBA PNG），否则从板图裁剪
    embedded = op.get("object_png")
    if embedded:
        import base64
        from io import BytesIO
        from PIL import Image as PILImage
        img_data = base64.b64decode(embedded)
        obj_pil = PILImage.open(BytesIO(img_data)).convert("RGBA")
        obj_rgba = np.array(obj_pil)
        if obj_rgba.shape[1] != w or obj_rgba.shape[0] != h:
            import cv2
            obj_rgba = cv2.resize(obj_rgba, (w, h), interpolation=cv2.INTER_LANCZOS4)
        fill_origin = False  # 嵌入物体时板图中该位置可能无物体，不填充原始位置
    else:
        # 从板图裁剪物体区域像素
        x0 = max(0, min(x, w_img - 1))
        y0 = max(0, min(y, h_img - 1))
        x1 = max(x0 + 1, min(x + w, w_img))
        y1 = max(y0 + 1, min(y + h, h_img))
        obj_rgb = board[y0:y1, x0:x1].copy()

        # 生成 alpha mask：与背景色差异大的像素是物体
        bg = np.array(estimate_bg(board))
        dist = np.abs(obj_rgb.astype(np.int16) - bg).sum(axis=2)
        alpha = (dist > INK_THRESHOLD * 2).astype(np.uint8) * 255
        # 膨胀 alpha 确保物体边缘不被截断
        import cv2
        alpha = cv2.dilate(alpha, np.ones((3, 3), np.uint8))
        obj_rgba = np.dstack([obj_rgb, alpha])
        fill_origin = True

    # 生成移动路径区域的背景：board 中路径区域
    path_x0 = max(0, min(from_xy[0], to_xy[0]))
    path_y0 = max(0, min(from_xy[1], to_xy[1]))
    path_x1 = min(w_img, max(from_xy[0], to_xy[0]) + w)
    path_y1 = min(h_img, max(from_xy[1], to_xy[1]) + h)

    move_bg = board[path_y0:path_y1, path_x0:path_x1].copy()
    # 从板图裁剪物体时，把物体原始位置（在路径区域内的部分）替换为背景色
    if fill_origin:
        bg = np.array(estimate_bg(board))
        obj_in_path_x0 = max(0, x - path_x0)
        obj_in_path_y0 = max(0, y - path_y0)
        obj_in_path_x1 = min(move_bg.shape[1], x + w - path_x0)
        obj_in_path_y1 = min(move_bg.shape[0], y + h - path_y0)
        if obj_in_path_x1 > obj_in_path_x0 and obj_in_path_y1 > obj_in_path_y0:
            move_bg[obj_in_path_y0:obj_in_path_y1, obj_in_path_x0:obj_in_path_x1] = bg

    return Task(
        kind="move",
        start_ms=el.start_ms,
        end_ms=el.start_ms + el.duration_ms,
        eid=el.eid,
        move_object=obj_rgba,
        move_bg=move_bg,
        move_from=from_xy,
        move_to=to_xy,
        move_rect=(path_x0, path_y0, path_x1 - path_x0, path_y1 - path_y0),
    )


def _slot_durations(slots: list[list], duration_ms: int) -> list[int]:
    """子槽时长分配：√弧长比例 + 60ms 下限 + 撑爆等比压回。

    √ 而非线性：填色槽的蛇形路径总弧长 ∝ 色块面积，线性比例下大色块
    吃掉窗口大头、轮廓一闪而过（"big fill hogs the timeline"，
    参照 whiteboard-animator/Kinoslide 的 √面积组件级权重）。√ 压缩让
    轮廓多分时间、铺色收得快，观感接近真人「细描慢、铺色快」。只压槽间：
    槽内笔画间仍按线性弧长（_schedule_group）保持恒定笔速。
    """
    weights = [math.sqrt(max(1e-6, sum(max(1e-6, float(c[-1]))
                                       for _p, c, _ln in slot)))
               for slot in slots]
    total_w = sum(weights)
    budget = max(60 * len(slots),
                 duration_ms - SUB_WINDOW_GAP_MS * (len(slots) - 1))
    durs = [max(60, int(budget * w / total_w)) if total_w else max(60, budget // len(slots))
            for w in weights]
    over = sum(durs) - budget
    if over > 0:                       # 下限撑爆预算：等比压回，保证总长 ≤ 窗口
        scale = budget / sum(durs)
        durs = [max(45, int(d * scale)) for d in durs]
    return durs


def build_tasks(elements: list[Element], board: np.ndarray,
                strokes_global: list[np.ndarray],
                skeleton: np.ndarray | None = None,
                delta_mask: np.ndarray | None = None) -> list[Task]:
    """按元素窗口编排绝对时间任务表。

    架构 v2（2026-09-05 重构）：
    - 联合分组：对描线+填色的并集做连通域分组，确保一个物体（含轮廓和色块）
      是同一个对象组，避免人物被拆成多组导致"先画五官再填色"的骷髅头中间态。
    - 描线/填色严格两段式：每个对象组内先完整描线（所有轮廓），再统一填色
      （蛇形扫描）。描线结束时对象轮廓已完整可见，观众能认出是什么；填色是
      "给已认出的东西上色"。杜绝描线填色混合调度导致的破碎中间态。
    - 区域严格串行：后一个区域的实际开始时间 = max(annotation start, 前一个区域
      实际结束 + REGION_GAP_MS)。即使 annotation 中区域时间窗口有重叠，内核也
      自动后移，保证"一个区域完全画完再开始下一个"，杜绝视觉上同时画多个区域。
    - protectedRegions 内的点在描线与填色两侧都被剔除，不在已揭示分区复墨。
    """
    by_elem: dict[str, list[np.ndarray]] = {e.eid: [] for e in elements}
    for s in strokes_global:
        cx, cy = float(s[:, 0].mean()), float(s[:, 1].mean())
        el = assign_element((cx, cy), elements)
        if el is not None:
            by_elem[el.eid].append(s)

    excl = dilate_mask(skeleton, radius=3) if skeleton is not None else None
    tasks: list[Task] = []
    prev_end_ms = 0  # 区域严格串行：前一个区域的实际结束时间

    for el in elements:
        # MOVE 操作（转场）：物体从 from 移动到 to，其他元素静止
        move_ops = [op for op in el.ops if isinstance(op, dict) and op.get("op") == "MOVE"]
        if move_ops:
            for op in move_ops:
                tasks.append(_build_move_task(el, op, board))
            prev_end_ms = el.start_ms + el.duration_ms
            continue

        outlines = _clip_strokes(
            sorted(by_elem.get(el.eid, []), key=lambda s: _arc_cum(s)[1], reverse=True),
            el.protected)
        if delta_mask is not None:
            # 描线同样必须裁成“新增墨迹段”。否则一条跨越旧内容/新内容的骨架线
            # 会把旧笔画带回本幕，造成重描和视觉鬼影。
            outlines = _mask_strokes(outlines, delta_mask, min_points=2)
        # 碎段治理（修"手来回扫却不落墨"）：先剔除贴线平行残段（重描零新墨），
        # 再把同一粉笔行的共线碎段接成连续折线（单任务恒速走完）
        outlines = _drop_covered(outlines)
        outlines = _merge_fragments(outlines)
        outlines.sort(key=lambda s: _arc_cum(s)[1], reverse=True)
        fills = build_fill_strokes(board, el, exclude_mask=excl, protected=el.protected)
        if delta_mask is not None:
            # 连续白板：填色也必须只覆盖本幕新增区域，否则上一幕的色块会被再次扫色。
            kept_fills: list[np.ndarray] = []
            for fp in fills:
                keep = delta_mask[np.clip(fp[:, 1], 0, delta_mask.shape[0] - 1),
                                  np.clip(fp[:, 0], 0, delta_mask.shape[1] - 1)]
                if not keep.any():
                    continue
                bounds = np.where(np.diff(keep.astype(np.int8)) != 0)[0] + 1
                start = 0
                state = bool(keep[0])
                for end in list(bounds) + [len(fp)]:
                    if state and end - start >= 3:
                        kept_fills.append(fp[start:end])
                    start = end
                    state = not state
            fills = kept_fills
        # 填色误判治理：轮廓线自身围成的"细闭合带"会被填色算法当成填色区，
        # 蛇形行纯重描轮廓（视觉零新墨）却占几百个 draw+travel 任务＝扫荡根因。
        # 轮廓先入掩膜再测填色行覆盖：贴线带剔除，离线的真色块填色原样保留。
        _o_ids = {id(p) for p in outlines}
        _kept = _drop_covered(
            sorted(outlines + fills, key=lambda s: _arc_cum(s)[1], reverse=True))
        outlines = [p for p in _kept if id(p) in _o_ids]
        fills = [p for p in _kept if id(p) not in _o_ids]
        # 灰雾带治理：粉笔灰雾/线带晕的中亮灰绿被填色算法当色区，蛇形行画上去
        # 只是淡雾痕却占整秒扫荡。主题色块（peach/coral/mustard r>g，violet/navy
        # 暗或 b 主导）不落在该色类里，安全保留。
        _bgc = np.array(estimate_bg(board), dtype=np.int16)
        _filt: list[np.ndarray] = []
        for p in fills:
            med = np.median(board[p[:, 1], p[:, 0]], axis=0).astype(np.int16)
            if med[1] >= med[0] and med[1] >= med[2] and int(med.sum()) - int(_bgc.sum()) > 120:
                continue
            _filt.append(p)
        fills = _filt
        o_prep = [(p,) + _arc_cum(p) for p in outlines]
        f_prep = [(p,) + _arc_cum(p) for p in fills]
        if not o_prep and not f_prep:
            continue

        # 联合分组：描线+填色并集做连通域分组，确保一个物体是同一个对象组
        all_prep = o_prep + f_prep
        o_ids = {id(p) for p in o_prep}
        if len(all_prep) >= 2:
            groups = _object_groups(all_prep, el)
        else:
            groups = [list(all_prep)]

        # 每个对象组内拆三段子槽：主描线 → 填色 → 细节描线（五官/小装饰）。
        # 细节排最后（2026-09-16 修"骷髅头"）：两段式先全描线再填色时，
        # 脸=板底深色而眼眶鼻线先出，中间态就是骷髅；肤色填完再点五官则无此窗口。
        slots: list[list] = []
        for group in groups:
            group_outlines = [p for p in group if id(p) in o_ids]
            group_fills = [p for p in group if id(p) not in o_ids]
            main_outlines, detail_outlines = [], []
            for p in group_outlines:
                pts, cum = p[0], p[1]
                bw = int(pts[:, 0].max() - pts[:, 0].min() + 1)
                bh = int(pts[:, 1].max() - pts[:, 1].min() + 1)
                if float(cum[-1]) < DETAIL_MAX_LEN and bw < DETAIL_MAX_BOX and bh < DETAIL_MAX_BOX:
                    detail_outlines.append(p)
                else:
                    main_outlines.append(p)
            if main_outlines:
                slots.append(main_outlines)
            if group_fills:
                slots.append(group_fills)
            if detail_outlines:
                slots.append(detail_outlines)
        if not slots:
            continue

        # 区域严格串行：实际开始时间不早于前一个区域结束 + 间隙
        actual_start = max(el.start_ms, prev_end_ms + REGION_GAP_MS)

        # 时间分配：各子槽按 √弧长比例（_slot_durations，槽间防大色块霸窗）
        durs = _slot_durations(slots, el.duration_ms)

        t = actual_start
        for slot, dur in zip(slots, durs):
            _schedule_group(el.eid, t, t + dur, slot, tasks)
            t += dur + SUB_WINDOW_GAP_MS
        prev_end_ms = t - SUB_WINDOW_GAP_MS  # 本区域实际结束时间

    return sorted(tasks, key=lambda x: (x.start_ms, x.end_ms))


# ---------------------------------------------------------------- 渲染主流程

def _hand_alpha_img(hand_img: Image.Image, alpha: float) -> Image.Image:
    if alpha >= 1.0:
        return hand_img
    arr = np.asarray(hand_img).copy()
    arr[:, :, 3] = (arr[:, :, 3].astype(np.float32) * alpha).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def _hand_tip(hand_png: Path, img_size: tuple[int, int]) -> tuple[int, int]:
    """笔尖锚点：优先读手素材旁的 <name>.tip.json（{"tip":[x,y]}，原图坐标），
    缺省退 HAND_TIP_RATIO 比例。换手素材必须二选一校准（kernel-design §3 第 7 条），
    sidecar 是显式校准，比全局比例常数可靠。
    """
    tip_json = Path(hand_png).with_suffix(".tip.json")
    if tip_json.exists():
        try:
            data = json.loads(tip_json.read_text(encoding="utf-8"))
            tx, ty = data["tip"]
            iw, ih = Image.open(hand_png).size
            return (int(img_size[0] * float(tx) / iw), int(img_size[1] * float(ty) / ih))
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            pass
    return (int(img_size[0] * HAND_TIP_RATIO[0]), int(img_size[1] * HAND_TIP_RATIO[1]))


def _mask_strokes(strokes: list[np.ndarray], mask: np.ndarray,
                 min_points: int = 2) -> list[np.ndarray]:
    """Split polylines into contiguous portions covered by mask."""
    out: list[np.ndarray] = []
    h, w = mask.shape[:2]
    for s in strokes:
        if len(s) < min_points:
            continue
        keep = mask[np.clip(s[:, 1], 0, h - 1), np.clip(s[:, 0], 0, w - 1)]
        bounds = np.where(np.diff(keep.astype(np.int8)) != 0)[0] + 1
        start = 0
        state = bool(keep[0])
        for end in list(bounds) + [len(s)]:
            if state and end - start >= min_points:
                out.append(s[start:end])
            start = end
            state = not state
    return out


def _delta_strokes(strokes: list[np.ndarray], current: np.ndarray,
                   initial: np.ndarray) -> list[np.ndarray]:
    """Return only stroke segments that are new on a persistent whiteboard.

    Scene boards remain complete illustrations; the renderer must not redraw ink
    that already exists on the previous scene's canvas.
    """
    import cv2
    if current.shape != initial.shape:
        return strokes
    ink_now = extract_ink_mask(current)
    ink_old = extract_ink_mask(initial)
    old_dilated = cv2.dilate(ink_old.astype(np.uint8),
                             np.ones((7, 7), np.uint8)).astype(bool)
    delta = ink_now & ~old_dilated
    changed = (np.abs(current.astype(np.int16) - initial.astype(np.int16)).sum(axis=2) > 90)
    delta |= changed & ink_now
    delta = cv2.dilate(delta.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    out: list[np.ndarray] = []
    for s in strokes:
        keep = delta[np.clip(s[:, 1], 0, delta.shape[0]-1),
                     np.clip(s[:, 0], 0, delta.shape[1]-1)]
        if not keep.any():
            continue
        bounds = np.where(np.diff(keep.astype(np.int8)) != 0)[0] + 1
        start = 0
        state = bool(keep[0])
        for end in list(bounds) + [len(s)]:
            if state and end - start >= 2:
                out.append(s[start:end])
            start = end
            state = not state
    return out


def render_region_scene(board_png: Path, annotation_json: Path, out_mp4: Path,
                        hand_png: Path, fps: int = 30,
                        total_ms: int | None = None,
                        overlay_png: Path | None = None,
                        fade_from_png: Path | None = None,
                        hand_follow: float = 1.0,
                        labels_json: Path | None = None,
                        initial_board_png: Path | None = None) -> Path:
    """单幕渲染入口：区域时序揭示 + 描线/填色 + 手部贴笔尖 → H.264 MP4。

    board_png = 内容原图（墨迹来源）；overlay_png = 版式 overlay（raw + 标签文字）。
    labels_json = 标签清单（[{text, bbox, panel}]，apply_layout 旁车输出）：存在时
    标签不再从第 0 帧常驻，而是随所属 panel 的岛画完后淡入（LABEL_FADE_MS）；
    缺失时回退旧行为：overlay 与原图的差集作 chrome 第 0 帧直接显现。
    fade_from_png = 上一幕的板面：幕首 FADE_IN_MS 内从它淡出到背景色，
    模拟"擦黑板"的自然切幕（替代硬切）。
    hand_follow：手部显示位置缓动系数（见 hand_follow_step；默认 1.0 硬贴）。
    """
    board, _ink, skel = load_board_layers(board_png)
    if not board.flags.writeable:
        board = board.copy()  # 确保可写（MOVE 物体会提前清除 board 中原始位置）
    h, w = board.shape[:2]
    ann = parse_annotation(annotation_json)
    duration_ms = int(total_ms or ann.scene_duration_ms or 0)
    if duration_ms <= 0:
        raise RuntimeError("无法确定场景时长：total_ms 与 annotation.sceneDurationMs 均缺失")

    base = board.copy()  # 确保可写（MOVE 物体会修改 base）
    chrome_mask = None
    labels: list[dict] = []
    overlay = None
    if overlay_png is not None and Path(overlay_png).exists():
        _ov = np.asarray(Image.open(overlay_png).convert("RGB"))
        if _ov.shape == board.shape:
            overlay = _ov
    if overlay is not None and labels_json is not None and Path(labels_json).exists():
        # 标签延迟揭示：每枚标签 = bbox 内 overlay 与原图的差集像素
        spec = json.loads(Path(labels_json).read_text(encoding="utf-8"))
        diff = np.abs(overlay.astype(np.int16) - board.astype(np.int16)).sum(axis=2)
        for item in spec:
            bx, by, bw, bh = [int(v) for v in item["bbox"]]
            m = np.zeros(diff.shape, dtype=bool)
            m[by:by + bh, bx:bx + bw] = diff[by:by + bh, bx:bx + bw] > 24
            if m.any():
                labels.append({"mask": m, "panel": int(item.get("panel", 0)),
                               "reveal_ms": None})
    elif overlay is not None:
        # 旧行为回退：chrome 第 0 帧常驻（无标签清单的期次/测试夹具）
        diff = np.abs(overlay.astype(np.int16) - board.astype(np.int16)).sum(axis=2)
        chrome_mask = diff > 24
        base[chrome_mask] = overlay[chrome_mask]

    prev_board = None
    if fade_from_png is not None and Path(fade_from_png).exists():
        pb = np.asarray(Image.open(fade_from_png).convert("RGB"))
        if pb.shape == board.shape:
            prev_board = pb

    initial_board = None
    if initial_board_png is not None and Path(initial_board_png).exists():
        ib = np.asarray(Image.open(initial_board_png).convert("RGB"))
        if ib.shape == board.shape:
            initial_board = ib
    elif prev_board is not None:
        initial_board = prev_board

    content_elements = [e for e in ann.elements if e.eid != "layout"]

    # 在 build_tasks 之前清除 board 中 MOVE 物体的原始位置，并重新生成 ink/skeleton。
    # 关键：draw 任务从 skeleton 提取笔画，如果只清 board 不清 skeleton，MOVE 结束后
    # draw 任务会把物体原始位置重新画到 canvas 上，破坏匹配剪辑连续性。
    # 必须在 build_tasks 之前清除并重新生成 skeleton，这样 draw 任务不会提取这些笔画。
    _bg_for_clear = np.array(estimate_bg(board))
    _has_move = False
    for el in content_elements:
        for op in el.ops:
            if isinstance(op, dict) and op.get("op") == "MOVE":
                _has_move = True
                x, y = int(op["from"][0]), int(op["from"][1])
                w_obj, h_obj = int(op["rect"][2]), int(op["rect"][3])
                cx0 = max(0, x)
                cy0 = max(0, y)
                cx1 = min(board.shape[1], x + w_obj)
                cy1 = min(board.shape[0], y + h_obj)
                if cx1 > cx0 and cy1 > cy0:
                    board[cy0:cy1, cx0:cx1] = _bg_for_clear
    if _has_move:
        # 重新生成 ink 和 skeleton，确保 draw 任务不包含物体原始位置的笔画
        _ink = extract_ink_mask(board)
        if _ink.any():
            skel = zhang_suen_skeleton(_ink)

    strokes_for_tasks = _trace_merged(skel, (w, h))
    delta_mask = None
    if initial_board is not None:
        # 与 _delta_strokes 使用同一套像素语义，保证描线/填色增量一致。
        import cv2
        ink_now = extract_ink_mask(board)
        ink_old = extract_ink_mask(initial_board)
        old_dilated = cv2.dilate(ink_old.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
        delta_mask = ink_now & ~old_dilated
        changed = (np.abs(board.astype(np.int16) - initial_board.astype(np.int16)).sum(axis=2) > 90)
        delta_mask |= changed & ink_now
        delta_mask = cv2.dilate(delta_mask.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
        strokes_for_tasks = _delta_strokes(strokes_for_tasks, board, initial_board)
    tasks = build_tasks(content_elements, board, strokes_for_tasks, skeleton=skel,
                        delta_mask=delta_mask)
    if not any(t.kind == "draw" for t in tasks) and initial_board is None:
        raise RuntimeError("时序编排结果为零绘制任务")
    draw_tasks = [t for t in tasks if t.kind == "draw"]
    draw_end = max((t.end_ms for t in draw_tasks), default=0)

    # 标签揭示时刻 = 所属 panel 最后一个任务的结束时间（随岛画完淡入）
    if labels:
        eid_end: dict[str, int] = {}
        for tk in tasks:
            eid_end[tk.eid] = max(eid_end.get(tk.eid, 0), tk.end_ms)
        ann_end = {e.eid: e.start_ms + e.duration_ms for e in content_elements}
        for lb in labels:
            eid = f"panel-{lb['panel']}"
            lb["reveal_ms"] = eid_end.get(eid, ann_end.get(eid, draw_end))

    # 提交 MOVE 物体到 base：清除原始位置，粘贴到目标位置。
    # 必须在 build_tasks 之后、渲染循环之前执行，因为 base 可能是 board.copy()，
    # build_tasks 内部修改 board 不会同步到 base。直接修改 base 确保
    # canvas[:] = base 整图兜底重置后物体仍在目标位置（匹配剪辑连续性）。
    # 注意：嵌入像素时 _build_move_task 的 fill_origin=False，move_bg 中原始位置
    # 未被清除，因此这里直接用背景色填充物体原始位置，不依赖 move_bg。
    bg_color = np.array(estimate_bg(board))
    for tk in tasks:
        if tk.kind == "move" and tk.move_object is not None:
            # 1. 清除 base 中物体原始位置（直接用背景色填充）
            ox, oy = tk.move_from
            obj_h, obj_w = tk.move_object.shape[:2]
            cx0 = max(0, ox)
            cy0 = max(0, oy)
            cx1 = min(base.shape[1], ox + obj_w)
            cy1 = min(base.shape[0], oy + obj_h)
            if cx1 > cx0 and cy1 > cy0:
                base[cy0:cy1, cx0:cx1] = bg_color
            # 2. 粘贴物体到目标位置（alpha 混合）
            tx, ty = tk.move_to
            px0 = max(0, tx)
            py0 = max(0, ty)
            px1 = min(base.shape[1], tx + obj_w)
            py1 = min(base.shape[0], ty + obj_h)
            if px1 > px0 and py1 > py0:
                obj_slice = tk.move_object[0:py1 - py0, 0:px1 - px0]
                alpha = obj_slice[:, :, 3:4].astype(np.float32) / 255.0
                base[py0:py1, px0:px1] = (
                    obj_slice[:, :, :3].astype(np.float32) * alpha +
                    base[py0:py1, px0:px1].astype(np.float32) * (1.0 - alpha)
                ).astype(base.dtype)

    bg = estimate_bg(board)
    bg_arr = np.array(bg, dtype=np.float32)
    canvas = np.empty_like(board)
    canvas[:] = initial_board if initial_board is not None else bg
    if chrome_mask is not None and initial_board is None:
        canvas[chrome_mask] = base[chrome_mask]
    complete = False                      # 进入收尾整图态后不再回退
    hand_img = Image.open(hand_png).convert("RGBA")
    hand_w = max(64, int(w * 0.15))  # 手素材宽度=画面15%（原7.5%太小，粉笔在黑板上看不清）
    hand_img = hand_img.resize((hand_w, int(hand_img.height * hand_w / hand_img.width)))
    tip = _hand_tip(hand_png, hand_img.size)
    hand_levels = tuple(_hand_alpha_img(hand_img, a) for a in (0.25, 0.5, 0.75, 1.0))
    hand_alpha = 0.0
    # 手的初始位置 = 第一笔的起点（不再悬在画面顶部）
    first_draw = next((t for t in tasks if t.kind == "draw" and t.pts is not None and len(t.pts)),
                      None)
    cursor = ((float(first_draw.pts[0][0]), float(first_draw.pts[0][1]))
              if first_draw is not None else (w / 2.0, 60.0))
    step_px = TRAVEL_SPEED_PX_MS * 1000.0 / fps      # 空档滑行单帧步长
    ink_starts = [t.start_ms for t in tasks if t.kind == "draw"]
    ink_i = 0
    hand_visible = False                                  # 每帧由落墨规则统一判定，初始离画
    display_pos = cursor                                  # 手部显示位置（hand_follow 平滑后）

    proc, _cmd = _open_ffmpeg_rawvideo_writer(Path(out_mp4), (w, h), fps)
    assert proc.stdin is not None
    try:
        n_tasks = len(tasks)
        ptr = 0
        n_frames = int(round(duration_ms / 1000 * fps))
        for f in range(n_frames):
            t_ms = f / fps * 1000
            # 补画：短于帧间隔的任务整段落墨，杜绝跳帧丢笔画
            while ptr < n_tasks and tasks[ptr].end_ms < t_ms:
                tk = tasks[ptr]
                if tk.kind == "draw" and not complete and tk.painted < len(tk.pts):
                    seg = tk.pts[tk.painted:]
                    _paint_points(canvas, base, seg[:, 1], seg[:, 0])
                    tk.painted = len(tk.pts)
                    cursor = (float(tk.pts[-1][0]), float(tk.pts[-1][1]))
                ptr += 1
            active = tasks[ptr] if ptr < n_tasks and tasks[ptr].start_ms <= t_ms <= tasks[ptr].end_ms else None

            if active is not None and active.kind == "draw" and not complete:
                # 线性推进＝恒定笔速：连画碎段拼成连续笔迹，逐段缓动会重新引入顿挫
                local = (t_ms - active.start_ms) / max(1, active.end_ms - active.start_ms)
                upto = float(active.cum[min(int(len(active.cum) * local), len(active.cum) - 1)]) if len(active.cum) else 0.0
                idx = int(np.searchsorted(active.cum, upto, side="right"))
                idx = min(idx, len(active.pts))
                if idx > active.painted:
                    seg = active.pts[active.painted:idx]
                    _paint_points(canvas, base, seg[:, 1], seg[:, 0])
                    active.painted = idx
                last_pt = active.pts[min(idx, len(active.pts) - 1)]
                cursor = (float(last_pt[0]), float(last_pt[1]))
            elif active is not None and active.kind == "move":
                # 转场操作：物体从 from 移动到 to，其他元素静止，手隐藏
                k = ease_in_out((t_ms - active.start_ms) / max(1, active.end_ms - active.start_ms))
                cx = int(active.move_from[0] + (active.move_to[0] - active.move_from[0]) * k)
                cy = int(active.move_from[1] + (active.move_to[1] - active.move_from[1]) * k)
                # 恢复移动路径区域的背景（物体原始位置已被替换为背景色）
                px, py, pw, ph = active.move_rect
                if pw > 0 and ph > 0 and active.move_bg is not None:
                    canvas[py:py + ph, px:px + pw] = active.move_bg
                # 贴物体到当前位置（alpha 混合）
                if active.move_object is not None:
                    obj_h, obj_w = active.move_object.shape[:2]
                    ox0 = max(0, cx)
                    oy0 = max(0, cy)
                    ox1 = min(canvas.shape[1], cx + obj_w)
                    oy1 = min(canvas.shape[0], cy + obj_h)
                    if ox1 > ox0 and oy1 > oy0:
                        obj_slice = active.move_object[0:oy1 - oy0, 0:ox1 - ox0]
                        alpha = obj_slice[:, :, 3:4].astype(np.float32) / 255.0
                        canvas[oy0:oy1, ox0:ox1] = (
                            obj_slice[:, :, :3].astype(np.float32) * alpha +
                            canvas[oy0:oy1, ox0:ox1].astype(np.float32) * (1.0 - alpha)
                        ).astype(canvas.dtype)
                    cursor = (float(cx + obj_w // 2), float(cy + obj_h // 2))
            elif active is not None and active.kind == "travel":
                k = ease_in_out((t_ms - active.start_ms) / max(1, active.end_ms - active.start_ms))
                cursor = (cursor[0] + (active.target[0] - cursor[0]) * k,
                          cursor[1] + (active.target[1] - cursor[1]) * k)
            else:
                # 空档帧：光标匀速滑向下一个任务的落笔点（手此时离画，滑行不可见）
                up = tasks[ptr] if ptr < n_tasks else None
                if up is not None:
                    if up.kind == "draw" and up.pts is not None and len(up.pts):
                        tgt = (float(up.pts[0][0]), float(up.pts[0][1]))
                    elif up.target is not None:
                        tgt = (float(up.target[0]), float(up.target[1]))
                    else:
                        tgt = None
                    if tgt is not None:
                        dx, dy = tgt[0] - cursor[0], tgt[1] - cursor[1]
                        dist = math.hypot(dx, dy)
                        if dist > step_px:
                            cursor = (cursor[0] + dx / dist * step_px,
                                      cursor[1] + dy / dist * step_px)
                        else:
                            cursor = tgt

            # 手只随落墨出现：draw 期间在画；MOVE 离画（物体自己在动）；空档/位移离画，
            # 仅下一笔前 HAND_LEAD_MS 淡入（光标已在落笔点，不会出现空移的手）
            if active is not None and active.kind == "draw":
                hand_visible = True
            elif active is not None and active.kind == "move":
                hand_visible = False
            else:
                while ink_i < len(ink_starts) and ink_starts[ink_i] <= t_ms:
                    ink_i += 1
                hand_visible = (ink_i < len(ink_starts)
                                and ink_starts[ink_i] - t_ms <= HAND_LEAD_MS)

            # 幕首淡入：从上一幕板面淡出到背景色（擦黑板式切幕；首笔最早 1050ms，
            # 与淡入窗不重叠，不会覆盖已画内容）
            if prev_board is not None and initial_board is None and t_ms < FADE_IN_MS and not complete:
                # 时钟前推一帧让窗口末帧 k 恰为 1：否则末帧 (1-k)≈0.7% 的上一幕残影
                # 会留在 canvas 上直到收尾整图兜底（平坦帧编码为 skip，残影不刷新）
                k = ease_in_out(min(1.0, (t_ms + 1000.0 / fps) / FADE_IN_MS))
                canvas[:] = (prev_board.astype(np.float32) * (1.0 - k)
                             + bg_arr * k).astype(canvas.dtype)
                if chrome_mask is not None:
                    canvas[chrome_mask] = base[chrome_mask]

            if not complete and t_ms >= draw_end:
                if initial_board is None:
                    canvas[:] = base
                complete = True

            # 标签揭示：随所属岛画完淡入，最后合成保证不被后续笔画覆盖
            for lb in labels:
                rv = lb["reveal_ms"]
                if rv is None or t_ms < rv:
                    continue
                a = min(1.0, (t_ms - rv) / LABEL_FADE_MS)
                m = lb["mask"]
                canvas[m] = (canvas[m].astype(np.float32) * (1.0 - a)
                             + overlay[m].astype(np.float32) * a).astype(canvas.dtype)

            frame = Image.fromarray(canvas)
            target = 1.0 if hand_visible else 0.0
            step_a = (1000.0 / fps) / HAND_FADE_MS
            if hand_alpha < target:
                hand_alpha = min(target, hand_alpha + step_a)
            elif hand_alpha > target:
                hand_alpha = max(target, hand_alpha - step_a)
            if hand_alpha > 0.02:
                display_pos = hand_follow_step(display_pos, cursor, hand_follow)
                himg = hand_levels[min(3, max(0, int(round(hand_alpha * 4)) - 1))]
                frame.paste(himg, (int(display_pos[0]) - tip[0],
                                   int(display_pos[1]) - tip[1]), himg)
            proc.stdin.write(frame.convert("RGB").tobytes())
    finally:
        proc.stdin.close()
        proc.wait()

    if not Path(out_mp4).exists():
        raise RuntimeError(f"内核未产出 {out_mp4}")
    return Path(out_mp4)


if __name__ == "__main__":      # pragma: no cover
    ap = argparse.ArgumentParser(description="分区同步白板渲染内核 v1")
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--annotation", type=Path, required=True)
    ap.add_argument("--hand", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fps", type=int, default=30)
    args = ap.parse_args()
    print(render_region_scene(args.board, args.annotation, args.out, args.hand, args.fps))
