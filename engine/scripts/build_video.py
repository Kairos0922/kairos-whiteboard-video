#!/usr/bin/env python3
"""whiteboard-story-video 一键流水线（工厂化，2026-08-23）。

子命令（--episode-dir 必填）：
  layout   烧录版式：build/boards/scene-XX.png → build/boards-layout/scene-XX.png
  annotate 重生成标注：build/annotations/scene-XX.annotation.json（与 tts 时长对齐）
  render   渲染动画：boards-layout + annotations → build/scenes/scene-XX.mp4（paper 模式）
  assemble 合成成片：concat 当期全部幕 + 旁白 + 字幕 → deliverables/final.mp4

本脚本是裸阶段执行器，只回写 state.json 的 phases 标志，**不查三次确认闸门**；
带闸门的调用走 workflow.py（render / confirm-*）。

明确不在本脚本内：
  - 板图 PNG 由宿主模型按 workflow.py prompts 的词表生成，落 build/boards/ 后 import；
  - 分区坐标写在当期 input/layout.json，构图随板图变化，每期校准。

用法示例（在本工具目录先 `uv sync`）：
  uv run python build_video.py --episode-dir <ep> layout
  uv run python build_video.py --episode-dir <ep> annotate
  uv run python build_video.py --episode-dir <ep> render --jobs 4
  uv run python build_video.py --episode-dir <ep> assemble

状态（2026-08-26）：layout / annotate / render / assemble 全链路可用；
render 走自有分区同步内核（whiteboard_story/kernel.py，设计见 references/kernel-design.md）。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from whiteboard_story.apply_layout import apply_layout            # noqa: E402
from whiteboard_story.render_trace import render_scene, DEFAULT_HAND  # noqa: E402
from whiteboard_story.resource_resolver import ResourceResolver       # noqa: E402
from whiteboard_story.karaoke_ass import write_ass                    # noqa: E402

TAIL_RESERVE_MS = 500   # 标注排程须给渲染器凝视段预留的最小余量（make_annotations_v2 TAIL_MS 保证）

HAND_DEFAULT = DEFAULT_HAND
FPS = 30


def _scene_ids(episode_dir: Path) -> list[str]:
    boards = sorted(episode_dir.glob("build/boards/scene-*.png"))
    if not boards:
        sys.exit(f"没有板图：{episode_dir}/build/boards/scene-*.png（先 import）")
    return [b.stem for b in boards]


def _scene_durations(ep: Path) -> dict[str, float]:
    """每幕时长（秒）：旧链路读 tts/durations.json，新声音链自 words.json 幕窗推导。"""
    legacy = ep / "tts" / "durations.json"
    if legacy.exists():
        return {k: float(v) for k, v in
                json.loads(legacy.read_text(encoding="utf-8")).items()}
    words = ep / "input" / "words.json"
    if not words.exists():
        sys.exit("缺 tts/durations.json 或 input/words.json（无法确定每幕时长）")
    doc = json.loads(words.read_text(encoding="utf-8"))
    ids: list[str] = []
    script = ep / "input" / "script.json"
    if script.exists():
        ids = [sc.get("id") or "" for sc in
               json.loads(script.read_text(encoding="utf-8")).get("scenes", [])]
    out: dict[str, float] = {}
    for sc in doc.get("scenes", []):
        idx = int(sc["scene_index"])
        sid = ids[idx] if idx < len(ids) and ids[idx] else f"scene-{idx + 1:02d}"
        out[sid] = (int(sc["end_ms"]) - int(sc["start_ms"])) / 1000
    return out


def _update_state(ep: Path, **phase_flags) -> None:
    """自动回写 state.json 的 phases 标志。
    无论用户通过 workflow.py 还是直接调用 build_video.py，状态都正确更新。
    忽略不存在的 state.json（未初始化的项目）。
    """
    state_path = ep / "state.json"
    if not state_path.exists():
        return
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    phases = state.setdefault("phases", {})
    changed = False
    for k, v in phase_flags.items():
        if phases.get(k) != v:
            phases[k] = v
            changed = True
    if changed:
        from datetime import datetime, timezone
        state["updated"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                               encoding="utf-8")


def _needs_render(ep: Path, sid: str, hand_png: Path) -> bool:
    """增量渲染判断：输出视频不存在或比依赖文件旧时返回 True。
    依赖文件：板图（boards-layout/<sid>.png）+ 标注（annotations/<sid>.annotation.json）+ 手笔。
    """
    out = ep / "build" / "scenes" / f"{sid}.mp4"
    if not out.exists():
        return True
    out_mtime = out.stat().st_mtime
    # 依赖文件列表
    deps = [
        ep / "build" / "boards-layout" / f"{sid}.png",
        ep / "build" / "boards-layout" / f"{sid}.raw.png",
        ep / "build" / "annotations" / f"{sid}.annotation.json",
        Path(hand_png),
    ]
    for dep in deps:
        if dep.exists() and dep.stat().st_mtime > out_mtime:
            return True
    return False


def cmd_layout(ep: Path, args) -> int:
    out_dir = ep / "build" / "boards-layout"
    out_dir.mkdir(parents=True, exist_ok=True)
    for sid in _scene_ids(ep):
        out = apply_layout(ep / "build" / "boards" / f"{sid}.png", sid, out_dir / f"{sid}.png",
                           episode_dir=ep, out_raw=out_dir / f"{sid}.raw.png",
                           out_preview=out_dir / f"{sid}.preview.png")
        print(f"OK {out.name}")
    return 0


def cmd_annotate(ep: Path, args) -> int:
    # make_annotations_v2 是裸导入的 CLI 直跑脚本，用 subprocess 保持原调用方式
    subprocess.run([sys.executable, str(SCRIPTS / "whiteboard_story" / "make_annotations_v2.py"),
                    "--episode-dir", str(ep)], check=True)
    # 校验凝视余量（防截尾复发：last element 结束须留 ≥500ms 给渲染器凝视段）
    durations = _scene_durations(ep)
    ok = True
    for sid in sorted(durations):
        if not sid.startswith("scene-"):
            continue
        ann_path = ep / "build" / "annotations" / f"{sid}.annotation.json"
        if not ann_path.exists():
            print(f"✗ 缺标注：{ann_path}")
            ok = False
            continue
        ann = json.loads(ann_path.read_text(encoding="utf-8"))
        last_end = max(e["reveal"]["startMs"] + e["reveal"]["durationMs"] for e in ann["elements"])
        tail = ann["sceneDurationMs"] - last_end
        print(f"OK {sid}.annotation.json  tail_reserve={tail}ms")
        ok = ok and tail >= TAIL_RESERVE_MS
    if not ok:
        sys.exit(f"存在尾段余量 < {TAIL_RESERVE_MS}ms 的标注，渲染会截尾（检查 TAIL_MS 常量）")
    _update_state(ep, annotated=True)
    return 0


def _episode_theme_dir(ep: Path) -> Path | None:
    """解析当期主题目录：state.theme → script.json.theme。

    统一走 ResourceResolver，支持相对于 episode_dir 和相对于项目根两种写法，
    杜绝基准不一致导致主题包找不到（曾导致手素材回退到马克笔）。
    """
    return ResourceResolver(ep).resolve_theme_from_state()


def _resolve_hand(ep: Path, hand_arg: str | None) -> Path:
    """手素材优先级：--hand > 主题包 hands[0] > 当期 assets/hand-chalk.png >
    当期 assets/hand-pen.png > 引擎默认。

    主题声明了手素材（如 chalk 主题的粉笔手）就以主题为准——马克笔配黑板
    是素材错配（2026-09-04 用户打回）。统一走 ResourceResolver。
    """
    return ResourceResolver(ep).resolve_hand(hand_arg)


def _prev_scene_raw(ep: Path, sids: list[str], sid: str) -> Path | None:
    """上一幕的板面（幕首淡入的来源）；首幕返回 None。
    优先 overlay（含标签）：上一幕收尾帧有标签，用 raw 会在切点造成标签瞬消。"""
    i = sids.index(sid)
    if i <= 0:
        return None
    prev = sids[i - 1]
    overlay = ep / "build" / "boards-layout" / f"{prev}.png"
    return overlay if overlay.exists() else (ep / "build" / "boards-layout" / f"{prev}.raw.png")


def cmd_render(ep: Path, args) -> int:
    hand = _resolve_hand(ep, args.hand)
    sids = [args.scene] if args.scene else _scene_ids(ep)
    fade_from = (Path(args.fade_from) if getattr(args, "fade_from", None) else None)
    jobs = args.jobs if args.jobs else min(4, max(1, (os.cpu_count() or 2) // 2))
    if jobs <= 1 or len(sids) <= 1:
        for sid in sids:
            if not _needs_render(ep, sid, hand):
                print(f"⊘ {sid}.mp4 跳过（无变化）")
                continue
            t0 = time.time()
            raw = ep / "build" / "boards-layout" / f"{sid}.raw.png"
            if not raw.exists():
                raw = ep / "build" / "boards-layout" / f"{sid}.png"
            prev = fade_from if fade_from is not None else _prev_scene_raw(ep, _scene_ids(ep), sid)
            out = render_scene(
                raw,
                ep / "build" / "annotations" / f"{sid}.annotation.json",
                ep / "build" / "scenes" / f"{sid}.mp4",
                hand, board_style="paper", fps=FPS,
                overlay_png=ep / "build" / "boards-layout" / f"{sid}.png",
                fade_from_png=prev,
                hand_follow=getattr(args, "hand_follow", 0.35),
                labels_json=ep / "build" / "boards-layout" / f"{sid}.labels.json")
            print(f"OK {sid}.mp4  {time.time() - t0:.0f}s  -> {out}")
        if not args.scene:
            _update_state(ep, rendered=True)
        return 0
    # 并行：各幕互相独立，用本脚本自身的单幕子进程池（规避 spawn 下的 pickle 问题，
    # 每个子进程各自加载板图与内核；IO/CPU 都在子进程里，主进程只调度）
    (ep / "build" / "scenes").mkdir(parents=True, exist_ok=True)
    self_cmd = [sys.executable, str(Path(__file__).resolve()), "--episode-dir", str(ep)]
    all_sids = _scene_ids(ep)
    t0 = time.time()
    procs: dict[str, subprocess.Popen] = {}
    # 增量渲染：过滤掉不需要重渲染的幕
    pending = []
    skipped = []
    for sid in sids:
        if _needs_render(ep, sid, hand):
            pending.append(sid)
        else:
            skipped.append(sid)
    for sid in skipped:
        print(f"⊘ {sid}.mp4 跳过（无变化）")
    if not pending:
        print(f"全部 {len(sids)} 幕无需重渲染")
        if not args.scene:
            _update_state(ep, rendered=True)
        return 0
    retry_count: dict[str, int] = {sid: 0 for sid in pending}
    MAX_RETRY = 2
    RETRY_DELAYS = [5, 10]  # 第1次重试等5s，第2次等10s
    failed: list[str] = []
    while pending or procs:
        while pending and len(procs) < jobs:
            sid = pending.pop(0)
            cmd = self_cmd + ["render", "--scene", sid, "--hand", str(hand), "--jobs", "1"]
            prev = _prev_scene_raw(ep, all_sids, sid)
            if prev is not None:
                cmd += ["--fade-from", str(prev)]
            log = open(ep / "build" / "scenes" / f"{sid}.render.log", "w", encoding="utf-8")
            procs[sid] = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
        time.sleep(0.2)
        for sid in list(procs):
            rc = procs[sid].poll()
            if rc is None:
                continue
            procs.pop(sid)
            if rc == 0 and (ep / "build" / "scenes" / f"{sid}.mp4").exists():
                print(f"OK {sid}.mp4")
            else:
                if retry_count[sid] < MAX_RETRY:
                    retry_count[sid] += 1
                    delay = RETRY_DELAYS[min(retry_count[sid] - 1, len(RETRY_DELAYS) - 1)]
                    print(f"↻ {sid} 渲染失败（rc={rc}），第{retry_count[sid]}次重试（{delay}s后），"
                          f"日志：build/scenes/{sid}.render.log")
                    time.sleep(delay)
                    pending.append(sid)
                else:
                    failed.append(sid)
                    print(f"✗ {sid} 渲染失败（已重试{MAX_RETRY}次），日志：build/scenes/{sid}.render.log")
    if failed:
        # ---- 渲染失败诊断：自动检查根因并给出修复建议 ----
        # 避免用户看到"零绘制任务"后需要深入排查3层才能找到原因。
        print()
        print("=" * 60)
        print("渲染失败诊断：")
        print("=" * 60)
        for sid in failed:
            print(f"\n--- {sid} ---")
            # 1. 检查 annotation
            ann_path = ep / "build" / "annotations" / f"{sid}.annotation.json"
            if not ann_path.exists():
                print(f"  ✗ 缺 annotation.json：{ann_path}")
                print(f"    → 修复：先跑 annotate 命令生成标注")
                continue
            try:
                ann = json.loads(ann_path.read_text(encoding="utf-8"))
                n_elements = len(ann.get("elements", []))
                matched = ann.get("meta", {}).get("matched", "?")
                print(f"  annotation: {n_elements} elements, matched={matched}")
                if n_elements <= 1:
                    print(f"  ✗ 只有 {n_elements} 个 element（应为 1 layout + N 内容元素）")
                    print(f"    → 根因：annotation 生成器没有生成内容元素")
                    # 2. 检查 layout.json
                    layout_path = ep / "input" / "layout.json"
                    if not layout_path.exists():
                        print(f"  ✗ 缺 layout.json：{layout_path}")
                        print(f"    → 修复：运行 annotate 会自动生成默认 layout.json，或手动创建")
                    else:
                        layout = json.loads(layout_path.read_text(encoding="utf-8"))
                        panels = (layout.get(sid) or layout.get("scenes", {}).get(sid) or {}).get("panels", [])
                        print(f"  layout.json panels: {len(panels)} 个")
                        if not panels:
                            print(f"  ✗ layout.json 中 {sid} 的 panels 为空")
                            print(f"    → 修复：在 layout.json 中为 {sid} 添加 panels 配置")
                    # 3. 检查 script.json elements 格式
                    script_path = ep / "input" / "script.json"
                    if script_path.exists():
                        doc = json.loads(script_path.read_text(encoding="utf-8"))
                        for i, sc in enumerate(doc.get("scenes", [])):
                            if sc.get("id") == sid or f"scene-{i+1:02d}" == sid:
                                elements = sc.get("elements", [])
                                print(f"  script.json elements: {len(elements)} 个")
                                for j, el in enumerate(elements):
                                    if "id" not in el:
                                        if "panel" in el:
                                            print(f"  ✗ 第{j+1}个 element 用了 panel:{el['panel']} 而非 id:'panel-N'")
                                            print(f"    → 修复：把 panel 改为 id:'panel-{el['panel']}'")
                                        else:
                                            print(f"  ✗ 第{j+1}个 element 缺 id 字段")
                                    elif not str(el["id"]).startswith("panel-"):
                                        print(f"  ✗ 第{j+1}个 element id='{el['id']}' 不符合 panel-N 格式")
                                break
                elif matched == "0/0":
                    print(f"  ✗ matched=0/0：phrase 全部未匹配")
                    print(f"    → 可能原因：phrase 用词与旁白不一致（英文vs中文）")
                    print(f"    → 修复：调整 script.json elements[].phrase，使用旁白中实际出现的词")
                else:
                    # 读取渲染日志找具体错误
                    log_path = ep / "build" / "scenes" / f"{sid}.render.log"
                    if log_path.exists():
                        log_content = log_path.read_text(encoding="utf-8")
                        if "零绘制任务" in log_content:
                            print(f"  ✗ 错误：时序编排结果为零绘制任务")
                            print(f"    → 虽然有 {n_elements} elements，但排程后无绘制任务")
                            print(f"    → 检查 annotation 的 reveal.startMs/durationMs 是否合理")
                        elif "手" in log_content and "不存在" in log_content:
                            print(f"  ✗ 手素材不存在")
                            print(f"    → 修复：用 --hand 指定正确的手素材路径")
                        else:
                            print(f"  日志最后10行：")
                            for line in log_content.strip().split("\n")[-10:]:
                                print(f"    {line}")
            except Exception as e:
                print(f"  ✗ annotation 解析失败：{e}")
        print()
        print("=" * 60)
        sys.exit(f"渲染失败（已重试{MAX_RETRY}次）：{', '.join(failed)}")
    print(f"并行渲染完成：{len(sids)} 幕，总耗时 {time.time() - t0:.0f}s（jobs={jobs}）")
    if not args.scene:
        _update_state(ep, rendered=True)
    return 0


def _ffprobe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())


def cmd_assemble(ep: Path, args) -> int:
    scenes = _scene_ids(ep)
    narration = ep / "input" / "narration.mp3"
    if not narration.exists():
        narration = ep / "build" / "narration.mp3"

    # 字幕：优先词级 ASS（卡拉OK逐字高亮），基于依赖时间戳增量判断
    # subtitles.ass 是 words.json 的派生产物：不存在或比 words.json 旧时重新生成
    sub_path = ep / "build" / "subtitles.ass"
    sub_kind = "ass"
    words = ep / "input" / "words.json"
    need_regen = not sub_path.exists()
    if sub_path.exists() and words.exists():
        if sub_path.stat().st_mtime < words.stat().st_mtime:
            need_regen = True
            print(f"字幕已过期（subtitles.ass 早于 words.json），重新生成")
    if need_regen:
        if words.exists():
            try:
                sub_path, gran = write_ass(ep)
                print(f"生成词级字幕：{sub_path}（granularity={gran}）")
            except Exception as e:
                print(f"ASS 字幕生成失败（{e}），回退 SRT")
                sub_kind = "srt"
        else:
            sub_kind = "srt"
    else:
        print(f"复用现有字幕：{sub_path}")
    if sub_kind == "srt":
        sub_path = ep / "input" / "captions.srt"
        if not sub_path.exists():
            sub_path = ep / "tts" / "combined.srt"

    if not narration.exists() or not sub_path.exists():
        sys.exit(f"缺旁白或字幕（旁白：{narration}；字幕：{sub_path}）")
    out_dir = ep / "deliverables"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "final.mp4"

    # 单幕时长与音频对齐校验（TAIL_MS 修复后应 ≤ 音频 + 100ms；超 200ms 报错防截尾复发）
    durations = _scene_durations(ep)
    for sid in scenes:
        want = durations.get(sid)
        if want:
            got = _ffprobe_duration(ep / "build" / "scenes" / f"{sid}.mp4")
            if abs(got - want) > 0.2:
                sys.exit(f"{sid} 时长 {got:.3f}s 与音频 {want:.3f}s 差 {abs(got-want)*1000:.0f}ms > 200ms，"
                         "检查标注排程（TAIL_MS）与渲染是否完整，勿直接合成")

    scenes_txt = ep / "build" / "scenes.txt"
    scenes_txt.write_text("\n".join(f"file '{ep / 'build/scenes' / (sid + '.mp4')}'" for sid in scenes) + "\n",
                          encoding="utf-8")

    print(f"合成：{len(scenes)} 幕 + {narration.name} + {sub_path.name}（{sub_kind}）→ {out}")
    # 快速模式：用 faster preset 替代 medium，速度提升约30-40%
    # macOS 上自动检测 VideoToolbox 硬件加速
    fast_mode = getattr(args, "fast", False)
    if fast_mode:
        # 检测 macOS VideoToolbox 硬件加速
        use_hw = False
        if sys.platform == "darwin":
            try:
                r = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                   capture_output=True, text=True, timeout=5)
                if "h264_videotoolbox" in r.stdout:
                    use_hw = True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        if use_hw:
            video_codec = ["-c:v", "h264_videotoolbox", "-b:v", "5M"]
            print("  快速模式：macOS VideoToolbox 硬件加速")
        else:
            video_codec = ["-c:v", "libx264", "-crf", "22", "-preset", "faster"]
            print("  快速模式：libx264 faster preset（质量略降，速度更快）")
    else:
        video_codec = ["-c:v", "libx264", "-crf", "20", "-preset", "medium"]
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(scenes_txt),
           "-i", str(narration),
           "-vf", f"subtitles={sub_path}",
           *video_codec,
           "-r", str(FPS), "-pix_fmt", "yuv420p",
           "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
           "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
           "-movflags", "+faststart",
           "-shortest", str(out)]
    subprocess.run(cmd, check=True)
    dur = _ffprobe_duration(out)
    size = out.stat().st_size
    print(f"OK {out}  {dur:.3f}s  {size/1e6:.1f}MB")
    _update_state(ep, finalized=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode-dir", required=True, type=Path)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_text in (("layout", "烧录版式"),
                            ("annotate", "重生成标注"),
                            ("render", "渲染动画"),
                            ("assemble", "合成成片")):
        p = sub.add_parser(name, help=help_text)
        if name == "render":
            p.add_argument("--scene", help="单幕 scene-XX；缺省全部")
            p.add_argument("--hand", help="手笔素材路径；缺省主题 hands[0] → assets/hand-pen.png")
            p.add_argument("--jobs", type=int, default=0,
                           help="并行渲染进程数；缺省=CPU 核数一半（上限 4），1=串行")
            p.add_argument("--fade-from", default=None,
                           help="幕首淡入来源图（上一幕板面）；缺省自动取上一幕 raw")
        if name == "assemble":
            p.add_argument("--fast", action="store_true",
                           help="快速模式：faster preset 或硬件加速，速度提升约30-40%（质量略降）")
    args = ap.parse_args()
    ep = args.episode_dir.resolve()
    dispatch = {"layout": cmd_layout, "annotate": cmd_annotate,
                "render": cmd_render, "assemble": cmd_assemble}
    return dispatch[args.cmd](ep, args)


if __name__ == "__main__":
    raise SystemExit(main())
