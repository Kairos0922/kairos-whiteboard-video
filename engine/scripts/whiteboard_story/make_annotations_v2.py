#!/usr/bin/env python3
"""v2 标注生成器（P1 时间链闭环升级版）。

两条排程路径，按项目里是否存在 input/words.json 自动选择：

1) **词级排程（新主路径，engine-design §2/§5）**：直接吃 words.json 的
   scenes[i] 时间窗——幕窗口由逐幕音频实际时长累计得出（结构性精确）；
   - 版式层（region-0）吃片头固定值：LEAD_MS 起笔 + LAYOUT_MS 固定描版式；
   - 内容元素按「元素对应台词短语」在 words.json 该幕词序列里做规范化子串
     匹配（去空白与标点后比对）定位词级区间；attach_audio 的 sentence 粒度
     下 cue 条目透明地充当匹配单元（句级窗口替代词级区间使用）；
   - 找不到短语的元素退回锚点间空隙均分，并收集 warning（写明哪个幕哪个元素
     没匹配上），不伪造任何时间边界；
   - 幕尾部保留 TAIL_MS=600 凝视预留；本幕所有元素窗口收敛进
     [片头, 场景时长-TAIL_MS]，必要时段内等比压缩并打 warning；
   - **方案 A（ir-alignment §5 定论 A）**：带脚本时每个分区挂 `ops[]`
     （按句数把跨幕 Beat 的 reveal 序列切片后按序分配到揭示单元，每单元 ≤3 op）
     与 `protectedRegions`（先揭示分区的矩形，渲染不得复墨）。
2) **旧排程路径（向后兼容）**：无 words.json 时沿用 tts/durations.json +
   「版式 10% + 其余均分」，逻辑原样保留。

分区坐标读当期 input/layout.json（与 apply_layout 同源）。无文件时退回
模块级 SCENE_PANELS（测试可 patch）。脚本台词短语来自
input/script.json 的 scenes[i].elements[]（{"id":"panel-N","phrase":...}）。

用法：<python> make_annotations_v2.py --episode-dir <episode根目录>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 平铺导入兼容：直接执行（CLI）与被 whiteboard_story 包导入两种路径都成立。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_layout import SCENE_PANELS, H, W, load_scene_layout  # noqa: E402

LEAD_MS = 300          # 起笔缓冲
GAP_MS = 150           # 区域间隔
LAYOUT_SHARE = 0.10    # 版式层时长占比（仅旧路径）
TAIL_MS = 600          # 凝视预留：渲染器尾部强制补 ≥500ms 完整原图 + 帧取整余量
                       # （2026-08-23 修复：不预留则动画顶满全程，成片 -shortest 截尾砍内容）

# 词级路径新增常量（engine-design §2：版式吃片头固定值，内容跟词走）
LAYOUT_MS = 600        # 版式层固定描版时长（不再随幕长按比例伸缩）
MIN_ELEMENT_MS = 450   # 元素窗口下限（低于则告警「窗口过挤」）
MIN_FALLBACK_MS = 300  # 退回均分的元素保底时长

# Hook 机制（2026-09-05 新增）：如果第一个内容元素的开始时间过晚（旁白开头
# 没有锚短语），把它提前到 HOOK_START_MS 开始绘制，消除场景切换后的纯空白断裂。
# 画面提前入场不需要和旁白严格同步——hook 是视觉入场，旁白讲到时画面已在画。
HOOK_START_MS = 600     # hook 触发后第一个元素的开始时间
HOOK_MAX_DELAY_MS = 1200  # 第一个元素开始时间超过此值则触发 hook

_NORM_RE = re.compile(r"[\W_]+", re.UNICODE)
_PANEL_ID_RE = re.compile(r"^panel[-_]?(\d+)$", re.IGNORECASE)


def _normalize(text: str) -> str:
    """规范化：去全部空白与标点，只留字母/数字/CJK。"""
    return _NORM_RE.sub("", text or "")


# 句级切分（唯一权威口径；spans 派生与跨幕 Beat 的 ops 切片都用它）：
# 只在 。？！!? 处断句，逗号/冒号/分号不断；保留句末标点，拼接后仍等于原文。
_SENTENCE_RE = re.compile(r"[^。？！!?]+[。？！!?]?")


def split_sentences(narration: str) -> list[str]:
    parts = [m.group(0) for m in _SENTENCE_RE.finditer(narration or "")]
    return [p for p in parts if p.strip()]


def _sweep(x, y, w, h):
    """竖向扫一笔的 handPath（上→下）。"""
    return {"start": [x + w // 2, max(0, y - 60)], "end": [x + w // 2, y + h + 40]}


# ================================================================ 旧路径（兼容保留）

def _panels(scene_id: str, episode_dir: Path | None = None) -> list:
    return load_scene_layout(scene_id, episode_dir)["panels"]


def build_annotation(scene_id: str, duration_ms: int,
                     episode_dir: Path | None = None) -> dict:
    """旧排程：版式占前 10%，其余均分给内容区域（留间隔）。"""
    panels = _panels(scene_id, episode_dir)
    n_content = max(1, len(panels))
    layout_ms = int(duration_ms * LAYOUT_SHARE)
    rest = duration_ms - layout_ms - LEAD_MS - GAP_MS * n_content - TAIL_MS
    per = max(800, rest // n_content)

    elements = [{
        "id": "layout", "sequence": 0,
        "region": {"x": 0, "y": 0, "width": W, "height": H},
        "reveal": {"startMs": LEAD_MS, "durationMs": layout_ms, "protectedRegions": []},
        "handPath": {"start": [W // 2, 40], "end": [W // 2, H - 40]},
        "kind": "layout",
    }]
    t = LEAD_MS + layout_ms + GAP_MS
    for idx, (_, x, y, w, h, _c) in enumerate(panels, start=1):
        elements.append({
            "id": f"panel-{idx}", "sequence": idx,
            "region": {"x": x + 14, "y": y + 14, "width": w - 28, "height": h - 28},
            "reveal": {"startMs": t, "durationMs": per, "protectedRegions": []},
            "handPath": _sweep(x, y, w, h),
            "kind": "panel",
        })
        t += per + GAP_MS
    return {"canvas": {"width": W, "height": H},
            "sceneDurationMs": duration_ms, "elements": elements}


# ================================================================ 词级路径

def _word_units(words_doc: dict, scene_index: int) -> list[dict]:
    """该幕的词级/句级单元（attach_audio sentence 粒度的 cue 也在这里统一处理）。"""
    return [w for w in words_doc.get("words", [])
            if int(w.get("scene_index", -1)) == scene_index]


def _levenshtein_ratio(a: str, b: str) -> float:
    """编辑距离相似度：1 - dist/max(len(a), len(b))。"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    la, lb = len(a), len(b)
    if la < lb:
        a, b = b, a
        la, lb = lb, la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return 1.0 - prev[lb] / max(la, lb)


FUZZY_THRESHOLD = 0.75  # 模糊匹配相似度阈值


# ---- 跨语言短语匹配词典（技术/设计领域常用英文-中文对照）----
# phrase 是英文但旁白是中文时，用词典翻译后再匹配。
# 覆盖白板讲解视频常见的技术/设计术语。
CROSS_LANG_DICT = {
    # 三阶段流程
    "discover": ["探索", "发现", "发散"],
    "define": ["深化", "定义", "聚焦"],
    "deliver": ["打磨", "交付", "执行"],
    # AI/技术术语
    "ai": ["人工智能", "AI"],
    "llm": ["大语言模型", "大模型"],
    "gpt": ["GPT"],
    "agent": ["代理", "智能体"],
    "prompt": ["提示词", "提示"],
    "token": ["词元", "token"],
    "next-token": ["下一个词", "下一个词元", "逐词预测"],
    "next token": ["下一个词", "下一个词元", "逐词预测"],
    # 设计术语
    "design": ["设计"],
    "designer": ["设计师"],
    "world-class": ["世界级", "一流"],
    "world class": ["世界级", "一流"],
    "gradient": ["渐变"],
    "purple gradient": ["紫色渐变"],
    "ui": ["界面", "UI"],
    "ux": ["体验", "UX"],
    "prototype": ["原型", "草图"],
    "wireframe": ["线框", "线框图"],
    # 代理/流程
    "critic": ["批评家", "批评", "评审"],
    "critic agent": ["批评家代理", "批评代理"],
    "executor": ["执行者", "执行"],
    "executor agent": ["执行者代理", "执行代理"],
    "iteration": ["迭代", "反复"],
    "workflow": ["流程", "工作流"],
    "process": ["流程", "过程"],
    # 质量/效果
    "quality": ["质量", "品质"],
    "boring": ["平庸", "无聊", "普通"],
    "amazing": ["惊艳", "出色", " amazing"],
    "mediocre": ["平庸", "普通"],
    "generic": ["通用", "千篇一律", "普通"],
    "safe": ["安全", "保守"],
    "safest": ["最安全", "最保守"],
    "creative": ["创意", "创造性"],
    "diverse": ["多样", "多样化"],
    "variety": ["多样", "变化"],
    # 其他常用
    "potential": ["潜力", "潜能"],
    "99%": ["99%", "百分之九十九"],
    "1%": ["1%", "百分之一"],
    "video": ["视频"],
    "animation": ["动画", "动效"],
    "motion": ["动效", "动态"],
    "subtract": ["减法", "做减法", "减去"],
    "simplify": ["简化", "精简"],
    "clutter": ["凌乱", "杂乱", "拥挤"],
    "clean": ["简洁", "干净", "清爽"],
    "minimal": ["极简", "简约"],
    "white space": ["留白", "空白"],
    "archive": ["存档", "归档"],
    "sketch": ["草图", "草稿"],
    "exploration": ["探索", "发散"],
    "bold": ["大胆", "醒目"],
    "random": ["随机", "随意"],
    "seed": ["种子", "随机种子"],
}


def _translate_phrase(phrase: str) -> list[str]:
    """把英文 phrase 翻译成中文候选词列表。返回空列表表示无需翻译。"""
    normalized = phrase.strip().lower()
    if normalized in CROSS_LANG_DICT:
        return CROSS_LANG_DICT[normalized]
    # 尝试部分匹配（短语包含词典中的词）
    for key, translations in CROSS_LANG_DICT.items():
        if key in normalized and key != normalized:
            return translations
    return []


def _match_phrase_span(units: list[dict], phrase: str) -> tuple[int, int, bool] | None:
    """规范化子串匹配：返回 (首单元下标, 末单元下标, 是否模糊匹配)；找不到返回 None。

    把该幕各单元文本拼成规范化长串并记录每字符→单元的下标映射，
    短语命中处即映射回词级区间——只认真实语音边界，不做比例折算。
    精确匹配失败时降级为滑动窗口模糊匹配（编辑距离相似度 ≥ FUZZY_THRESHOLD）。
    支持跨语言匹配：英文 phrase 先用词典翻译为中文，再匹配中文旁白。
    """
    hay_parts: list[str] = []
    char_unit: list[int] = []
    for i, u in enumerate(units):
        n = _normalize(u.get("text", ""))
        for ch in n:
            hay_parts.append(ch)
            char_unit.append(i)
    if not hay_parts:
        return None
    hay = "".join(hay_parts)
    needle = _normalize(phrase)
    if not needle:
        return None

    # 收集所有需要尝试的 needle：原文 + 跨语言翻译
    needles_to_try = [needle]
    translations = _translate_phrase(phrase)
    for t in translations:
        t_norm = _normalize(t)
        if t_norm and t_norm not in needles_to_try:
            needles_to_try.append(t_norm)

    # 对每个 needle 尝试精确匹配和模糊匹配
    for n_idx, current_needle in enumerate(needles_to_try):
        is_translation = n_idx > 0
        # 精确匹配
        pos = hay.find(current_needle)
        if pos >= 0:
            first = char_unit[pos]
            last = char_unit[pos + len(current_needle) - 1]
            return (int(units[first]["start_ms"]), int(units[last]["end_ms"]), is_translation)
        # 模糊匹配：滑动窗口找最相似的连续字符段
        best_pos = -1
        best_ratio = 0.0
        nlen = len(current_needle)
        # 窗口大小在 0.5x ~ 1.5x needle 长度之间搜索
        for win_len in range(max(1, int(nlen * 0.5)), min(len(hay), int(nlen * 1.5)) + 1):
            for start in range(0, len(hay) - win_len + 1):
                window = hay[start:start + win_len]
                ratio = _levenshtein_ratio(current_needle, window)
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_pos = start
        if best_pos >= 0 and best_ratio >= FUZZY_THRESHOLD:
            first = char_unit[best_pos]
            # 找到窗口末尾对应的单元
            end_pos = min(best_pos + max(1, int(nlen * 1.5)) - 1, len(char_unit) - 1)
            last = char_unit[end_pos]
            return (int(units[first]["start_ms"]), int(units[last]["end_ms"]), True)
    return None


def _place_fallback_run(count: int, lo: int, hi: int, warnings: list[str],
                        scene_id: str, ctx: str) -> list[tuple[int, int]]:
    """在 [lo,hi] 里给 count 个退回元素均分窗口（留 GAP）。空间不足时压缩并告警。"""
    out: list[tuple[int, int]] = []
    if count <= 0:
        return out
    usable = hi - lo - GAP_MS * (count - 1)
    per = usable // count if count else 0
    if per < MIN_FALLBACK_MS:
        warnings.append(f"{scene_id}：「{ctx}」段剩余空间 {usable}ms 不足以均分 "
                        f"{count} 个退回元素（每个 < {MIN_FALLBACK_MS}ms），已压缩")
        per = max(120, usable // count)
    t = lo
    for _ in range(count):
        e = min(t + per, hi)
        out.append((t, max(e, t + 120)))
        t += per + GAP_MS
        if t >= hi:
            break
    return out


def schedule_windows(scene_id: str, duration_ms: int,
                     raw_spans: list[tuple[int, int] | None],
                     warnings: list[str]) -> list[tuple[int, int]]:
    """把各内容元素的原始词级跨度（None=退回均分）编排为幕内不重叠有序窗口。

    - 全部窗口约束在 [LEAD_MS+LAYOUT_MS+GAP_MS, duration_ms-TAIL_MS]；
    - 锚点元素按真实语音位置落位，顺序冲突时顺次后移（视觉顺序=讲解顺序）；
    - 锚点之间/之外的空隙留给退回元素均分；
    - 总体越界（最后一个锚点越过 tail 线）时整体等比压缩回界内并告警。
    """
    area_start = LEAD_MS + LAYOUT_MS + GAP_MS
    area_end = max(area_start + MIN_ELEMENT_MS, duration_ms - TAIL_MS)
    n = len(raw_spans)
    out: list[tuple[int, int] | None] = [None] * n

    # 1) 正向落锚点：位置取真实词级边界，但保证有序与最小窗
    prev_end = area_start - GAP_MS
    anchor_seq: list[int] = []
    for i, span in enumerate(raw_spans):
        if span is None:
            continue
        rs, re = span
        s = max(rs, prev_end + GAP_MS, area_start)
        s = min(s, area_end - MIN_ELEMENT_MS)   # 单元素至少要在界内放下
        e = max(re, s + MIN_ELEMENT_MS)
        e = min(e, area_end)
        out[i] = (s, max(e, s + MIN_ELEMENT_MS))
        prev_end = out[i][1]
        anchor_seq.append(i)

    # 2) 尾部越界的整体压缩：保持相对几何，线性映射回首锚点起点的可用区
    placed = [(i, out[i]) for i in anchor_seq]
    if placed and placed[-1][1][1] > area_end:
        first_s = placed[0][1][0]
        overflow_end = placed[-1][1][1]
        room = area_end - first_s
        scale = room / max(1, overflow_end - first_s)
        warnings.append(f"{scene_id}：词级锚点总跨度超出预留区 {overflow_end - area_end}ms，"
                        f"已等比压缩 ×{scale:.2f}（检查 LAYOUT_MS/TAIL_MS 或分镜密度）")
        cur_s = first_s
        for k, (i, (s, e)) in enumerate(placed):
            ns = cur_s
            ne = min(area_end, ns + max(MIN_ELEMENT_MS, int((e - s) * scale)))
            out[i] = (ns, ne)
            cur_s = ne + GAP_MS

    # 3) 空隙分配给退回元素（前后锚点之间、首个锚点之前、最后锚点之后）
    cursor_lo = area_start
    fb_start = 0
    for i in range(n):
        if out[i] is None:
            continue
        fb_idx = list(range(fb_start, i))
        gap_end = out[i][0] - GAP_MS
        got = _place_fallback_run(len(fb_idx), min(cursor_lo, gap_end),
                                  gap_end, warnings, scene_id, f"panel-{fb_start + 1}-{i}")
        for j, win in zip(fb_idx, got):
            out[j] = win
        fb_start = i + 1
        cursor_lo = out[i][1] + GAP_MS
    # 尾部剩余退回元素
    tail_fb = list(range(fb_start, n))
    if tail_fb:
        got = _place_fallback_run(len(tail_fb), min(cursor_lo, area_end),
                                  area_end, warnings, scene_id, f"尾部 panel-{tail_fb[0] + 1}-{n}")
        for j, win in zip(tail_fb, got):
            out[j] = win

    final: list[tuple[int, int]] = []
    for i in range(n):
        if out[i] is None:                    # 极端情况兜底：挤到 tail 前
            base = area_end - MIN_FALLBACK_MS
            out[i] = (base, area_end)
            warnings.append(f"{scene_id}：元素 panel-{i + 1} 无处安放，已压至尾区")
        final.append(out[i])

    # Hook 机制：如果第一个内容元素开始过晚（旁白开头无锚短语），提前到 HOOK_START_MS
    # 开始绘制，消除场景切换后的纯空白断裂。延长 duration 保持结束时间不变。
    if final and final[0][0] > HOOK_MAX_DELAY_MS:
        old_s, old_e = final[0]
        new_s = max(HOOK_START_MS, area_start)
        final[0] = (new_s, old_e)
        warnings.append(f"{scene_id}：首元素开始 {old_s}ms > {HOOK_MAX_DELAY_MS}ms，"
                        f"触发 hook 提前至 {new_s}ms（消除开场空白）")

    return final


# ================================================================ 揭示单元 ops（ir-alignment §5 定论 A）

def _beat_scene_slices(beat: dict, owner_id: str) -> list[str]:
    sl = beat.get("scene_slice")
    return [str(s) for s in sl] if sl else [owner_id]


def _scene_reveal_ops(doc: dict, scene_id: str, warnings: list[str]) -> list[dict]:
    """按序拼接落在本幕的 reveal ops。

    跨幕 Beat 的 reveal 序列按句数切片：各 slice 幕把自己的旁白按句切分，
    Beat 的 spans 依次分段，本幕取 bound_span 落在自己段内的 reveal 项；
    某 slice 幕旁白切不出句子时，整条序列归 Beat 所属幕（记 warning）。
    """
    scenes = doc.get("scenes", []) if isinstance(doc, dict) else []
    narration_by_id = {str(sc.get("id")): sc.get("narration", "") for sc in scenes}
    out: list[dict] = []
    for sc in scenes:
        owner = str(sc.get("id"))
        for beat in sc.get("beats") or []:
            if not isinstance(beat, dict):
                continue
            reveal = beat.get("reveal") or []
            slices = _beat_scene_slices(beat, owner)
            if scene_id not in slices:
                continue
            if len(slices) == 1:
                out.extend(rv for rv in reveal if isinstance(rv, dict))
                continue
            cursor, taken, broken = 0, None, False
            for sl in slices:
                k = len(split_sentences(narration_by_id.get(sl, "")))
                if k == 0:
                    warnings.append(f"{scene_id}：Beat {beat.get('id')} 的 slice 幕 {sl} "
                                    f"无旁白可切句，reveal ops 全归 Beat 所属幕")
                    broken = True
                    break
                if sl == scene_id:
                    taken = (cursor, cursor + k)
                cursor += k
            if broken:
                if owner == scene_id:
                    out.extend(rv for rv in reveal if isinstance(rv, dict))
                continue
            if taken is None:
                continue
            lo, hi = taken
            out.extend(dict(rv, bound_span=rv["bound_span"] - lo) for rv in reveal
                       if isinstance(rv, dict) and isinstance(rv.get("bound_span"), int)
                       and lo <= rv["bound_span"] < hi)
    return out


def _assign_ops_to_panels(scene_ops: list[dict], n_panels: int,
                          warnings: list[str], scene_id: str) -> list[list[dict]]:
    """把本幕 ops 按顺序分给各分区（揭示单元）。

    数量相等时一一对应；不等时按序均分（每单元 >3 个 op 记 warning，
    违反方案 A 口径但不阻断）；无 ops 时返回等长空表。
    """
    if n_panels <= 0:
        return []
    if not scene_ops:
        return [[] for _ in range(n_panels)]
    if len(scene_ops) == n_panels:
        return [[op] for op in scene_ops]
    out: list[list[dict]] = [[] for _ in range(n_panels)]
    base, extra = divmod(len(scene_ops), n_panels)
    idx = 0
    for i in range(n_panels):
        cnt = base + (1 if i < extra else 0)
        out[i] = scene_ops[idx:idx + cnt]
        idx += cnt
    if any(len(g) > 3 for g in out):
        warnings.append(f"{scene_id}：存在分区 ops 多于 3，违反方案 A 单元口径（ir-alignment §5）")
    return out


def build_annotation_words(scene_id: str, duration_ms: int,
                           script_elements: list[dict],
                           units: list[dict],
                           warnings: list[str],
                           scene_window: dict,
                           granularity: str = "word",
                           episode_dir: Path | None = None,
                           script_doc: dict | None = None,
                           sentence_spans: list[tuple[int, int]] | None = None) -> dict:
    """词级排程单幕标注。

    script_elements: input/script.json 该幕 elements[]（id=panel-N + phrase/text）。
    scene_window: words.json 里本幕 {"start_ms","end_ms"}（全局坐标，用于换算局窗）。
    script_doc: 完整 script.json；提供时按方案 A（ir-alignment §5）给每个分区挂
    `ops[]`（揭示单元内的离散操作）与 `protectedRegions`（先揭示分区，渲染不得复墨）。
    sentence_spans: 本幕句级边界（局窗坐标，与 ops 的 bound_span 同序）；有 ops 的分区
    其揭示窗 = 所绑句子边界之并集（画面跟着整句走，而不是锚短语的几个词，P2）。
    返回 annotation dict；匹配失败逐项写入 warnings。
    """
    panels = _panels(scene_id, episode_dir)
    # 台词短语表：panel 序号 → 短语文本
    phrase_by_panel: dict[int, str] = {}
    unnamed: list[str] = []
    for el in script_elements:
        text = el.get("phrase") or el.get("text") or ""
        if not text:
            continue
        m = _PANEL_ID_RE.match(str(el.get("id", "")))
        if m:
            phrase_by_panel[int(m.group(1))] = text
        else:
            unnamed.append(text)

    n_panels = len(panels)
    panels_ops = _assign_ops_to_panels(
        _scene_reveal_ops(script_doc, scene_id, warnings) if script_doc else [],
        n_panels, warnings, scene_id)

    spans: list[tuple[int, int] | None] = []
    matched_cnt = 0
    for idx in range(n_panels):
        pno = idx + 1
        span: tuple[int, int] | None = None
        ops = panels_ops[idx] if idx < len(panels_ops) else []
        if ops and sentence_spans:
            idxs = [int(op["bound_span"]) for op in ops
                    if isinstance(op.get("bound_span"), int)
                    and 0 <= op["bound_span"] < len(sentence_spans)]
            if idxs:
                span = (min(sentence_spans[i][0] for i in idxs),
                        max(sentence_spans[i][1] for i in idxs))
        if span is not None:
            spans.append(span)
            matched_cnt += 1
            continue
        phrase = phrase_by_panel.get(pno)
        mspan = _match_phrase_span(units, phrase) if phrase else None
        if mspan is None:
            # 详细诊断：列出该幕前10个词，方便用户修正 script.json 的短语
            word_preview = "、".join(u.get("text", "") for u in units[:10])
            if len(units) > 10:
                word_preview += "..."
            why = (f"panel-{pno}" +
                   (f"（短语「{phrase}」未在该幕台词命中，该幕词预览：{word_preview}）"
                    if phrase else "（脚本未提供对应短语）"))
            warnings.append(f"{scene_id}：{why} → 退回区内均分")
            spans.append(None)
        else:
            start_ms, end_ms, is_fuzzy = mspan
            if is_fuzzy:
                warnings.append(f"{scene_id}：panel-{pno} 短语「{phrase}」精确匹配失败，"
                                f"已用模糊匹配（相似度≥{FUZZY_THRESHOLD}）定位，建议核对 script.json 短语准确性")
            # 词级坐标是全局 ms，转回幕内局部坐标
            local_s = start_ms - int(scene_window["start_ms"])
            local_e = end_ms - int(scene_window["start_ms"])
            spans.append((max(0, local_s), max(0, local_e)))
            matched_cnt += 1
    scheduled = schedule_windows(scene_id, duration_ms, spans, warnings)

    elements = [{
        "id": "layout", "sequence": 0,
        "region": {"x": 0, "y": 0, "width": W, "height": H},
        "reveal": {"startMs": LEAD_MS, "durationMs": LAYOUT_MS, "protectedRegions": []},
        "handPath": {"start": [W // 2, 40], "end": [W // 2, H - 40]},
        "kind": "layout",
    }]
    for idx, ((_name, x, y, w, h, _c), (s, e)) in enumerate(zip(panels, scheduled), start=1):
        region = {"x": x + 14, "y": y + 14, "width": w - 28, "height": h - 28}
        # 保护区 = 先于本分区揭示的各分区（已上墨的区域不得复画；版式层不算）。
        # 仅在带脚本的新链路上启用；无脚本的兼容路径保持旧形状。
        protected = ([dict(el["region"]) for el in elements
                      if el.get("kind") == "panel" and el["sequence"] < idx]
                     if script_doc is not None else [])
        el_out = {
            "id": f"panel-{idx}", "sequence": idx,
            "region": region,
            "reveal": {"startMs": s, "durationMs": e - s, "protectedRegions": protected},
            "handPath": _sweep(x, y, w, h),
            "kind": "panel",
        }
        ops = panels_ops[idx - 1] if idx - 1 < len(panels_ops) else []
        if ops:
            el_out["ops"] = [{"op": rv.get("op"), "target": rv.get("target"),
                              "bound_span": rv.get("bound_span")} for rv in ops]
        elements.append(el_out)
    return {"canvas": {"width": W, "height": H},
            "sceneDurationMs": duration_ms, "elements": elements,
            "meta": {"schedule": "words",
                     "granularity": granularity,
                     "matched": f"{matched_cnt}/{n_panels}",
                     "warnings": warnings}}


def run_words_mode(ep: Path, out_dir: Path) -> int:
    """有 input/words.json 时的新主路径。返回退出码。"""
    words_doc = json.loads((ep / "input" / "words.json").read_text(encoding="utf-8"))
    script_path = ep / "input" / "script.json"
    script_doc: dict | None = None
    script_scenes: list[dict] = []
    if script_path.exists():
        script_doc = json.loads(script_path.read_text(encoding="utf-8"))
        script_scenes = script_doc.get("scenes", [])
    granularity = words_doc.get("granularity", "word")

    out_dir.mkdir(parents=True, exist_ok=True)
    all_warnings: list[str] = []
    ok = True
    for sc_win in words_doc.get("scenes", []):
        idx = int(sc_win["scene_index"])
        sid = (script_scenes[idx]["id"] if idx < len(script_scenes)
               and script_scenes[idx].get("id") else f"scene-{idx + 1:02d}")
        duration_ms = int(sc_win["end_ms"]) - int(sc_win["start_ms"])
        if duration_ms <= TAIL_MS + LEAD_MS + LAYOUT_MS:
            all_warnings.append(f"{sid}：幕音频窗 {duration_ms}ms 过短，不足以承载片头+尾部预留")
            ok = False
        warnings: list[str] = []
        script_els = (script_scenes[idx].get("elements", [])
                      if idx < len(script_scenes) else [])
        if not script_els:
            warnings.append(f"{sid}：脚本无 elements[] 短语表，全幕退回均分")
        # 句级边界（方案 A 的揭示窗口口径）：与 ops 的 bound_span 同序
        import spans as spans_mod
        narration = (script_scenes[idx].get("narration", "")
                     if idx < len(script_scenes) else "")
        sentence_spans = None
        if narration:
            start0 = int(sc_win["start_ms"])
            sentence_spans = [(s["start_ms"] - start0, s["end_ms"] - start0)
                              for s in spans_mod.derive_scene_spans(
                                  _word_units(words_doc, idx), narration, warnings, sid)]
        ann = build_annotation_words(sid, duration_ms, script_els,
                                     _word_units(words_doc, idx), warnings,
                                     scene_window=sc_win, granularity=granularity,
                                     episode_dir=ep, script_doc=script_doc,
                                     sentence_spans=sentence_spans)
        p = out_dir / f"{sid}.annotation.json"
        p.write_text(json.dumps(ann, ensure_ascii=False, indent=2), encoding="utf-8")
        all_warnings.extend(warnings)
        print(f"OK {p}  {len(ann['elements'])} elements  window={sc_win['start_ms']}"
              f"-{sc_win['end_ms']}ms ({duration_ms}ms)  matched={ann['meta']['matched']}")
    for wmsg in all_warnings:
        print(f"  ! {wmsg}")
    fallback_warnings = [w for w in all_warnings if "退回区内均分" in w]
    if fallback_warnings:
        print(f"✗ annotation blocked: {len(fallback_warnings)} 个元素未能绑定真实语音锚点")
        return 1
    return 0 if ok else 1


def _ensure_layout_json(ep: Path) -> None:
    """确保 input/layout.json 存在；不存在时根据 script.json 的 elements 数量自动生成默认布局。

    layout.json 是 annotation 生成器的必需输入——panels 为空会导致 matched=0/0，
    进而导致渲染失败"零绘制任务"。自动生成默认布局，避免手动创建遗漏。
    """
    layout_path = ep / "input" / "layout.json"
    if layout_path.exists():
        return

    script_path = ep / "input" / "script.json"
    if not script_path.exists():
        print(f"  ! 无 script.json，跳过 layout.json 自动生成")
        return

    doc = json.loads(script_path.read_text(encoding="utf-8"))
    scenes = doc.get("scenes", [])
    if not scenes:
        print(f"  ! script.json 无 scenes，跳过 layout.json 自动生成")
        return

    W, H = 1920, 1080
    MARGIN = 60
    GAP = 40

    def _grid_layout(n: int) -> list[dict]:
        """根据 elements 数量生成不重叠的网格布局。"""
        if n <= 1:
            return [{"x": MARGIN, "y": MARGIN, "w": W - 2*MARGIN, "h": H - 2*MARGIN, "color": "blue"}]
        if n == 2:
            w = (W - 2*MARGIN - GAP) // 2
            h = H - 2*MARGIN
            return [
                {"x": MARGIN, "y": MARGIN, "w": w, "h": h, "color": "blue"},
                {"x": MARGIN + w + GAP, "y": MARGIN, "w": w, "h": h, "color": "orange"},
            ]
        if n == 3:
            w_top = W - 2*MARGIN
            h_top = (H - 2*MARGIN - GAP) // 2
            w_bottom = (w_top - GAP) // 2
            return [
                {"x": MARGIN, "y": MARGIN, "w": w_top, "h": h_top, "color": "blue"},
                {"x": MARGIN, "y": MARGIN + h_top + GAP, "w": w_bottom, "h": h_top, "color": "orange"},
                {"x": MARGIN + w_bottom + GAP, "y": MARGIN + h_top + GAP, "w": w_bottom, "h": h_top, "color": "red"},
            ]
        # n >= 4: 2x2 网格（前4个），多余的堆叠在底部
        cols = 2
        rows = (n + cols - 1) // cols
        w = (W - 2*MARGIN - (cols-1)*GAP) // cols
        h = (H - 2*MARGIN - (rows-1)*GAP) // rows
        colors = ["blue", "orange", "red", "green", "purple"]
        panels = []
        for i in range(n):
            r, c = divmod(i, cols)
            panels.append({
                "x": MARGIN + c*(w+GAP),
                "y": MARGIN + r*(h+GAP),
                "w": w, "h": h,
                "color": colors[i % len(colors)],
            })
        return panels

    layout = {}
    for i, sc in enumerate(scenes):
        sid = sc.get("id") or f"scene-{i+1:02d}"
        n_elements = len(sc.get("elements", []))
        if n_elements <= 0:
            raise ValueError(f"{sid} 没有 elements[]：无法建立可验证的绘制区域")
        layout[sid] = {"panels": _grid_layout(n_elements)}

    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ 自动生成 layout.json（{len(layout)} 幕，默认网格布局）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode-dir", required=True, type=Path)
    args = ap.parse_args()
    ep = args.episode_dir
    out_dir = ep / "build" / "annotations"

    # 确保 layout.json 存在（不存在时自动生成默认布局）
    _ensure_layout_json(ep)

    if (ep / "input" / "words.json").exists():
        return run_words_mode(ep, out_dir)

    # ---- 向后兼容：旧路径（tts/durations.json + 版式10%均分）----
    durations = json.loads((ep / "tts" / "durations.json").read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    for sid in sorted(durations):
        if not sid.startswith("scene-"):
            continue
        ann = build_annotation(sid, int(durations[sid] * 1000), episode_dir=ep)
        p = out_dir / f"{sid}.annotation.json"
        p.write_text(json.dumps(ann, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"OK {p}  {len(ann['elements'])} elements, {ann['sceneDurationMs']}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
