#!/usr/bin/env python3
"""validate.py — 交付前闸门（engine-design §7，P1 最小集）。

只拦「无法交付」的问题（阻断级），其余降为 warning 由人决定：

阻断：
  1. deliverables/final.mp4 存在且 ffprobe 读得出时长（含视频流）；
  2. 配置了旁白（input/narration.mp3 存在）则成片必须有音轨；
  3. 口播三件套齐全：input/narration.mp3 + captions.srt + words.json；
  4. annotations 覆盖所有幕（以 words.json scenes[] 为幕真值）；
  5. 口播指纹复核：与 state.json["voice_fingerprints"] 记录的三件套 sha256
     比对，不一致列明细并阻断（挂接约定见 providers/voice.py 模块注释；
     尚无记录报 warning——从未确认过就谈不上「变了」）。

警告：
  a. 成片时长与旁白时长偏差 > 2s；
  b. 底部字幕带亮度冲突（收编 review_images.check_board 的字幕带告警，
     跑在 boards-layout 图上；该检查本属板图自动审核，validate 只汇总提醒）。

产出：markdown 报告落 build/review/validate-report.md。
退出码：有阻断=1，否则 0。

用法：<python> validate.py --episode-dir <episode根目录>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from providers.voice import FINGERPRINT_FILES, sha256_file  # noqa: E402

FINAL_MP4 = Path("deliverables/final.mp4")
MAX_DURATION_DRIFT_MS = 2000


def _ffprobe(path: Path, entries: str) -> str:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entries,
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def probe_duration_ms(path: Path) -> int | None:
    out = _ffprobe(path, "format=duration")
    try:
        return int(round(float(out.splitlines()[0]) * 1000))
    except (IndexError, ValueError):
        return None


def _ffprobe_select(path: Path, kind: str) -> str:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", kind,
         "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return r.stdout.strip()


def _resolve_theme_dir(ep: Path, state_doc: dict | None) -> Path | None:
    """统一解析主题目录：state.json theme > script.json theme > None。

    路径解析：绝对路径直接用；相对路径相对于项目根目录（engine/..）。
    修复原逻辑：ep.name == "input" 永远为 false，且 ep.parent.parent 路径错误。
    """
    candidates = []
    # 1. state.json theme
    if state_doc and isinstance(state_doc, dict):
        theme_val = state_doc.get("theme")
        if theme_val:
            candidates.append(str(theme_val))
    # 2. script.json theme
    script_path = ep / "input" / "script.json"
    if script_path.exists():
        try:
            rel = json.loads(script_path.read_text(encoding="utf-8")).get("theme")
            if rel:
                candidates.append(str(rel))
        except (OSError, json.JSONDecodeError):
            pass
    # 项目根目录：engine/scripts/whiteboard_story/ → 上溯3级到项目根
    project_root = Path(__file__).resolve().parents[3]
    for cand in candidates:
        p = Path(cand)
        if p.is_absolute():
            if p.exists():
                return p
            continue
        # 1. 先相对于 episode_dir 解析（state.json 中的相对路径通常相对于项目目录）
        rel_ep = (ep / p).resolve()
        if rel_ep.exists():
            return rel_ep if rel_ep.is_dir() else rel_ep.parent
        # 2. 再相对于项目根解析（script.json 中的相对路径可能相对于项目根）
        rel_root = (project_root / p).resolve()
        if rel_root.exists():
            return rel_root if rel_root.is_dir() else rel_root.parent
    return None


def validate(episode_dir: Path) -> tuple[list[str], list[str], dict]:
    """跑全部检查。返回 (blockers, warnings, info)。"""
    ep = Path(episode_dir)
    blockers: list[str] = []
    warnings: list[str] = []
    info: dict = {}

    inp = ep / "input"

    # 加载 state.json（供主题解析和确认状态检查使用）
    state_doc = None
    state_path = ep / "state.json"
    if state_path.exists():
        try:
            state_doc = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    # 统一解析主题目录（多主题支持：黑板/白纸）
    theme_dir = _resolve_theme_dir(ep, state_doc)
    info["theme_dir"] = str(theme_dir) if theme_dir else None

    # ---- 3. 三件套存在性 ----
    trio = {}
    for name in FINGERPRINT_FILES:
        p = inp / name
        trio[name] = p.exists()
        if not p.exists():
            blockers.append(f"口播三件套缺文件：input/{name}"
                            + ("（先跑 providers/voice.make_voice 或 attach_audio）"
                               if name == "narration.mp3" else ""))
    info["trio"] = trio

    # 幕真值：words.json 的 scenes[]（三件套缺失时退化为脚本幕数）
    scene_ids: list[str] = []
    words_doc = {}
    if trio["words.json"]:
        try:
            words_doc = json.loads((inp / "words.json").read_text(encoding="utf-8"))
            scene_ids = [f"scene-{int(s['scene_index']) + 1:02d}"
                         for s in sorted(words_doc.get("scenes", []),
                                         key=lambda x: x["scene_index"])]
            info["granularity"] = words_doc.get("granularity", "word")
            info["word_count"] = len(words_doc.get("words", []))
        except (json.JSONDecodeError, KeyError) as e:
            blockers.append(f"input/words.json 解析失败：{e}")
    if not scene_ids and (ep / "input/script.json").exists():
        try:
            doc = json.loads((ep / "input/script.json").read_text(encoding="utf-8"))
            scene_ids = [sc.get("id") or f"scene-{i + 1:02d}"
                         for i, sc in enumerate(doc.get("scenes", []))]
        except (json.JSONDecodeError, IndexError):
            pass
    info["scenes"] = scene_ids

    # ---- 1/2. 成片存在性、时长、音轨 ----
    final_path = ep / FINAL_MP4
    has_final = final_path.exists()
    info["final_exists"] = has_final
    duration_ms: int | None = None
    if not has_final:
        blockers.append(f"缺少成片：{FINAL_MP4}（未合成或被移动）")
    else:
        duration_ms = probe_duration_ms(final_path)
        info["final_duration_ms"] = duration_ms
        has_v, has_a = False, False
        if duration_ms is None or duration_ms <= 0:
            blockers.append(f"{FINAL_MP4} 无有效时长（损坏或空文件）")
        else:
            has_v = bool(_ffprobe_select(final_path, "v"))
            has_a = bool(_ffprobe_select(final_path, "a"))
            if not has_v:
                blockers.append(f"{FINAL_MP4} 缺视频轨")
        # 配置了旁白（narration.mp3 在）则必须有音轨
        if trio["narration.mp3"]:
            if not has_a:
                blockers.append(f"{FINAL_MP4} 配置了旁白但没有音轨")
            elif duration_ms:
                narr_ms = probe_duration_ms(inp / "narration.mp3")
                drift = abs(duration_ms - (narr_ms or 0))
                info["narration_duration_ms"] = narr_ms
                info["drift_ms"] = drift
                if narr_ms and drift > MAX_DURATION_DRIFT_MS:
                    warnings.append(
                        f"成片 {duration_ms}ms 与旁白 {narr_ms}ms 偏差 {drift}ms "
                        f"> {MAX_DURATION_DRIFT_MS}ms（画面/声音可能错位或截尾）")

    # ---- 4. annotations 覆盖所有幕 ----
    ann_missing: list[str] = []
    for sid in scene_ids:
        apath = ep / "build" / "annotations" / f"{sid}.annotation.json"
        if not apath.exists():
            ann_missing.append(sid)
            continue
        try:
            ann = json.loads(apath.read_text(encoding="utf-8"))
            n_el = len(ann.get("elements", []))
            if n_el == 0 or not ann.get("sceneDurationMs"):
                blockers.append(f"{sid} 标注为空或缺 sceneDurationMs：{apath.name}")
                ann_missing.append(sid)
        except json.JSONDecodeError as e:
            blockers.append(f"{sid} 标注解析失败：{e}")
            ann_missing.append(sid)
    if ann_missing and scene_ids:
        blockers.append("annotations 未覆盖所有幕，缺：" + "、".join(ann_missing))
    info["annotations_ok"] = bool(scene_ids) and not ann_missing

    # ---- 5. 口播指纹复核 ----
    state_path = ep / "state.json"
    recorded: dict = {}
    state_doc: dict = {}
    if state_path.exists():
        try:
            state_doc = json.loads(state_path.read_text(encoding="utf-8"))
            recorded = state_doc.get("voice_fingerprints", {}) or {}
        except json.JSONDecodeError:
            warnings.append("state.json 解析失败，口播指纹无法复核（人工检查确认记录）")
    fp_detail: list[str] = []
    mismatches: list[str] = []
    if trio == {k: True for k in FINGERPRINT_FILES}:
        actual = {name: sha256_file(ep / "input" / name) for name in FINGERPRINT_FILES}
        info["fingerprints_actual"] = actual
        if not recorded:
            warnings.append("state.json 无 voice_fingerprints 记录：第一次人工确认后"
                            "应写入三件套 sha256（providers.voice.compute_voice_fingerprints），"
                            "此后才可拦截「确认后又改了口播」")
        else:
            for name in FINGERPRINT_FILES:
                old = recorded.get(name)
                new = actual[name]
                mark = "✓" if old == new else "✗"
                fp_detail.append(f"| {name} | {mark} | `{old}` | `{new}` |")
                if old != new:
                    mismatches.append(name)
            if mismatches:
                blockers.append("口播指纹与确认记录不一致："
                                + "、".join(mismatches)
                                + "（确认后改过旁白——按 §8 重跑矩阵重走三件套→标注→渲染）")
    info["fingerprint_table"] = fp_detail

    # ---- 5b. 声音身份一致性（跨期品牌声音检查；2026-08-28 声音选型引入）----
    voice_used = words_doc.get("voice")
    voice_expected = (state_doc.get("voice_identity") or {}).get("name")
    if voice_used and voice_expected and voice_used != voice_expected:
        warnings.append(
            f"声音身份漂移：words.json 用的是 {voice_used}，state 记录的生效身份是 "
            f"{voice_expected}（主题品牌声音应跨期一致；改声源请同步主题 voice 块"
            "并重跑 voice --force，按 §8 重算下游）")
    info["voice_identity"] = {"used": voice_used, "expected": voice_expected}

    # ---- 警告 b：底部字幕带亮度冲突（收编 review_images.check_board）----
    layout_dir = ep / "build" / "boards-layout"
    board_dir = layout_dir if any(layout_dir.glob("scene-*.png")) \
        else ep / "build" / "boards"
    # theme_dir 已在函数开头统一解析（多主题支持：黑板/白纸）
    sub_band_notes: list[str] = []
    try:
        from review_images import check_board
        for png in sorted(board_dir.glob("scene-*.png")):
            if png.stem.endswith((".raw", ".preview")):
                continue                    # 内容原图与二审预览：不是字幕带检查对象
            r = check_board(png, theme_dir=theme_dir)
            for wmsg in r.get("warnings", []):
                if "字幕" in wmsg:
                    sub_band_notes.append(f"{png.name}: {wmsg}")
    except Exception as exc:                      # 板图缺失不构成交付阻断
        warnings.append(f"底部字幕带检查跳过（{board_dir}）：{exc}")
    warnings.extend(sub_band_notes)
    info["subtitle_band_notes"] = sub_band_notes

    # ---- 7. 三次确认状态（质量门）----
    conf = state_doc.get("confirmations", {}) if isinstance(state_doc.get("confirmations"), dict) else {}
    if not conf.get("content_confirmed"):
        warnings.append("第1次确认未通过：内容与方向（content_confirmed=false），建议先确认脚本与主题")
    if not conf.get("visual_confirmed"):
        warnings.append("第2次确认未通过：视觉方案（visual_confirmed=false），建议先确认全部场景图")
    info["confirmations"] = conf

    # ---- 8. 板图质量（每幕 check_board 有 error 时阻断）+ 拥挤检测 ----
    board_errors: list[str] = []
    crowding_warnings: list[str] = []
    try:
        from review_images import check_board, check_layout_crowding
        layout_path = ep / "input" / "layout.json"
        for sid in scene_ids:
            png = ep / "build" / "boards" / f"{sid}.png"
            if not png.exists():
                board_errors.append(f"{sid}: 板图不存在")
                continue
            r = check_board(png, theme_dir=theme_dir)
            if r.get("errors"):
                board_errors.append(f"{sid}: " + "；".join(r["errors"]))
            # 拥挤/重叠检测
            cr = check_layout_crowding(layout_path, sid)
            if cr.get("warnings"):
                crowding_warnings.extend(cr["warnings"])
    except Exception as exc:
        warnings.append(f"板图质量检查跳过：{exc}")
    if board_errors:
        blockers.append("板图质量不合格：" + "；".join(board_errors))
    if crowding_warnings:
        warnings.extend(crowding_warnings)
    info["board_errors"] = board_errors
    info["crowding_warnings"] = crowding_warnings

    # ---- 9. 字幕缓存一致性（subtitles.ass 比 words.json 旧时警告）----
    sub_ass = ep / "build" / "subtitles.ass"
    words_json = ep / "input" / "words.json"
    if sub_ass.exists() and words_json.exists():
        if sub_ass.stat().st_mtime < words_json.stat().st_mtime:
            warnings.append("字幕缓存过期：build/subtitles.ass 早于 input/words.json，"
                            "assemble 时会自动重新生成，但建议确认字幕内容是否正确")
            info["subtitle_cache_stale"] = True
        else:
            info["subtitle_cache_stale"] = False

    # ---- 10. 渲染完整性（每幕 build/scenes/*.mp4 不存在时阻断）----
    render_missing: list[str] = []
    for sid in scene_ids:
        mp4 = ep / "build" / "scenes" / f"{sid}.mp4"
        if not mp4.exists():
            render_missing.append(sid)
    if render_missing:
        blockers.append("渲染不完整，缺：" + "、".join(render_missing) + "（先跑 build_video.py render）")
    info["render_missing"] = render_missing

    # ---- 11. layout.json 一致性（panels 与 elements 数量不匹配时阻断）----
    layout_path = ep / "input" / "layout.json"
    if layout_path.exists():
        try:
            layout_doc = json.loads(layout_path.read_text(encoding="utf-8"))
            for sid in scene_ids:
                scene_layout = layout_doc.get(sid, {})
                panels = scene_layout.get("panels", [])
                # elements 数量从 script.json 中获取
                script_scene = None
                if (ep / "input" / "script.json").exists():
                    script_doc_local = json.loads((ep / "input" / "script.json").read_text(encoding="utf-8"))
                    for sc in script_doc_local.get("scenes", []):
                        if sc.get("id") == sid:
                            script_scene = sc
                            break
                n_elements = len(script_scene.get("elements", [])) if script_scene else 0
                if panels and n_elements and len(panels) != n_elements:
                    blockers.append(f"{sid} layout.json 不一致：panels={len(panels)} 但 elements={n_elements}"
                                    "（必须一一对应）")
        except (json.JSONDecodeError, KeyError) as e:
            warnings.append(f"layout.json 解析失败：{e}")

    return blockers, warnings, info


def render_report(ep: Path, blockers: list[str], warnings: list[str],
                  info: dict) -> Path:
    ok_line = "**结论：通过（可交终审）**" if not blockers else \
        f"**结论：存在 {len(blockers)} 条阻断项，禁止进入终审**"
    rows = "\n".join(info.get("fingerprint_table", [])) or "_（无记录可比对）_"
    md = f"""# validate 报告 — {ep.name}

- 时间：{datetime.now().isoformat(timespec='seconds')}
- 幕数：{len(info.get('scenes', []))}　粒度：{info.get('granularity', '-')}　
  词条目：{info.get('word_count', '-')}
- 成片：{"存在" if info.get('final_exists') else "缺失"}　
  时长：{info.get('final_duration_ms', '-')}ms　
  旁白：{info.get('narration_duration_ms', '-')}ms（偏差 {info.get('drift_ms', '-')}ms）

## 结论

{ok_line}

## 阻断项（{len(blockers)}）

{chr(10).join('- ' + b for b in blockers) if blockers else '_（无）_'}

## 警告项（{len(warnings)}）

{chr(10).join('- ' + w for w in warnings) if warnings else '_（无）_'}

## 口播指纹复核（sha256）

| 文件 | 复核 | 确认记录 | 当前 |
|---|---|---|---|
{rows}
"""
    out_dir = ep / "build" / "review"
    out_dir.mkdir(parents=True, exist_ok=True)
    rp = out_dir / "validate-report.md"
    rp.write_text(md, encoding="utf-8")
    return rp


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode-dir", required=True, type=Path)
    args = ap.parse_args()
    ep = args.episode_dir.resolve()
    blockers, warnings, info = validate(ep)
    rp = render_report(ep, blockers, warnings, info)
    print(f"validate：阻断 {len(blockers)} 项，警告 {len(warnings)} 项")
    for b in blockers:
        print(f"  ✗ {b}")
    for w in warnings:
        print(f"  ! {w}")
    print(f"报告：{rp}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
