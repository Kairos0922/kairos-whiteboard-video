"""karaoke_ass.py — ASS 字幕生成器（engine-design §6 合成层，P1 卡拉OK）。

- 词级 words.json → 逐句一行 Dialogue，每词一个 \\k 卡拉OK标签：
  当前读到的高亮色（PrimaryColour）、未读普通色（SecondaryColour），
  白色描边保证任何底色可读；\\k 时长 = 词时长取整到厘秒，行内累计与
  真实词边界吻合，不发明时间。
- 只有 sentence 粒度（attach_audio 路线）→ 输出普通整句显示，
  文件头注释明示「无词级计时」，**不伪造逐字卡拉OK**。

烧录沿用 assemble.py 的 ffmpeg subtitles 滤镜链路，编码参数不变。
用法：<python> karaoke_ass.py --episode-dir <ep>   # 写 build/subtitles.ass
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from providers.voice import SENTENCE_END_PUNCT  # noqa: E402

ASS_PATH_NAME = "subtitles.ass"
LINE_MAX_CHARS = 18          # 单行字幕字数上限（1920 宽、60 号字的舒适阅读量）
LINE_BREAK_PAUSE_MS = 350    # 词间停顿 ≥ 该值换行（词级分组用）
MIN_LINE_DISPLAY_MS = 400    # 整句展示模式最短停留

# ASS 颜色为 &HAABBGGRR（BGR 序）。纸白底：
PRIMARY_ASS = "&H000B4F8F"     # 高亮（正在读的字）：暖赭 #8F4F0B(RGB) → BGR 0B4F8F
SECONDARY_ASS = "&H00353A3D"   # 未读普通：石墨 #3D3A35(RGB) → BGR 353A3D
OUTLINE_ASS = "&H00FFFFFF"     # 描边：白；黑板上换深底同样醒目

STYLE_NAME = "WhiteboardKaraoke"

_HEADER_WORD = """[Script Info]
; 由 whiteboard_story/karaoke_ass.py 生成：词级卡拉OK（engine-design §6）
; granularity=word — 每词 \\k 标签，时间来自 words.json 真实语音边界
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {style},PingFang SC,58,{primary},{secondary},{outline},&H64000000,1,0,0,0,100,100,0,0,1,3,1,2,90,90,54,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

_HEADER_PLAIN = """[Script Info]
; 由 whiteboard_story/karaoke_ass.py 生成
; granularity=sentence —— 无词级计时，整句展示；**不伪造逐字卡拉OK**
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {style},PingFang SC,58,{ink},{ink},{outline},&H64000000,1,0,0,0,100,100,0,0,1,3,1,2,90,90,54,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_time(ms: int) -> str:
    """ASS 时间 h:mm:ss.cc。"""
    ms = max(0, int(ms))
    cs = round(ms / 10)
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs2 = divmod(rem, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs2:02d}"


def _is_end(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and t[-1] in SENTENCE_END_PUNCT


def _group_lines(words: list[dict]) -> list[list[dict]]:
    """把该幕词序列按标点/停顿/行长分成字幕行。跨幕永不并组。"""
    lines: list[list[dict]] = []
    cur: list[dict] = []
    prev: dict | None = None
    for w in words:
        if not w.get("text"):
            continue
        new_line = (
            cur and prev is not None
            and (int(w["scene_index"]) != int(prev["scene_index"])
                 or int(w["start_ms"]) - int(prev["end_ms"]) >= LINE_BREAK_PAUSE_MS
                 or sum(len(x["text"]) for x in cur) >= LINE_MAX_CHARS)
        )
        if new_line:
            lines.append(cur)
            cur = []
        cur.append(w)
        prev = w
        if _is_end(w["text"]):
            lines.append(cur)
            cur = []
            prev = None
    if cur:
        lines.append(cur)
    return [ln for ln in lines if ln]


def build_karaoke_ass(words_doc: dict) -> str:
    """words.json → ASS 文本。granularity=word 出逐词 \\k；sentence 出整句展示。"""
    granularity = words_doc.get("granularity", "word")
    if granularity == "sentence":
        return _build_plain_ass(words_doc)

    out = [_HEADER_WORD.format(style=STYLE_NAME, primary=PRIMARY_ASS,
                               secondary=SECONDARY_ASS, outline=OUTLINE_ASS)]
    for scene in sorted(words_doc.get("scenes", []), key=lambda s: s["scene_index"]):
        units = [w for w in words_doc.get("words", [])
                 if int(w.get("scene_index", -1)) == int(scene["scene_index"])]
        for line in _group_lines(units):
            start_ms = int(line[0]["start_ms"])
            end_ms = max(int(w["end_ms"]) for w in line)
            parts: list[str] = []
            prev_end = start_ms
            for w in line:
                # 词前停顿/换幕等待：空文本 \k 吃掉，色带暂停推进、不提前点亮
                gap_cs = round((int(w["start_ms"]) - prev_end) / 10)
                if gap_cs > 0:
                    parts.append(r"{\k%d}" % gap_cs)
                kcs = max(1, round((int(w["end_ms"]) - int(w["start_ms"])) / 10))
                parts.append(r"{\k%d}%s" % (kcs, str(w["text"])))
                prev_end = int(w["end_ms"])
            text = "".join(parts)
            out.append(f"Dialogue: 0,{_ass_time(start_ms)},{_ass_time(end_ms)},"
                       f"{STYLE_NAME},,0,0,0,,{text}")
    return "\n".join(out) + "\n"


def _build_plain_ass(words_doc: dict) -> str:
    """sentence 粒度：整句普通展示（无 \\k），时间窗=句首末 cue。"""
    out = [_HEADER_PLAIN.format(style=STYLE_NAME, ink=SECONDARY_ASS,
                                outline=OUTLINE_ASS)]
    cues = sorted(words_doc.get("words", []), key=lambda w: int(w["start_ms"]))
    for c in cues:
        s = int(c["start_ms"])
        e = max(s + MIN_LINE_DISPLAY_MS, int(c["end_ms"]))
        text = str(c["text"]).replace("\n", r"\N")
        out.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},"
                   f"{STYLE_NAME},,0,0,0,,{text}")
    return "\n".join(out) + "\n"


def write_ass(episode_dir: Path, ass_path: Path | None = None) -> tuple[Path, str]:
    """从 input/words.json 产字幕文件（缺省 build/subtitles.ass）。返回 (路径, 粒度)。"""
    ep = Path(episode_dir)
    src = ep / "input" / "words.json"
    if not src.exists():
        raise FileNotFoundError(f"缺 {src}：先跑 providers/voice.make_voice 或 attach_audio")
    doc = json.loads(src.read_text(encoding="utf-8"))
    gran = doc.get("granularity", "word")
    target = ass_path or ep / "build" / ASS_PATH_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_karaoke_ass(doc), encoding="utf-8")
    return target, gran


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode-dir", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    path, gran = write_ass(args.episode_dir, args.out)
    n_lines = sum(1 for ln in path.read_text(encoding="utf-8").splitlines()
                  if ln.startswith("Dialogue:"))
    print(f"OK {path}  granularity={gran}  dialogue={n_lines}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
