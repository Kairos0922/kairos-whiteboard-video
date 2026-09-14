"""板图审核：尺寸 / 长宽比 / 底色一致性 / 底部留白带，供 workflow import 使用。

按 style-spec.md 的约定做自动检查；文字与分区的最终判断交给人工二审（第二次确认）。
检查结果记入 state.json，不改变图片文件。
底色检查跟主题走：theme.json 的 renderer_mode=paper 查四角暖白，
renderer_mode=chalk 查四角为板底色（palette.board）且整体偏暗。
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

PAPER_MIN_LUMA = 185.0           # 纸面模式：四角平均亮度下限（暖白素描纸）
CHALK_MAX_LUMA = 130.0           # 黑板模式：四角平均亮度上限（深板绿）
CORNER_PATCH = 48               # 四角采样窗边长
CORNER_TOL = 60                  # 与底色 BGR 单通道差上限
BOTTOM_BAND_RATIO = 0.20        # 底部 1/5 为字幕区
MIN_LONG_EDGE = 1920
ASPECT = 16.0 / 9.0
ASPECT_TOL = 0.03              # 「16:9 家族」准入带宽：宿主常出 1792×1024（=1.75，差 0.028）


def _hex_to_bgr(hex_color: str) -> np.ndarray:
    h = hex_color.lstrip("#")
    return np.array([int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)], dtype=np.int16)


def _theme_mode(theme_dir: Path | None) -> tuple[str, np.ndarray | None]:
    """读主题包：返回 (renderer_mode, 板底色 BGR)。读不到一律退回 paper。"""
    if theme_dir:
        tj = Path(theme_dir) / "theme.json"
        if tj.exists():
            try:
                data = json.loads(tj.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return "paper", None
            mode = str(data.get("renderer_mode") or "paper")
            board_hex = (data.get("palette") or {}).get("board")
            board_bgr = _hex_to_bgr(board_hex) if board_hex else None
            return mode, board_bgr
    return "paper", None


def normalize_board_size(path: Path,
                         target_w: int = 1920, target_h: int = 1080) -> dict:
    """把「16:9 家族」的板图归一化到 1920×1080（写回原文件）。

    生图服务常输出 1200×675 这类 16:9 小图，也常只能出 1792×1024（=1.75）这类
    近似 16:9 的档位，直接过 check_board 会被 MIN_LONG_EDGE 或长宽比阻断。
    处理：比例落在 ASPECT_TOL 带内时，先**居中裁**到精确 16:9 再等比放大——
    不用非等比拉伸（那会把板面几何畸变掉），裁切只动边缘余量
    （构图纪律是四周留白 + 底部 1/5 空，内容不在被裁的那几像素上）。
    内核描线在缩放后的像素上进行，笔画与填色自动按新尺度调度，缩放无损。
    比例超出准入带的图不动，交给 check_board 按错误处理。

    返回 {"scaled": bool, "size": 原尺寸 | None, "cropped": 裁切后中间尺寸 | None}；
    scaled=False 时 size 为原尺寸（含读图失败时 None，调用方后续 check_board 会兜底报错）。
    """
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return {"scaled": False, "size": None, "cropped": None}
    h, w = img.shape[:2]
    if (w, h) == (target_w, target_h):
        return {"scaled": False, "size": (w, h), "cropped": None}
    if abs(w / max(h, 1) - ASPECT) > ASPECT_TOL:
        return {"scaled": False, "size": (w, h), "cropped": None}
    cropped = None
    ratio = w / max(h, 1)
    if abs(ratio - ASPECT) > 1e-6:
        if ratio > ASPECT:                      # 过宽：裁左右两侧
            keep_w = int(round(h * ASPECT))
            x0 = (w - keep_w) // 2
            img = img[:, x0:x0 + keep_w]
        else:                                   # 过高：裁上下两侧
            keep_h = int(round(w / ASPECT))
            y0 = (h - keep_h) // 2
            img = img[y0:y0 + keep_h, :]
        cropped = (int(img.shape[1]), int(img.shape[0]))
    resized = cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
    cv2.imwrite(str(path), resized)
    return {"scaled": True, "size": (w, h), "cropped": cropped}


def check_board(path: Path, theme_dir: Path | None = None) -> dict:
    """逐项检查一张板图，返回 {ok, errors, warnings, info}。"""
    errors: list[str] = []
    warnings: list[str] = []
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return {"ok": False, "errors": [f"无法读取图片：{path}"], "warnings": [], "info": {}}
    h, w = img.shape[:2]
    info = {"width": w, "height": h, "aspect": round(w / h, 4)}

    ratio = w / h
    if abs(ratio - ASPECT) > 0.02:
        errors.append(f"长宽比 {ratio:.3f} 不是 16:9（±0.02）")
    if max(w, h) < MIN_LONG_EDGE:
        errors.append(f"长边 {max(w, h)}px 低于 {MIN_LONG_EDGE}px")

    mode, board_bgr = _theme_mode(theme_dir)
    info["renderer_mode"] = mode
    corner_scores = []
    for (y0, x0) in [(0, 0), (0, w - CORNER_PATCH), (h - CORNER_PATCH, 0),
                     (h - CORNER_PATCH, w - CORNER_PATCH)]:
        patch = img[y0:y0 + CORNER_PATCH, x0:x0 + CORNER_PATCH].astype(np.float32)
        luma = float(patch.mean())
        corner_scores.append(round(luma))
        if mode == "chalk":
            if luma > CHALK_MAX_LUMA:
                errors.append(f"角落平均亮度 {luma:.0f} > {CHALK_MAX_LUMA:.0f}，不像黑板深底")
            if board_bgr is not None:
                diff = float(np.abs(patch.mean(axis=(0, 1)) - board_bgr).max())
                if diff > CORNER_TOL:
                    errors.append(f"角落与板底色最大通道差 {diff:.0f} > {CORNER_TOL}（palette.board）")
        else:
            if luma < PAPER_MIN_LUMA:
                errors.append(f"角落平均亮度 {luma:.0f} < {PAPER_MIN_LUMA:.0f}，不像纸面白")
    info["corner_lumas"] = corner_scores

    # 底部 1/5 平均亮度：字幕区被内容侵入时提示。
    # paper：底部明显比上中部暗 = 有内容；chalk：底部明显比板底色亮 = 有内容。
    bottom = img[int(h * (1 - BOTTOM_BAND_RATIO)):, :].mean()
    top = img[: int(h * 0.6), :].mean()
    info["bottom_mean"] = round(float(bottom), 1)
    info["top_mean"] = round(float(top), 1)
    if mode == "chalk":
        board_luma = float(board_bgr.mean()) if board_bgr is not None else CHALK_MAX_LUMA * 0.6
        if bottom > board_luma + 40:
            warnings.append(f"底部 1/5 亮度({bottom:.0f})明显高于板底色({board_luma:.0f})，字幕带可能压到内容")
    elif bottom > top * 0.75:
        warnings.append(f"底部 1/5 亮度({bottom:.0f})接近上中部({top:.0f})，字幕带可能压到内容")

    # 空白检测：全图像素方差过低 = 可能是空白图或生图失败
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    pixel_std = float(gray.std())
    info["pixel_std"] = round(pixel_std, 1)
    BLANK_STD_THRESHOLD = 15.0  # 方差低于15 = 几乎纯色
    if pixel_std < BLANK_STD_THRESHOLD:
        errors.append(f"图像像素方差 {pixel_std:.1f} < {BLANK_STD_THRESHOLD}，可能是空白图或生图失败")

    # 低信息量检测：Laplacian 边缘像素占比过低 = 内容过少
    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    edge_pixels = int((np.abs(laplacian) > 30).sum())
    edge_ratio = edge_pixels / (h * w)
    info["edge_ratio"] = round(edge_ratio, 4)
    LOW_INFO_THRESHOLD = 0.005  # 边缘像素占比低于0.5% = 信息量过低
    if edge_ratio < LOW_INFO_THRESHOLD and pixel_std >= BLANK_STD_THRESHOLD:
        warnings.append(f"图像边缘像素占比 {edge_ratio:.4f} < {LOW_INFO_THRESHOLD}，信息量过低，可能是生图内容不足")

    # 文字检测：板图不得带可读文字（铁律），AI生图常违反。
    # 基于连通区域分析：文字 = 大量小而密集的连通区域，水平排列成行。
    text_info = _detect_text_regions(gray, h, w)
    info["text_detection"] = text_info
    if text_info["likely_text"]:
        warnings.append(f"检测到可能的可读文字（{text_info['text_line_count']}行，{text_info['small_component_count']}个小区域）。"
                       f"板图铁律：不得有可读文字（字母/数字/汉字），请重新生成无文字板图")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "info": info}


# 文字行判据（相对图高，跨分辨率成立）：
# 同一行 = y 中心落在锚点 ±2.5% 图高的窄带内；行内字形高度均匀（CV≤0.2）、
# 相邻间隙均匀（CV≤0.5）、平均字形高 ≤5% 图高、组件 ≥3 个；
# 整体需 ≥1 个合格行且小区域总数 ≥8。
# 阈值定标（2026-09-11）：真文字行 h_cv/gap_cv≈0；密集图示碎片假阳性
# h_cv≥0.2、gap_cv≥0.8（chalkboard-chibi 探针图实测），故取 0.2/0.5。
TEXT_LINE_BAND_RATIO = 0.025
TEXT_LINE_HEIGHT_CV = 0.2
TEXT_LINE_GAP_CV = 0.5
TEXT_LINE_HEIGHT_CAP = 0.05
TEXT_MIN_COMPONENTS = 8


def _detect_text_regions(gray: np.ndarray, h: int, w: int) -> dict:
    """基于连通区域分析检测板图中的可读文字。

    文字特征：
    - 小连通区域（面积 20-3000 像素，宽高比 0.1-10）
    - 组成水平"行"：y 中心同窄带、字形高度均匀、字形级大小
    - 排除角落水印区域（水印由 strip_watermark 单独处理）

    已知局限（2026-09-11 修）：v0 用链式聚类（与上一个组件比 y 差），
    密集图示符号会被串成纵贯半幅的假"行"（一排小人图标/图表节点必中），
    导致 chalk 主题每张板图都误报警告。现改为锚点窄带聚类 + 高度/间隙
    双均匀性判据（阈值经探针图定标，见常量注释）；尺寸字形级且间距均匀的
    一排小图标仍可能触发，warning 交人工二审按返回的行坐标放大复核即可，
    不阻断 import。另：自适应阈值在均匀深板上对亮色前景不敏感（检出能力
    偏向暗色字形），板图无文字铁律最终靠人工二审把关，本检测只是辅助。

    返回：{likely_text, text_line_count, small_component_count, lines, details}
    lines 为合格行的外接框 [{x, y, w, h, n}]，供二审快速定位。
    """
    # 自适应二值化提取前景（粉笔线条）
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 15, 5)
    # 连通区域分析
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

    # 筛选小连通区域（文字特征）
    small_components = []
    for i in range(1, num_labels):  # 跳过背景（label=0）
        x, y, cw, ch, area = stats[i]
        # 文字区域特征：面积 20-3000，宽高比 0.1-10，不是整行/整列
        if 20 <= area <= 3000 and 0.1 <= cw / max(ch, 1) <= 10 and cw < w * 0.3 and ch < h * 0.3:
            # 排除角落水印区域（左上角 18%×10%，右下角 18%×8%）
            cx, cy = centroids[i]
            in_top_left = cx < w * 0.18 and cy < h * 0.10
            in_bottom_right = cx > w * 0.82 and cy > h * 0.92
            if not in_top_left and not in_bottom_right:
                small_components.append((int(x), int(y), int(cw), int(ch),
                                         int(area), float(cx), float(cy)))

    # 检测文字行：锚点窄带聚类（按 y 中心排序后，收齐锚点 ±band 内的全部组件），
    # 再过双均匀性判据：字形高度 CV + 相邻间隙 CV。
    text_lines = []
    if len(small_components) >= 3:
        band = max(15.0, h * TEXT_LINE_BAND_RATIO)
        height_cap = h * TEXT_LINE_HEIGHT_CAP
        comps = sorted(small_components, key=lambda c: c[6])
        i = 0
        while i < len(comps):
            anchor_cy = comps[i][6]
            line = [c for c in comps[i:] if abs(c[6] - anchor_cy) <= band]
            i += len(line)
            if len(line) < 3:
                continue
            line.sort(key=lambda c: c[0])
            heights = np.array([c[3] for c in line], dtype=np.float64)
            gaps = np.array([line[j + 1][0] - (line[j][0] + line[j][2])
                             for j in range(len(line) - 1)], dtype=np.float64)
            height_cv = float(heights.std() / max(heights.mean(), 1e-6))
            gap_cv = (float(gaps.std() / max(gaps.mean(), 1e-6))
                      if len(gaps) >= 2 else 0.0)
            if heights.mean() > height_cap or height_cv > TEXT_LINE_HEIGHT_CV \
                    or gap_cv > TEXT_LINE_GAP_CV:
                continue
            text_lines.append(line)

    likely_text = len(text_lines) >= 1 and len(small_components) >= TEXT_MIN_COMPONENTS

    line_boxes = []
    for line in text_lines:
        x0 = min(c[0] for c in line)
        y0 = min(c[1] for c in line)
        x1 = max(c[0] + c[2] for c in line)
        y1 = max(c[1] + c[3] for c in line)
        line_boxes.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                           "n": len(line)})

    return {
        "likely_text": likely_text,
        "text_line_count": len(text_lines),
        "small_component_count": len(small_components),
        "lines": line_boxes,
        "details": (f"{len(text_lines)}行x{len(small_components)}区域"
                    if likely_text else "无明显文字特征"),
    }


# 平台水印（半透明文字，如"AI生成"）：板图不得带可读文字（铁律），
# 且判墨会把水印当墨迹画出来，import 前必须清除。
# 三层防御：多区域检测 → 纯色背景填充 → 清除后验证
WM_REGIONS = [
    # (x0_ratio, y0_ratio, x1_ratio, y1_ratio) — 检测角落最一小块
    # AI生成水印可能在左上角或右下角，通常只占最角落的 15%宽 × 8%高
    # 区域足够小，确保是纯背景，不会包含板图实际内容
    (0.0, 0.0, 0.18, 0.10),    # 左上角
    (0.82, 0.92, 1.0, 1.0),    # 右下角
]
WM_DIST = 45                          # 与局部背景色的三通道和差下限（半透明水印约30-60）
WM_MIN_PIXEL_RATIO = 0.002           # 检测到水印的最小像素占比（0.2%）
WM_MIN_PIXEL_COUNT = 30               # 检测到水印的最小绝对像素数（双重判断，满足任一即可）
WM_MAX_PIXEL_RATIO = 0.05             # 安全上限：非背景像素占比>5%说明是实际内容，跳过
WM_RESIDUAL_THRESHOLD = 0.003        # 清除后残留率阈值（超过则清除失败）
WM_BG_SAMPLE_MARGIN = 10             # 背景色采样边缘宽度（像素）


def _sample_background(img: np.ndarray, x0: int, y0: int, x1: int, y1: int) -> np.ndarray:
    """采样检测区域外一圈的背景色中位数，避免水印像素污染背景估计。"""
    h, w = img.shape[:2]
    patches = []
    m = WM_BG_SAMPLE_MARGIN
    # 上方
    if y0 - m >= 0:
        patches.append(img[max(0, y0 - m):y0, max(0, x0 - m):min(w, x1 + m)])
    # 下方
    if y1 + m <= h:
        patches.append(img[y1:min(h, y1 + m), max(0, x0 - m):min(w, x1 + m)])
    # 左方
    if x0 - m >= 0:
        patches.append(img[max(0, y0 - m):min(h, y1 + m), max(0, x0 - m):x0])
    # 右方
    if x1 + m <= w:
        patches.append(img[max(0, y0 - m):min(h, y1 + m), x1:min(w, x1 + m)])
    if not patches:
        return np.median(img.reshape(-1, 3), axis=0)
    combined = np.concatenate([p.reshape(-1, 3) for p in patches], axis=0)
    return np.median(combined, axis=0)


def _watermark_mask(roi: np.ndarray, bg_color: np.ndarray) -> np.ndarray:
    """生成水印 mask：与背景色三通道和差超过阈值的像素。"""
    dist = np.abs(roi.astype(np.int16) - bg_color).sum(axis=2)
    return (dist > WM_DIST).astype(np.uint8) * 255


def strip_watermark(path: Path) -> dict:
    """清除板图水印：多区域检测 + 纯色背景填充 + 清除后验证。

    对每个检测区域：采样区域外背景色 → 生成水印 mask → 用背景色填充 mask →
    全部区域处理完后重新检测计算残留率。

    返回 {"detected", "removed", "regions", "residual_ratio"}。
    removed=False 时不修改原文件，调用方应报错阻止 import。
    """
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        return {"detected": False, "removed": False, "regions": [], "residual_ratio": 0.0,
                "error": f"无法读取图片：{path}"}
    h, w = img.shape[:2]
    detected_regions = []
    any_detected = False

    for (rx0, ry0, rx1, ry1) in WM_REGIONS:
        x0, y0 = int(w * rx0), int(h * ry0)
        x1, y1 = int(w * rx1), int(h * ry1)
        if x1 <= x0 or y1 <= y0:
            continue
        roi = img[y0:y1, x0:x1]
        bg_color = _sample_background(img, x0, y0, x1, y1)
        mask = _watermark_mask(roi, bg_color)
        pixel_ratio = float((mask > 0).mean())
        pixel_count = int((mask > 0).sum())
        # 安全上限：非背景像素占比太高说明是实际内容，不是水印，跳过
        if pixel_ratio > WM_MAX_PIXEL_RATIO:
            continue
        if pixel_ratio < WM_MIN_PIXEL_RATIO and pixel_count < WM_MIN_PIXEL_COUNT:
            continue
        any_detected = True
        detected_regions.append({
            "region": [rx0, ry0, rx1, ry1],
            "pixel_ratio": round(pixel_ratio, 4),
            "pixel_count": pixel_count,
            "bg_color": [int(c) for c in bg_color],
        })
        # 检测到水印后，直接填充整个检测区域为背景色。
        # 白板/黑板场景的角落为纯色背景，无实际内容；整区填充比mask膨胀更彻底，
        # 能覆盖差<阈值的半透明边缘，避免淡痕残留。
        roi[:] = bg_color.astype(np.uint8)
        img[y0:y1, x0:x1] = roi

    if not any_detected:
        return {"detected": False, "removed": False, "regions": [], "residual_ratio": 0.0}

    # 第三层：清除后验证 — 重新检测所有区域，计算残留率
    total_residual = 0
    total_pixels = 0
    for (rx0, ry0, rx1, ry1) in WM_REGIONS:
        x0, y0 = int(w * rx0), int(h * ry0)
        x1, y1 = int(w * rx1), int(h * ry1)
        if x1 <= x0 or y1 <= y0:
            continue
        roi = img[y0:y1, x0:x1]
        bg_color = _sample_background(img, x0, y0, x1, y1)
        mask = _watermark_mask(roi, bg_color)
        total_residual += int((mask > 0).sum())
        total_pixels += roi.shape[0] * roi.shape[1]
    residual_ratio = total_residual / max(total_pixels, 1)
    removed = residual_ratio < WM_RESIDUAL_THRESHOLD

    if removed:
        cv2.imwrite(str(path), img)

    return {
        "detected": True,
        "removed": removed,
        "regions": detected_regions,
        "residual_ratio": round(residual_ratio, 4),
    }


# ---- 板图拥挤/重叠检测（基于 layout.json panels）----

CROWDING_IOU_THRESHOLD = 0.10   # 区域重叠率超过10%时警告
CROWDING_DENSITY_THRESHOLD = 0.55  # 区域总面积占比超过55%时警告（拥挤）


def _rect_iou(r1: dict, r2: dict) -> float:
    """计算两个矩形的 IoU（Intersection over Union）。
    rect 格式：{"x": int, "y": int, "width": int, "height": int}
    """
    x1 = max(r1["x"], r2["x"])
    y1 = max(r1["y"], r2["y"])
    x2 = min(r1["x"] + r1["width"], r2["x"] + r2["width"])
    y2 = min(r1["y"] + r1["height"], r2["y"] + r2["height"])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    area1 = r1["width"] * r1["height"]
    area2 = r2["width"] * r2["height"]
    union = area1 + area2 - inter
    return inter / max(union, 1)


def check_layout_crowding(layout_path: Path, scene_id: str) -> dict:
    """检查某幕的 layout.json 是否存在区域重叠或拥挤。
    返回 {"ok": bool, "errors": [], "warnings": [], "info": {}}
    """
    errors: list[str] = []
    warnings: list[str] = []
    info: dict = {}
    if not layout_path.exists():
        return {"ok": True, "errors": errors, "warnings": warnings,
                "info": {"note": "layout.json 不存在，跳过拥挤检测"}}
    try:
        doc = json.loads(layout_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"ok": False, "errors": [f"layout.json 解析失败：{e}"],
                "warnings": warnings, "info": {}}
    scene_layout = doc.get(scene_id, {})
    panels = scene_layout.get("panels", [])
    if not panels:
        return {"ok": True, "errors": errors, "warnings": warnings,
                "info": {"note": f"{scene_id} 无 panels，跳过拥挤检测"}}
    # 转换为标准 rect 格式
    rects = []
    for i, p in enumerate(panels):
        if isinstance(p, dict) and "x" in p and "y" in p:
            w = int(p.get("width", p.get("w", 0)))
            h = int(p.get("height", p.get("h", 0)))
            rects.append({"idx": i, "x": int(p["x"]), "y": int(p["y"]),
                          "width": w, "height": h})
        elif isinstance(p, (list, tuple)) and len(p) >= 4:
            rects.append({"idx": i, "x": int(p[0]), "y": int(p[1]),
                          "width": int(p[2]), "height": int(p[3])})
    info["panel_count"] = len(rects)
    # 重叠检测
    overlaps = []
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            iou = _rect_iou(rects[i], rects[j])
            if iou > CROWDING_IOU_THRESHOLD:
                overlaps.append((rects[i]["idx"], rects[j]["idx"], round(iou, 3)))
    if overlaps:
        for (i, j, iou) in overlaps:
            warnings.append(f"{scene_id}：panel-{i + 1} 与 panel-{j + 1} 重叠率 {iou:.1%} "
                            f"> {CROWDING_IOU_THRESHOLD:.0%}，建议调整 layout.json 分区位置")
    info["overlaps"] = overlaps
    # 拥挤检测：区域总面积占比
    canvas_w = scene_layout.get("canvasWidth", 1920)
    canvas_h = scene_layout.get("canvasHeight", 1080)
    total_area = sum(r["width"] * r["height"] for r in rects)
    density = total_area / max(canvas_w * canvas_h, 1)
    info["density"] = round(density, 3)
    if density > CROWDING_DENSITY_THRESHOLD:
        warnings.append(f"{scene_id}：区域总面积占比 {density:.1%} > {CROWDING_DENSITY_THRESHOLD:.0%}，"
                        f"板图可能过于拥挤，建议减少元素或扩大分区间距")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "info": info}
