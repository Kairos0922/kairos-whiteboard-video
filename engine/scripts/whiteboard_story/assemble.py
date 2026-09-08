"""合成成片：按幕序 concat 场景视频，加旁白与烧录字幕（ASS），输出 deliverables/final.mp4。

参数与 v1 成片口径一致：H.264 + AAC、30fps、1920×1080、faststart。

P1 时间链闭环：ass_path 缺省时给 words_json，由 karaoke_ass 生成
词级卡拉OK ASS（sentence 粒度自动降级整句展示）；烧录链路不变。
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def assemble(scene_mp4s: list[Path], narration_mp3: Path, ass_path: Path | None,
             out_mp4: Path, words_json: Path | None = None) -> Path:
    """合成；成功返回输出路径。

    ass_path 显式给出时直接烧录；为 None 时从 words_json 现生成
    （build/subtitles.ass，卡拉OK按 words.json 粒度自动选择）。
    """
    if ass_path is None:
        if words_json is None or not Path(words_json).exists():
            raise RuntimeError("缺字幕来源：要么传 ass_path，要么传存在的 words_json")
        from .karaoke_ass import write_ass
        ass_path, _gran = write_ass(Path(words_json).parents[1], None)
    list_file = out_mp4.parent / "scenes.txt"
    with open(list_file, "w", encoding="utf-8") as f:
        for p in scene_mp4s:
            f.write(f"file '{str(p.resolve())}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-i", str(narration_mp3),
        "-vf", f"subtitles={Path(ass_path).as_posix()}",
        "-c:v", "libx264", "-r", "30", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        "-shortest", str(out_mp4),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    if not out_mp4.exists():
        raise RuntimeError(f"合成未产出 {out_mp4}")
    return out_mp4
