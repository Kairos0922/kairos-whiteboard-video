#!/usr/bin/env python3
"""P1 时间链闭环冒烟自测（真实 edge-tts，产物全落 /tmp/wsv-smoke/）。

覆盖任务书冒烟四条：
1. 真实 edge-tts 产三件套 → 打印词数、各幕窗口、抽 3 个词时间戳；
2. B 标注器吃该 words.json（假 boards 用内存 SCENE_PANELS 构造）→
   校验排程数值对齐幕窗口；
3. C ASS：词级卡拉OK打印前 30 行；sentence 假数据验证降级整句模式；
4. D validate：正例 exit=0，篡改 captions.srt 后 exit≠0 且列指纹明细。

用法：cd 本工具目录 && uv run python scripts/smoke_voice.py
退出码：0=全部通过。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest.mock as mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from whiteboard_story.providers import voice           # noqa: E402
from whiteboard_story import karaoke_ass               # noqa: E402
from whiteboard_story import make_annotations_v2 as mav  # noqa: E402
from whiteboard_story import validate                  # noqa: E402

SMOKE = Path("/tmp/wsv-smoke")
EP = SMOKE / "ep"

SCRIPT = {
    "scenes": [
        {"id": "scene-01", "narration": "为什么手写动画让人看得下去？答案藏在一个心理学现象里。",
         "elements": [
             {"id": "panel-1", "phrase": "手写动画"},
             {"id": "panel-2", "phrase": "心理学现象"},
         ]},
        {"id": "scene-02", "narration": "当画面跟着讲解逐笔出现，你的注意力会被牵着走，不需要意志力硬撑。",
         "elements": [
             {"id": "panel-1", "phrase": "注意力"},
             {"id": "panel-2", "phrase": "意志力"},
         ]},
        {"id": "scene-03", "narration": "所以白板视频的本质，不是画画，而是替观众管理视线。这条就是它的核心原理。",
         "elements": [
             {"id": "panel-1", "phrase": "白板视频"},
             {"id": "panel-2", "phrase": "核心原理"},
         ]},
    ]
}

FAKE_PANELS = {  # 最小假布局：每幕两格（只验排程数值，与真实板图无关）
    sid: [("panel", 120 + k * 60, 100 + k * 80, 600 - k * 50, 500, ["blue", "green"][k])
          for k in range(2)]
    for sid in ("scene-01", "scene-02", "scene-03")
}


def step(name: str):
    print(f"\n===== {name} =====")


def main() -> int:
    shutil.rmtree(SMOKE, ignore_errors=True)
    EP.mkdir(parents=True)

    # ---- 1. 真实 edge-tts 三件套 ----
    step("1 make_voice：真实 edge-tts 三件套")
    r = voice.make_voice(SCRIPT, EP)
    print(f"word_count={r['word_count']} total_ms={r['total_ms']} "
          f"durations_ms={r['durations_ms']}")
    assert r["word_count"] > 20, "词数异常"
    for f in ("narration.mp3", "captions.srt", "words.json", "script.json"):
        assert (EP / "input" / f).exists(), f"缺 {f}"
    assert (EP / "build/voice/scenes/scene-01.mp3").exists()
    srt_first = (EP / "input/captions.srt").read_text(encoding="utf-8").splitlines()[:8]
    print("captions.srt 前 8 行：")
    print("\n".join(srt_first))

    wd = json.loads((EP / "input/words.json").read_text(encoding="utf-8"))
    print("幕窗口：", wd["scenes"])
    samples = [wd["words"][0], wd["words"][len(wd["words"]) // 2], wd["words"][-1]]
    for w in samples:
        print(f'  样本词 [{w["scene_index"]}] "{w["text"]}" '
              f'{w["start_ms"]}-{w["end_ms"]}ms')
    fp = voice.compute_voice_fingerprints(EP / "input")
    print("fingerprints:", {k: v[:12] + "…" for k, v in fp.items()})

    # ---- 1b. attach_audio：已有配音接入（SRT → 句级窗口）----
    step("1b attach_audio：接入已有配音（sentence 粒度）")
    EP_ATTACH = SMOKE / "ep-attach"
    (EP_ATTACH / "input").mkdir(parents=True)
    shutil.copy(EP / "input/script.json", EP_ATTACH / "input/script.json")
    ra = voice.attach_audio(EP / "input/narration.mp3", EP / "input/captions.srt",
                            EP_ATTACH, script=EP_ATTACH / "input/script.json")
    print(f"cue_count={ra['cue_count']} total_ms={ra['total_ms']}")
    ad = json.loads((EP_ATTACH / "input/words.json").read_text(encoding="utf-8"))
    assert ad["granularity"] == "sentence", "attach_audio 必须标 sentence 粒度"
    got_blocks = [w["scene_index"] for w in ad["words"]]
    # 每幕归属必须为连续块（时序单调指针），本 fixture 应恰为 [0,0,1,1,2,2]
    dedup = [k for i, k in enumerate(got_blocks) if i == 0 or k != got_blocks[i - 1]]
    assert dedup == sorted(set(got_blocks)), \
        f"cue 幕归属出现回跳/穿插：{got_blocks}"
    print(f"cue→幕归属块：{dedup}（期望连续分块，无穿插）")
    wins = ad["scenes"]
    print("attach 幕窗口：", wins)
    assert len(wins) == 3
    assert wins[0]["start_ms"] == 0 and wins[-1]["end_ms"] == ad["duration_ms"]
    for a, b in zip(wins, wins[1:]):      # 窗口连续覆盖、单调不减
        assert b["start_ms"] >= a["end_ms"] - 1, f"幕窗口断开：{a}→{b}"
        assert b["start_ms"] > a["start_ms"], "幕窗口应严格推进（同幕多句必须能分幕）"

    # B 兼容 sentence 粒度：短语匹配应命中句内子片段
    with mock.patch.object(mav, "SCENE_PANELS", FAKE_PANELS):
        rc = mav.run_words_mode(EP_ATTACH, EP_ATTACH / "build" / "annotations")
    assert rc == 0
    n_pan = len(FAKE_PANELS["scene-01"])
    for sid in ("scene-01", "scene-02", "scene-03"):
        ann = json.loads((EP_ATTACH / "build/annotations" /
                          f"{sid}.annotation.json").read_text(encoding="utf-8"))
        assert ann["meta"]["granularity"] == "sentence"
        assert ann["meta"]["matched"] == f"{n_pan}/{n_pan}", \
            f"{sid} 句级粒度下短语应全命中：{ann['meta']['matched']}"
    print(f"attach+标注 matched=全中（句级窗口充当词级区间）✓")

    # ---- 2. B 标注器（词级排程）----
    step("2 make_annotations_v2 词级排程")
    with mock.patch.object(mav, "SCENE_PANELS", FAKE_PANELS):
        rc = mav.run_words_mode(EP, EP / "build" / "annotations")
    assert rc == 0
    for sc in wd["scenes"]:
        i = sc["scene_index"]
        sid = f"scene-{i + 1:02d}"
        ann = json.loads((EP / "build/annotations" /
                          f"{sid}.annotation.json").read_text(encoding="utf-8"))
        dur = sc["end_ms"] - sc["start_ms"]
        assert ann["sceneDurationMs"] == dur, f"{sid} 幕长不等于音频窗 {dur}ms"
        layout = next(e for e in ann["elements"] if e["kind"] == "layout")
        assert layout["reveal"]["startMs"] == mav.LEAD_MS
        assert layout["reveal"]["durationMs"] == mav.LAYOUT_MS, "版式层须吃片头固定值"
        area_end = dur - mav.TAIL_MS
        for e in [x for x in ann["elements"] if x["kind"] == "panel"]:
            s, d = e["reveal"]["startMs"], e["reveal"]["durationMs"]
            assert s >= mav.LEAD_MS + mav.LAYOUT_MS, f"{sid}/{e['id']} 越过片头线"
            assert s + d <= area_end + 1, f"{sid}/{e['id']} 越 TAIL 线 ({s + d}>{area_end})"
        ends = [e["reveal"]["startMs"] + e["reveal"]["durationMs"]
                for e in ann["elements"]]
        assert ends == sorted(ends), f"{sid} 元素窗口乱序"
        meta = ann["meta"]
        n_panels = len(FAKE_PANELS[sid])
        assert meta["matched"] == f"{n_panels}/{n_panels}", \
            f"{sid} 短语应全部命中词级区间（脚本落盘断链？）：{meta['matched']}"
        print(f"{sid}: matched={meta['matched']} grain={meta['granularity']} "
              f"windows={[(e['id'], e['reveal']['startMs'], e['reveal']['durationMs']) for e in ann['elements']]}")

    # ---- 2b. 向后兼容：无 words.json 走旧排程（裸脚本执行，验证 apply_layout 直连导入）----
    step("2b make_annotations_v2 旧路径兼容（tts/durations.json）")
    EP_LEGACY = SMOKE / "ep-legacy"
    (EP_LEGACY / "tts").mkdir(parents=True)
    (EP_LEGACY / "tts" / "durations.json").write_text(
        json.dumps({"scene-01": 4.2, "scene-02": 3.1}), encoding="utf-8")
    proc = subprocess.run([sys.executable,
                           str(HERE / "whiteboard_story" / "make_annotations_v2.py"),
                           "--episode-dir", str(EP_LEGACY)],
                          capture_output=True, text=True)
    print(proc.stdout.strip() or proc.stderr.strip())
    assert proc.returncode == 0, f"旧路径退出码 {proc.returncode}"
    for sid, secs in (("scene-01", 4.2), ("scene-02", 3.1)):
        ann = json.loads((EP_LEGACY / "build/annotations" /
                          f"{sid}.annotation.json").read_text(encoding="utf-8"))
        assert ann["sceneDurationMs"] == int(secs * 1000)
        layout = next(e for e in ann["elements"] if e["kind"] == "layout")
        # 旧口径：版式 = 时长 ×10%，内容均分
        expect_layout_ms = int(int(secs * 1000) * mav.LAYOUT_SHARE)
        assert layout["reveal"]["durationMs"] == expect_layout_ms
    print("旧排程路径数值与历史口径一致 ✓")

    # ---- 3. C ASS 卡拉OK ----
    step("3 karaoke_ass：词级卡拉OK（前 30 行）+ sentence 降级")
    ass_text = karaoke_ass.build_karaoke_ass(wd)
    lines = ass_text.splitlines()
    assert any("\\k" in ln for ln in lines), "词级模式必须出现 \\k"
    print("\n".join(lines[:30]))
    plain_doc = {"granularity": "sentence",
                 "words": [{"scene_index": i, "text": t,
                            "start_ms": s, "end_ms": e}
                           for i, (t, s, e) in enumerate([
                               ("第一句完整台词。", 0, 1800),
                               ("第二句较长一点的整句展示内容也不伪造。", 1800, 4200)])],
                 "scenes": [{"scene_index": 0, "start_ms": 0, "end_ms": 4200}]}
    plain = karaoke_ass.build_karaoke_ass(plain_doc)
    assert "\\k{" not in plain and "\\k" not in plain, "sentence 模式严禁出现 \\k"
    assert "granularity=sentence" in plain
    print("… sentence 模式头 6 行：")
    print("\n".join(plain.splitlines()[:6]))

    # ---- 4. D validate ----
    step("4 validate：正例过闸 → 篡改拦截")
    vep = SMOKE / "validate-fixture"
    (vep / "deliverables").mkdir(parents=True)
    for sub in ("build/annotations", "build/boards-layout"):
        (vep / sub).mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=size=320x180:rate=15:duration=1.5",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(vep / "deliverables/final.mp4")],
                   check=True)
    (vep / "input").mkdir(exist_ok=True)
    for f in ("narration.mp3", "captions.srt", "words.json"):
        shutil.copy(EP / "input" / f, vep / "input" / f)
    for sc in wd["scenes"]:
        sid = f"scene-{sc['scene_index'] + 1:02d}"
        ann = mav.build_annotation(sid, sc["end_ms"] - sc["start_ms"])  # 兼容旧构造即可
        (vep / "build/annotations" / f"{sid}.annotation.json").write_text(
            json.dumps(ann, ensure_ascii=False), encoding="utf-8")
    (vep / "state.json").write_text(json.dumps({"voice_fingerprints":
        voice.compute_voice_fingerprints(vep / "input")}, ensure_ascii=False),
        encoding="utf-8")
    blockers, warnings, info = validate.validate(vep)
    print(f"正例：blockers={blockers}")
    assert not blockers, "正例不应有阻断"
    rp = validate.render_report(vep, blockers, warnings, info)
    print(f"报告：{rp}")

    # 篡改 captions.srt（模拟「确认后又改了口播」）
    srt = vep / "input/captions.srt"
    srt.write_text(srt.read_text(encoding="utf-8") + "\n18\n00:00:00,000 --> 00:00:01,000\n被篡改\n",
                   encoding="utf-8")
    code = None
    sys.argv = ["validate.py", "--episode-dir", str(vep)]
    try:
        rc = validate.main()
        code = rc
    except SystemExit as e:
        code = e.code
    print(f"篡改后退出码 = {code}")
    report_txt = (vep / "build/review/validate-report.md").read_text(encoding="utf-8")
    tail = "\n".join(report_txt.splitlines()[:14])
    print("--- 报告摘录 ---")
    print(tail)
    assert code not in (0, None), "validate 必须拦下指纹不一致"
    mismatched = any("指纹与确认记录不一致" in b for b in validate.validate(vep)[0])
    assert mismatched, "必须明确列出指纹不一致明细"

    print("\nSMOKE ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
