#!/usr/bin/env python3
"""转场物体裁剪与 MOVE op 生成工具（完整版，支持6个转场）。

从源场景板图裁剪转场物体（带 alpha mask），编码为 base64 PNG，
在源场景 annotation 中添加转出 MOVE op（物体从当前位置→画面中央），
在目标场景 annotation 中添加转入 MOVE op（物体从画面中央→目标位置）。

匹配剪辑原理：切换点在画面中央，物体速度峰值，观众无感知。

用法：
  python transition_gen.py --episode-dir <项目目录>
  python transition_gen.py --episode-dir <项目目录> --recommend  # 半自动推荐转场物体
"""
import argparse
import base64
import json
import sys
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# 转场物体配置在运行时根据 --episode-dir 解析路径
BOARDS_LAYOUT: Path | None = None
ANNOTATIONS: Path | None = None
LAYOUT_JSON: Path | None = None


def recommend_transitions(episode_dir: Path) -> list[dict]:
    """半自动推荐转场物体：基于 layout.json 的区域位置和大小，
    为每个相邻场景对推荐最适合作为转场的物体区域。

    推荐逻辑：
    1. 读取 layout.json，获取每个场景的 panels 列表
    2. 对每个相邻场景对（scene-i → scene-i+1），选择源场景中
       面积最大且位置显著的 panel 作为转场物体候选
    3. 目标位置选择目标场景中对应的 panel 位置（同序号或最接近的）
    4. 输出推荐配置，用户确认后可直接用于 TRANSITIONS
    """
    layout_path = episode_dir / "input" / "layout.json"
    if not layout_path.exists():
        print(f"✗ layout.json 不存在：{layout_path}")
        print("  请先运行 build_video.py layout 生成 layout.json，或手动创建")
        return []
    try:
        doc = json.loads(layout_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"✗ layout.json 解析失败：{e}")
        return []
    # 获取所有场景ID（按序号排序）
    scene_ids = sorted([k for k in doc.keys() if k.startswith("scene-")])
    if len(scene_ids) < 2:
        print(f"✗ 场景数不足（{len(scene_ids)}），至少需要2个场景才能生成转场")
        return []
    recommendations = []
    for i in range(len(scene_ids) - 1):
        src_scene = scene_ids[i]
        tgt_scene = scene_ids[i + 1]
        src_panels = doc.get(src_scene, {}).get("panels", [])
        tgt_panels = doc.get(tgt_scene, {}).get("panels", [])
        if not src_panels or not tgt_panels:
            print(f"! {src_scene} → {tgt_scene}：panels 为空，跳过")
            continue
        # 选择源场景中面积最大的 panel 作为转场物体
        def panel_area(p):
            if isinstance(p, dict):
                w = p.get("width", p.get("w", 0))
                h = p.get("height", p.get("h", 0))
                return w * h
            if isinstance(p, (list, tuple)) and len(p) >= 4:
                return p[2] * p[3]
            return 0
        best_idx = max(range(len(src_panels)), key=lambda i: panel_area(src_panels[i]))
        best_panel = src_panels[best_idx]
        if isinstance(best_panel, dict):
            x = best_panel.get("x", 0)
            y = best_panel.get("y", 0)
            w = best_panel.get("width", best_panel.get("w", 0))
            h = best_panel.get("height", best_panel.get("h", 0))
            source_rect = [x, y, w, h]
        else:
            source_rect = [int(best_panel[0]), int(best_panel[1]),
                           int(best_panel[2]), int(best_panel[3])]
        # 目标位置：选择目标场景中同序号的 panel，或面积最大的
        tgt_idx = best_idx if best_idx < len(tgt_panels) else 0
        tgt_panel = tgt_panels[tgt_idx]
        if isinstance(tgt_panel, dict):
            target_pos = [tgt_panel.get("x", 0), tgt_panel.get("y", 0)]
        else:
            target_pos = [int(tgt_panel[0]), int(tgt_panel[1])]
        rec = {
            "source_scene": src_scene,
            "target_scene": tgt_scene,
            "object_name": f"{src_scene}-panel-{best_idx + 1}",
            "source_rect": source_rect,
            "target_pos": target_pos,
            "confidence": "high" if best_idx < len(tgt_panels) else "medium",
            "note": f"源场景面积最大的 panel-{best_idx + 1}（{source_rect[2]}x{source_rect[3]}）"
                    + ("，目标场景同序号 panel" if best_idx < len(tgt_panels)
                       else "，目标场景回退到 panel-1"),
        }
        recommendations.append(rec)
    return recommendations

# 完整转场物体链（6对）
# source_rect: 物体在源场景板图中的精确位置 [x,y,w,h]（1920x1080坐标）
# target_pos: 物体在目标场景板图中的最终位置 [x,y]（左上角坐标）
TRANSITIONS = [
    {
        "source_scene": "scene-01",
        "object_name": "AI机器人",
        "source_rect": [1354, 497, 164, 135],  # 最下方AI机器人
        "target_scene": "scene-02",
        "target_pos": [1600, 60],  # 右上
    },
    {
        "source_scene": "scene-02",
        "object_name": "生成机器",
        "source_rect": [556, 380, 359, 369],  # 中央生成机器
        "target_scene": "scene-03",
        "target_pos": [700, 120],  # 中央偏上
    },
    {
        "source_scene": "scene-03",
        "object_name": "思考人物",
        "source_rect": [59, 680, 271, 324],  # 左下人物
        "target_scene": "scene-04",
        "target_pos": [60, 80],  # 左上
    },
    {
        "source_scene": "scene-04",
        "object_name": "代码窗口",
        "source_rect": [60, 60, 420, 380],  # 左上代码窗口
        "target_scene": "scene-05",
        "target_pos": [1380, 60],  # 右上
    },
    {
        "source_scene": "scene-05",
        "object_name": "评分牌",
        "source_rect": [312, 299, 544, 638],  # 中央评分牌
        "target_scene": "scene-06",
        "target_pos": [80, 80],  # 左上
    },
    {
        "source_scene": "scene-06",
        "object_name": "干净页面",
        "source_rect": [1250, 440, 380, 420],  # 右下干净页面
        "target_scene": "scene-07",
        "target_pos": [720, 300],  # 中央
    },
]

# MOVE 时长（毫秒）
MOVE_DURATION_MS = 700
# 转出开始时间偏移（场景结尾前多少毫秒开始）
MOVE_OUT_OFFSET_MS = 900
# 转入开始时间（场景开头后多少毫秒开始，需等淡入完成）
MOVE_IN_START_MS = 400


def center_pos(w, h):
    """计算物体左上角的画面中央位置。"""
    return [(1920 - w) // 2, (1080 - h) // 2]


def crop_object_with_alpha(board_path, rect):
    """从板图裁剪物体区域，生成带 alpha mask 的 RGBA 图像。"""
    img = cv2.imread(str(board_path))
    if img is None:
        raise RuntimeError(f"无法读取板图: {board_path}")
    x, y, w, h = rect
    h_img, w_img = img.shape[:2]
    x0 = max(0, min(x, w_img - 1))
    y0 = max(0, min(y, h_img - 1))
    x1 = max(x0 + 1, min(x + w, w_img))
    y1 = max(y0 + 1, min(y + h, h_img))
    obj_rgb = img[y0:y1, x0:x1].copy()

    # 估计背景色（板图四角中位数）
    corners = np.vstack([
        img[0:30, 0:30].reshape(-1, 3),
        img[0:30, -30:].reshape(-1, 3),
        img[-30:, 0:30].reshape(-1, 3),
        img[-30:, -30:].reshape(-1, 3),
    ])
    bg = np.median(corners, axis=0)

    # alpha mask：与背景色差大的像素是物体
    dist = np.abs(obj_rgb.astype(np.int16) - bg).sum(axis=2)
    alpha = (dist > 120).astype(np.uint8) * 255
    # 膨胀 alpha 确保物体边缘不被截断
    alpha = cv2.dilate(alpha, np.ones((3, 3), np.uint8))

    obj_rgba = np.dstack([obj_rgb, alpha])
    return obj_rgba


def encode_png_base64(obj_rgba):
    """将 RGBA numpy 数组编码为 base64 PNG。"""
    img_pil = Image.fromarray(obj_rgba, mode="RGBA")
    buf = BytesIO()
    img_pil.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def add_move_out(annotation_path, object_name, rect, from_pos, to_pos, scene_duration, object_png_b64):
    """在源场景 annotation 中添加转出 MOVE op（嵌入物体像素，确保提交到 base 时可用）。"""
    ann = json.loads(annotation_path.read_text(encoding="utf-8"))
    w, h = rect[2], rect[3]
    move_element = {
        "id": f"transition-out-{object_name}",
        "sequence": 900,
        "region": {"x": from_pos[0], "y": from_pos[1], "width": w, "height": h},
        "reveal": {
            "startMs": scene_duration - MOVE_OUT_OFFSET_MS,
            "durationMs": MOVE_DURATION_MS,
            "protectedRegions": []
        },
        "ops": [
            {
                "op": "MOVE",
                "target": object_name,
                "rect": rect,
                "from": list(from_pos),
                "to": list(to_pos),
                "object_png": object_png_b64,
            }
        ]
    }
    ann["elements"].append(move_element)
    annotation_path.write_text(json.dumps(ann, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  转出: {from_pos} → {to_pos}, {scene_duration - MOVE_OUT_OFFSET_MS}ms (嵌入像素)")


def add_move_in(annotation_path, object_name, rect, from_pos, to_pos, object_png_b64):
    """在目标场景 annotation 中添加转入 MOVE op（使用嵌入的物体像素）。"""
    ann = json.loads(annotation_path.read_text(encoding="utf-8"))
    w, h = rect[2], rect[3]
    move_element = {
        "id": f"transition-in-{object_name}",
        "sequence": 1,
        "region": {"x": from_pos[0], "y": from_pos[1], "width": w, "height": h},
        "reveal": {
            "startMs": MOVE_IN_START_MS,
            "durationMs": MOVE_DURATION_MS,
            "protectedRegions": []
        },
        "ops": [
            {
                "op": "MOVE",
                "target": object_name,
                "rect": rect,
                "from": list(from_pos),
                "to": list(to_pos),
                "object_png": object_png_b64,
            }
        ]
    }
    ann["elements"].append(move_element)
    annotation_path.write_text(json.dumps(ann, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  转入: {from_pos} → {to_pos}, {MOVE_IN_START_MS}ms (嵌入像素, {len(object_png_b64)}字符)")


def main():
    global BOARDS_LAYOUT, ANNOTATIONS
    ap = argparse.ArgumentParser(description="转场物体裁剪与 MOVE op 生成工具")
    ap.add_argument("--episode-dir", required=True, type=Path,
                    help="项目目录（包含 build/boards-layout/ 和 build/annotations/）")
    ap.add_argument("--recommend", action="store_true",
                    help="半自动推荐模式：基于 layout.json 分析并输出推荐的转场物体配置（不修改文件）")
    args = ap.parse_args()
    ep = args.episode_dir.resolve()
    BOARDS_LAYOUT = ep / "build" / "boards-layout"
    ANNOTATIONS = ep / "build" / "annotations"
    LAYOUT_JSON = ep / "input" / "layout.json"

    # 推荐模式：只输出推荐配置，不修改文件
    if args.recommend:
        print("=" * 60)
        print("转场物体半自动推荐（基于 layout.json）")
        print("=" * 60)
        recs = recommend_transitions(ep)
        if not recs:
            print("\n✗ 无法生成推荐（请检查 layout.json 是否存在且包含至少2个场景）")
            return
        print(f"\n✓ 生成 {len(recs)} 个转场推荐：\n")
        for i, rec in enumerate(recs, 1):
            print(f"  [{i}] {rec['source_scene']} → {rec['target_scene']}")
            print(f"      物体: {rec['object_name']}（置信度: {rec['confidence']}）")
            print(f"      source_rect: {rec['source_rect']}")
            print(f"      target_pos: {rec['target_pos']}")
            print(f"      说明: {rec['note']}")
            print()
        # 输出可直接复制的 TRANSITIONS 配置
        print("=" * 60)
        print("可直接复制到 TRANSITIONS 列表的配置：")
        print("=" * 60)
        print(json.dumps(recs, ensure_ascii=False, indent=2))
        print("\n提示：确认后将上述配置复制到 transition_gen.py 的 TRANSITIONS 列表，")
        print("      然后运行 `python transition_gen.py --episode-dir <dir>` 生成 MOVE op")
        return

    if not BOARDS_LAYOUT.exists():
        sys.exit(f"板图目录不存在：{BOARDS_LAYOUT}")
    if not ANNOTATIONS.exists():
        sys.exit(f"标注目录不存在：{ANNOTATIONS}")

    for t in TRANSITIONS:
        src_scene = t["source_scene"]
        tgt_scene = t["target_scene"]
        obj_name = t["object_name"]
        src_rect = t["source_rect"]
        tgt_pos = t["target_pos"]
        w, h = src_rect[2], src_rect[3]

        print(f"\n{'='*60}")
        print(f"转场: {src_scene} → {tgt_scene} ({obj_name})")
        print(f"{'='*60}")

        # 1. 从源场景板图裁剪物体
        src_board = BOARDS_LAYOUT / f"{src_scene}.raw.png"
        obj_rgba = crop_object_with_alpha(src_board, src_rect)
        alpha_ratio = float((obj_rgba[:, :, 3] > 0).mean())
        print(f"  物体裁剪: {obj_rgba.shape}, alpha非零占比={alpha_ratio:.3f}")

        # 2. 编码为 base64 PNG
        obj_b64 = encode_png_base64(obj_rgba)

        # 3. 计算画面中央位置
        center = center_pos(w, h)
        print(f"  画面中央: {center}")

        # 4. 读取源场景时长
        src_ann_path = ANNOTATIONS / f"{src_scene}.annotation.json"
        src_ann = json.loads(src_ann_path.read_text(encoding="utf-8"))
        src_duration = src_ann.get("sceneDurationMs", 20000)

        # 5. 添加转出 MOVE op
        add_move_out(src_ann_path, obj_name, src_rect,
                     (src_rect[0], src_rect[1]), center, src_duration, obj_b64)

        # 6. 添加转入 MOVE op
        tgt_ann_path = ANNOTATIONS / f"{tgt_scene}.annotation.json"
        add_move_in(tgt_ann_path, obj_name, src_rect, center, tgt_pos, obj_b64)

    print(f"\n{'='*60}")
    print("全部6个转场 MOVE op 生成完成！")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
