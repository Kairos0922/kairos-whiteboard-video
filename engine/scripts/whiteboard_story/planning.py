"""分幕规划与时间：读脚本与 TTS 时长，产出幕表。幕数跟 script.json 走。"""
from __future__ import annotations

import json
from pathlib import Path

def scene_table(episode_root: Path) -> list[dict]:
    """读时长表与脚本，返回幕表。幕数以脚本为准。"""
    script = episode_root / "input" / "script.json"
    if not script.exists():
        raise FileNotFoundError("未找到脚本 input/script.json")
    scenes = json.loads(script.read_text(encoding="utf-8")).get("scenes", [])
    if not scenes:
        raise ValueError("script.json scenes[] 为空")
    ids = [sc.get("id") or f"scene-{i + 1:02d}" for i, sc in enumerate(scenes)]
    durations_path = episode_root / "tts" / "durations.json"
    if not durations_path.exists():
        raise FileNotFoundError(f"缺少 {durations_path}")
    durations = json.loads(durations_path.read_text(encoding="utf-8"))
    if "scenes" in durations:
        durations = durations["scenes"]
    missing = [k for k in ids if durations.get(k) is None]
    if missing:
        raise ValueError(f"缺少幕时长: {missing}")
    total = sum(int(durations[sid]) for sid in ids
                if isinstance(durations.get(sid), (int, float)))
    return [{"scene": sid, "duration_ms": int(durations[sid])} for sid in ids] + \
        [{"total_ms": total}]


def check_audio_track(episode_root: Path, total_ms: int) -> None:
    """旁白整轨（build/narration.mp3）时长与幕表总时长对齐校验（±500ms）。"""
    import subprocess

    narration = episode_root / "build" / "narration.mp3"
    if not narration.exists():
        raise FileNotFoundError("缺少 build/narration.mp3")
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(narration)],
        capture_output=True, text=True, check=True,
    )
    actual = float(out.stdout.strip())
    if abs(int(actual * 1000) - total_ms) > 500:
        raise ValueError(f"旁白整轨 {actual:.2f}s 与幕表总时长 {total_ms / 1000:.2f}s 偏差超过 500ms")
