"""voice.py — 语音适配层（engine-design §2/§3 阶段 3，P1 时间链闭环第一环）。

两个功能：
- make_voice(script, episode_dir, ...)：逐幕调 edge-tts（WordBoundary 词级时间），
  产出三件套 input/narration.mp3 + input/captions.srt + input/words.json，
  以及幕级中间产物 build/voice/scenes/scene-XX.mp3；
- attach_audio(audio_path, srt_path, episode_dir, ...)：接入已有配音。SRT 必填，
  句级窗口充当粗粒度词表（granularity="sentence"）；下游一律降级句级，
  **严禁伪造词边界**。

words.json schema（固定 v1；attach_audio 另加 granularity 字段）：
{
  "version": 1,
  "voice": "<声音名>",
  "granularity": "word" | "sentence",      # sentence 仅出现在 attach_audio
  "duration_ms": N,
  "scenes":  [{"scene_index": i, "start_ms": A, "end_ms": B}, ...],
  "words":   [{"scene_index": i, "text": "词", "start_ms": n, "end_ms": m}, ...]
}

幕窗口由**逐幕音频实际时长（ffprobe 实测）累计**得出——结构性精确，
不做全文模糊匹配；词时间为幕内相对时间加幕偏移的全局坐标。

口播指纹：compute_voice_fingerprints(input_dir) 返回三件套 sha256。
挂接约定：第一次确认（script_audio_confirmed）时调用方把返回值写入
state["voice_fingerprints"] = {...}；validate 在渲染前复核，不一致即阻断
（engine-design §2 第 5 条）。

用法：
  uv run python providers 相关调用走 whiteboard_story.providers.voice；
  CLI 冒烟：uv run python -m scripts.smoke_voice（见 scripts/smoke_voice.py）
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
from pathlib import Path

# 句级字幕聚合：中文句末标点集合与单条字幕字符上限（任务书口径：超 22 字硬断）
SENTENCE_END_PUNCT = "。！？!?；;……"
MAX_CAPTION_CHARS = 22
# 词间停顿 ≥ 该值视为句界（WordBoundary 不回传标点时的真实停顿兜底）
SENTENCE_PAUSE_MS = 400

WORD_JSON_VERSION = 1


class VoiceError(RuntimeError):
    """语音适配层显式失败类型。"""


def _ffprobe_duration_ms(path: Path) -> int:
    """实测媒体时长（ms）。ffprobe 不存在或读不出时长都算硬错误。"""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, check=True)
        return int(round(float(r.stdout.strip()) * 1000))
    except FileNotFoundError as e:
        raise VoiceError("缺 ffmpeg/ffprobe（系统需安装），无法量测音频时长") from e
    except (subprocess.CalledProcessError, ValueError) as e:
        raise VoiceError(f"ffprobe 读不出时长：{path}") from e


def _has_audio_stream(path: Path) -> bool:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return bool(r.stdout.strip())


# ---------------------------------------------------------------- 句级聚合

def _is_sentence_end(text: str) -> bool:
    t = text.strip()
    return bool(t) and t[-1] in SENTENCE_END_PUNCT


def aggregate_sentences(words: list[dict], max_chars: int = MAX_CAPTION_CHARS,
                        pause_ms: int = SENTENCE_PAUSE_MS) -> list[dict]:
    """把词区间聚合成句级字幕：句末标点 / 词间真实停顿 ≥pause_ms 断句；
    累计超 max_chars 硬断为多条字幕。只落词边界，不发明时间点。

    返回 [{"text","start_ms","end_ms"}]。跨幕词永不并入同一句。
    """
    sents: list[dict] = []
    buf: list[str] = []
    start_ms: int | None = None
    end_ms = 0
    prev_end: int | None = None
    prev_scene: int | None = None

    def flush():
        nonlocal buf, start_ms
        if buf and start_ms is not None:
            sents.append({"text": "".join(buf), "start_ms": start_ms, "end_ms": end_ms})
        buf, start_ms = [], None

    for w in words:
        if not w.get("text"):
            continue
        ws, we, wsc = int(w["start_ms"]), int(w["end_ms"]), int(w.get("scene_index", 0))
        boundary = (prev_scene is not None and wsc != prev_scene) or (
            prev_end is not None and ws - prev_end >= pause_ms)
        if boundary and buf:
            flush()
        if start_ms is None:
            start_ms = ws
        end_ms = we
        buf.append(w["text"])
        prev_end, prev_scene = we, wsc
        chars = sum(len(x) for x in buf)
        if _is_sentence_end(w["text"]) or chars >= max_chars:
            flush()
    flush()
    return sents


_SRT_TIME = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")


def parse_srt(srt_path: Path) -> list[dict]:
    """解析 SRT → [{"text","start_ms","end_ms"}]（毫秒整数）。"""
    raw = Path(srt_path).read_text(encoding="utf-8-sig")
    cues: list[dict] = []
    block: list[str] = []

    def to_ms(ts: str) -> int:
        m = _SRT_TIME.fullmatch(ts.strip())
        if not m:
            raise VoiceError(f"SRT 时间码不合法：{ts!r}")
        h, mi, s, ms = (int(x) for x in m.groups())
        return ((h * 60 + mi) * 60 + s) * 1000 + ms

    def commit():
        nonlocal block
        lines = [x for x in block if x.strip()]
        block = []
        times = [x for x in lines if "-->" in x]
        if not times:
            return
        a, b = [t.strip() for t in times[0].split("-->")]
        text = "\n".join(lines[lines.index(times[0]) + 1:])
        text = re.sub(r"<[^>]+>", "", text).strip()
        if text:
            cues.append({"text": text, "start_ms": to_ms(a), "end_ms": to_ms(b)})
    for line in raw.splitlines():
        if not line.strip() and block:
            commit()
        else:
            block.append(line.rstrip())
    if block:
        commit()
    if not cues:
        raise VoiceError(f"SRT 里没有可用台词：{srt_path}")
    return sorted(cues, key=lambda c: c["start_ms"])


def write_srt(cues: list[dict], path: Path) -> Path:
    def fmt(ms: int) -> str:
        ms = max(0, int(ms))
        h, rem = divmod(ms, 3600000)
        m, rem = divmod(rem, 60000)
        s, ms2 = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms2:03d}"
    out = []
    for i, c in enumerate(sorted(cues, key=lambda x: x["start_ms"]), 1):
        out += [str(i), f'{fmt(c["start_ms"])} --> {fmt(c["end_ms"])}', c["text"], ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 合成（edge-tts）

async def _synth_scene(text: str, mp3_path: Path, voice: str,
                       rate: str, volume: str, pitch: str) -> list[dict]:
    """单幕合成：写 mp3 并收集 WordBoundary（幕内相对 ms）。返回词表。

    瞬时失败（NoAudioReceived，微软侧 DRM/WebSocket 偶发空回包）重试 1 次；
    复跑 stream() 需要新 Communicate 实例（stream 只能调一次）。
    """
    import edge_tts

    async def once(comm) -> tuple[bytes, list[dict]]:
        words: list[dict] = []
        audio = bytearray()
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # offset/duration 单位 100ns → ms
                words.append({"text": chunk["text"],
                              "start_ms": chunk["offset"] // 10_000,
                              "end_ms": (chunk["offset"] + chunk["duration"]) // 10_000})
        return bytes(audio), words

    last_err: Exception | None = None
    for attempt in (1, 2):
        comm = edge_tts.Communicate(text, voice=voice, rate=rate, volume=volume,
                                    pitch=pitch, boundary="WordBoundary")
        try:
            audio, words = await once(comm)
        except edge_tts.exceptions.NoAudioReceived as e:   # 偶发空回包
            last_err = e
            print(f"  ! edge-tts 第 {attempt} 次合成无音频（瞬时），"
                  + ("重试" if attempt == 1 else "放弃"))
            continue
        if not audio:
            raise VoiceError(f"edge-tts 未产出音频：{mp3_path}")
        if not words:
            raise VoiceError(f"edge-tts 未回传 WordBoundary（无词级时间）：{mp3_path}")
        mp3_path.parent.mkdir(parents=True, exist_ok=True)
        mp3_path.write_bytes(audio)
        return words
    raise VoiceError(
        f"edge-tts 合成两次均失败：{last_err}\n"
        "  排查顺序：① 音色名可能失效/拼错（微软会下线音色）——"
        "`uv run edge-tts --list-voices | grep zh-CN` 核对，或改主题 voice 块换音色；"
        "② 网络能否到微软云（speech.platform.bing.com）；"
        "③ NoAudioReceived 多为微软侧瞬时故障，隔几分钟重试即可。")


def _concat_mp3(parts: list[Path], out: Path) -> None:
    """concat demuxer 拼整片旁白（重编码保证时间戳干净无缝）。"""
    out.parent.mkdir(parents=True, exist_ok=True)
    lst = out.with_suffix(".list.txt")
    lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts),
                   encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c:a", "libmp3lame", "-q:a", "2", str(out)],
                   check=True, capture_output=True, text=True)
    lst.unlink(missing_ok=True)


def load_script(script: dict | str | Path) -> list[dict]:
    """归一化脚本入参 → scenes 列表（dict 或 script.json 路径均可）。"""
    data = json.loads(Path(script).read_text(encoding="utf-8")) \
        if isinstance(script, (str, Path)) else script
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if not scenes or not isinstance(scenes, list):
        raise VoiceError("脚本缺少 scenes[]，或不是合法 script.json")
    for i, sc in enumerate(scenes):
        if not str(sc.get("narration", "")).strip():
            raise VoiceError(f"scenes[{i}] 缺 narration 文本")
    return scenes


def make_voice(script: dict | str | Path, episode_dir: Path,
               voice: str = "zh-CN-YunxiNeural",
               rate: str = "+0%", volume: str = "+0%", pitch: str = "+0Hz",
               ) -> dict:
    """逐幕 edge-tts 合成 → 三件套 + input/script.json 落盘。

    scene_index 以脚本顺序为准，id 缺省补 scene-XX。脚本不管以 dict 还是以
    路径传入，都会在合成成功后回写（幂等：内容相同则不重写）到
    input/script.json——标注器（make_annotations_v2）要吃它的短语表，
    缺了它下游全幕退均分，「视觉顺序=讲解顺序」就断了。

    返回 {"words_json":…, "narration":…, "srt":…, "script":…,
          "durations_ms":[…], "total_ms":N, "word_count":n}
    """
    if isinstance(script, (str, Path)):
        doc = json.loads(Path(script).read_text(encoding="utf-8"))
        src_path: Path | None = Path(script)
    else:
        doc = script
        src_path = None
    scenes = load_script(doc)          # 校验 scenes[]/narration
    for i, sc in enumerate(scenes):    # 幕 id 归一化后写回脚本，保证单一事实源
        sc.setdefault("id", f"scene-{i + 1:02d}")
    ep = Path(episode_dir)
    scene_audio_dir = ep / "build" / "voice" / "scenes"
    inp = ep / "input"
    inp.mkdir(parents=True, exist_ok=True)

    words: list[dict] = []
    windows: list[dict] = []
    part_paths: list[Path] = []
    cursor_ms = 0
    durations: list[int] = []

    for idx, sc in enumerate(scenes):
        sid = sc["id"]
        part = scene_audio_dir / f"{sid}.mp3"
        rel_words = asyncio.run(_synth_scene(str(sc["narration"]).strip(), part,
                                             voice, rate, volume, pitch))
        actual_ms = _ffprobe_duration_ms(part)          # 结构真值：实际音频时长
        # 该幕音频元数据里最晚词尾超出实际时长时，以实际时长收口（防负 tail / 越窗）
        for w in rel_words:
            w["end_ms"] = min(int(w["end_ms"]), actual_ms)
        for w in rel_words:
            words.append({"scene_index": idx,
                          "text": w["text"],
                          "start_ms": cursor_ms + int(w["start_ms"]),
                          "end_ms": cursor_ms + int(w["end_ms"])})
        windows.append({"scene_index": idx, "start_ms": cursor_ms,
                        "end_ms": cursor_ms + actual_ms})
        part_paths.append(part)
        durations.append(actual_ms)
        cursor_ms += actual_ms

    _concat_mp3(part_paths, inp / "narration.mp3")
    sents = aggregate_sentences(words)
    write_srt(sents, inp / "captions.srt")
    payload = {"version": WORD_JSON_VERSION, "voice": voice,
               "granularity": "word", "duration_ms": cursor_ms,
               "scenes": windows, "words": words}
    (inp / "words.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
    # script.json 回写（幂等，内容相同不重写）：标注器的短语表事实源
    spath = inp / "script.json"
    desired = json.dumps(doc, ensure_ascii=False, indent=2)
    if not (src_path and src_path.resolve() == spath.resolve()) \
            and (not spath.exists()
                 or spath.read_text(encoding="utf-8") != desired):
        spath.write_text(desired, encoding="utf-8")
    got_total = _ffprobe_duration_ms(inp / "narration.mp3")
    if abs(got_total - cursor_ms) > 150:
        raise VoiceError(f"拼接旁白时长 {got_total}ms 与分幕累计 {cursor_ms}ms 差 >150ms，"
                         "检查 concat 产物是否完整")
    return {"words_json": inp / "words.json", "narration": inp / "narration.mp3",
            "srt": inp / "captions.srt", "script": spath, "durations_ms": durations,
            "total_ms": cursor_ms, "word_count": len(words)}


# ---------------------------------------------------------------- 接入已有配音

_NORM_RE = re.compile(r"[\s\u3000，。！？!?；;、：:…—·「」『』（）()\[\]{}\"'“”‘’,.]+")


def _norm(text: str) -> str:
    return _NORM_RE.sub("", text)


def _assign_cues_to_scenes(cues: list[dict], scenes_narrations: list[str] | None,
                           total_ms: int) -> tuple[list[dict], list[dict]]:
    """把 SRT cue 分配到幕窗口。

    有脚本台词时：按规范化文本做「逐幕消耗式包含匹配 + 时序单调指针」——每幕
    维护一个已消耗游标，cue 只匹配各幕剩余部分，同幕多句才能顺序推进，不会
    全部卡在第 0 幕；归属不上的 cue 跟随当前幕。SRT 时间本身是真实语音证据，
    这里只做归属，不发明时间点。无脚本时全部记入第 0 幕。
    幕窗口 = 各幕首末 cue 边界，并把幕间空隙折给前一幕（首幕吸收到 0，
    末幕吸收到总时长）。
    """
    n = len(scenes_narrations) if scenes_narrations else 1
    ptr = 0                      # 当前归属幕（只前进）
    normed = [_norm(t) for t in (scenes_narrations or [""] * n)]
    cursor = [0] * n             # 每幕已消耗到的规范化下标
    groups: list[list[dict]] = [[] for _ in range(n)]
    for c in cues:
        if scenes_narrations:
            cur = _norm(c["text"])
            hit = None
            if cur:
                for j in range(ptr, n):
                    pos = normed[j].find(cur, cursor[j])
                    if pos >= 0:
                        hit = j
                        cursor[j] = pos + len(cur)
                        break
            if hit is not None:
                ptr = hit
        c["scene_index"] = ptr   # 指针归属是唯一事实源（不做时间窗二次划分）
        groups[ptr].append(c)
    last_end = max((c["end_ms"] for c in cues), default=0)

    win: list[dict] = []
    for i in range(n):
        s = min((c["start_ms"] for c in groups[i]), default=None)
        e = max((c["end_ms"] for c in groups[i]), default=s)
        if s is None:            # 该幕一句都没归属到：顶在前一幕尾后
            s = win[-1]["end_ms"] if win else 0
            e = s
        win.append({"scene_index": i, "start_ms": s, "end_ms": e})
    # 首尾吸收 + 把幕间无话空隙折给前一幕（保证窗口连续覆盖全片）
    if win:
        win[0]["start_ms"] = 0
        win[-1]["end_ms"] = total_ms if total_ms > 0 else max(last_end, win[-1]["end_ms"])
        for i in range(1, len(win)):
            if win[i - 1]["end_ms"] < win[i]["start_ms"]:
                win[i - 1]["end_ms"] = win[i]["start_ms"]
            win[i]["start_ms"] = max(win[i - 1]["end_ms"], win[i]["start_ms"])
            if win[i]["end_ms"] < win[i]["start_ms"]:
                win[i]["end_ms"] = win[i]["start_ms"]
    return win, cues


def attach_audio(audio_path: Path, srt_path: Path, episode_dir: Path,
                 script: dict | str | Path | None = None) -> dict:
    """接入已有配音：narration.mp3 + captions.srt 必产出，words.json 由 SRT 充当
    句级粗粒度词表（granularity="sentence"，每条 cue 一个条目，无词级伪造）。

    script 提供时可按各幕 narration 的规范化包含关系把 cue 归属到幕，得到幕窗口；
    不提供则整体记为单一幕（scene_index=0），由人工在标注层知悉降级范围。
    """
    ep = Path(episode_dir)
    inp = ep / "input"
    inp.mkdir(parents=True, exist_ok=True)
    audio_path, srt_path = Path(audio_path), Path(srt_path)

    narration = inp / "narration.mp3"
    total_ms: int | None = None
    if audio_path.resolve() != narration.resolve():
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio_path),
                        "-c:a", "libmp3lame", "-q:a", "2", str(narration)],
                       check=True, capture_output=True, text=True)
    if not _has_audio_stream(narration):
        raise VoiceError(f"接入的音频没有音轨：{audio_path}")
    total_ms = _ffprobe_duration_ms(narration)

    cues = parse_srt(srt_path)
    narrations = [str(sc.get("narration", "")).strip()
                  for sc in load_script(script)] if script is not None else None
    windows, words_cues = _assign_cues_to_scenes(
        [dict(c) for c in cues], narrations, total_ms)

    write_srt(cues, inp / "captions.srt")     # 统一口径重写一份到 input/
    payload = {"version": WORD_JSON_VERSION, "voice": "external",
               "granularity": "sentence", "duration_ms": total_ms,
               "scenes": windows, "words": words_cues}
    (inp / "words.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
    return {"words_json": inp / "words.json", "narration": narration,
            "srt": inp / "captions.srt", "total_ms": total_ms,
            "cue_count": len(words_cues), "granularity": "sentence"}


# ---------------------------------------------------------------- 口播指纹

FINGERPRINT_FILES = ("narration.mp3", "captions.srt", "words.json")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def compute_voice_fingerprints(input_dir: Path) -> dict[str, str]:
    """三件套 sha256 → 供第一次确认时写入 state["voice_fingerprints"]。"""
    d = Path(input_dir)
    missing = [f for f in FINGERPRINT_FILES if not (d / f).exists()]
    if missing:
        raise VoiceError(f"口播指纹缺文件：{missing}（先跑 make_voice/attach_audio）")
    return {f: sha256_file(d / f) for f in FINGERPRINT_FILES}


if __name__ == "__main__":
    raise SystemExit("voice.py 是库模块：make_voice/attach_audio 请经 smoke 或管线脚本调用")
