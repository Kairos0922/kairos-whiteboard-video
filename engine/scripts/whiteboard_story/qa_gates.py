"""成片质量闸口（SKILL.md 自检协议的机器侧）：数值 / 运动 / 缺墨 / 切幕 / 残影 + 接触表。

设计原则：感知类缺陷（扫荡、手空转、残影）不能只靠人眼终检——每条闸口都给出
可复跑的数值判据；人审接触表由本模块统一产出，帧率写死（首幕 2fps、其余 1fps），
杜绝"1fps 漏检扫荡"重演。纯判据函数不依赖 ffmpeg，便于单测。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

W, H = 1920, 1080
GHOST_ROI = (502, 930)          # 残影度量带：避开顶部留白与底部字幕
GHOST_MAX_DEV = 24.0            # 切点后 0.8s 板面应只剩新幕底色：均差超此值=上一幕残影
WIPE_MAX_FRAME = 12.0           # 切幕窗内单帧均差上限：超=硬切（应走 700ms 擦黑板淡入）
WIPE_MIN_CUM = 8.0              # 切幕窗首尾累计均差下限：低于=切点前后画面没换
INK_TH = 160                    # 真墨口径（三通道绝对差和）：低于此值算淡边/晕，不计缺墨
INK_MISSING_MAX = 0.01          # 幕末真墨缺墨率上限：超=有笔画被调度丢弃
SWEEP_WINDOW_MS = 2000          # 扫荡审计滑窗：窗内 travel>800ms 且 draw 弧长<60px = 手在
SWEEP_TRAVEL_MS = 800           # 动而墨不长（填色误判/碎段扫荡的机器判据）
SWEEP_DRAW_ARC = 60.0
LUFS_TARGET = (-16.5, -15.5)    # −16 LUFS ±0.5
TP_TARGET = (-2.0, -1.0)        # −1.5 dBTP ±0.5
SILENCE_NOISE_DB = -35
SILENCE_MIN_DUR = 2.0


# ---------------------------------------------------------------- 纯判据（单测覆盖）

def sweep_windows(tasks, dur_ms: int, window_ms: int = SWEEP_WINDOW_MS,
                  travel_ms: int = SWEEP_TRAVEL_MS, draw_arc: float = SWEEP_DRAW_ARC) -> int:
    """任务表扫荡窗计数：滑窗内手可见地移动却几乎不长墨。"""
    n = 0
    for t0 in range(0, max(int(dur_ms) - window_ms, 0), 500):
        win = [t for t in tasks if t.start_ms >= t0 and t.start_ms < t0 + window_ms]
        d_arc = sum(t.length for t in win if t.kind == "draw")
        t_ms = sum(t.end_ms - t.start_ms for t in win if t.kind == "travel")
        if d_arc < draw_arc and t_ms > travel_ms:
            n += 1
    return n


def wipe_metrics(frames_gray: np.ndarray) -> tuple[float, float]:
    """切幕窗逐帧灰度序列 → (单帧最大均差, 首尾累计均差)。"""
    if len(frames_gray) < 2:
        return 0.0, 0.0
    d = [float(np.abs(frames_gray[i + 1] - frames_gray[i]).mean())
         for i in range(len(frames_gray) - 1)]
    return max(d), float(np.abs(frames_gray[-1] - frames_gray[0]).mean())


def ghost_dev(frame_rgb: np.ndarray, bg: tuple[int, int, int]) -> float:
    """切点后板面与新品底色的均差：残影（上一幕墨迹未擦净）会显著抬高它。"""
    roi = frame_rgb[GHOST_ROI[0]:GHOST_ROI[1]]
    return float(np.abs(roi - np.array(bg, np.int16)).mean())


def missing_ink_ratio(ink_board: np.ndarray, ink_frame: np.ndarray) -> float:
    """幕末仍缺的板图真墨比例（调度丢笔画的判据）。"""
    return float((ink_board & ~ink_frame).sum()) / max(int(ink_board.sum()), 1)


def parse_lufs(summary: str) -> tuple[float | None, float | None]:
    """ebur128 Summary 文本 → (I LUFS, true peak dBTP)。"""
    m = re.search(r"I:\s+(-?[\d.]+)\s+LUFS", summary)
    p = re.search(r"Peak:\s+(-?[\d.]+)\s+dBFS", summary)
    return (float(m.group(1)) if m else None, float(p.group(1)) if p else None)


# ---------------------------------------------------------------- ffmpeg 解码

def _ffmpeg(args: list[str]) -> bytes:
    p = subprocess.run(["ffmpeg", "-v", "error"] + args, capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败：{p.stderr.decode('utf-8', 'replace')[:400]}")
    return p.stdout


def decode_gray(mp4: Path, t0: float, dur: float) -> np.ndarray:
    raw = _ffmpeg(["-ss", f"{t0:.3f}", "-i", str(mp4), "-t", f"{dur:.3f}",
                   "-vf", "format=gray", "-f", "rawvideo", "-"])
    a = np.frombuffer(raw, np.uint8)
    n = len(a) // (W * H)
    return a[: n * W * H].reshape(n, H, W).astype(np.int16)


def decode_rgb(mp4: Path, t: float) -> np.ndarray:
    raw = _ffmpeg(["-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1",
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(np.int16)


# ---------------------------------------------------------------- 各闸口

def scene_bounds(ep: Path) -> list[tuple[str, float, float]]:
    from build_video import _scene_durations
    bounds, t = [], 0.0
    for sid, sec in sorted(_scene_durations(ep).items()):
        bounds.append((sid, t, t + float(sec)))
        t += float(sec)
    return bounds


def check_spec(mp4: Path) -> list[str]:
    out = _ffmpeg_probe(mp4)
    bad = []
    if "h264" not in out or "1920" not in out or "1080" not in out or "yuv420p" not in out:
        bad.append(f"视频流规格不符：{out.strip()[:120]}")
    if "aac" not in out or "44100" not in out:
        bad.append(f"音频流规格不符：{out.strip()[:120]}")
    atoms = _top_atoms(mp4)
    if "moov" not in atoms or "mdat" not in atoms or atoms.index("moov") > atoms.index("mdat"):
        bad.append(f"非 faststart（atom 序 {atoms}）")
    return bad


def _ffmpeg_probe(mp4: Path) -> str:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_name,width,height,pix_fmt,sample_rate",
                        "-of", "default=nw=1", str(mp4)], capture_output=True)
    return p.stdout.decode()


def _top_atoms(mp4: Path) -> list[str]:
    data = mp4.read_bytes()
    atoms, i = [], 0
    while i + 8 <= len(data) and len(atoms) < 8:
        sz = int.from_bytes(data[i:i + 4], "big")
        if sz < 8:
            break
        atoms.append(data[i + 4:i + 8].decode("latin1"))
        i += sz
    return atoms


def check_audio(mp4: Path) -> list[str]:
    bad = []
    p = subprocess.run(["ffmpeg", "-v", "info", "-i", str(mp4),
                        "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True)
    log = p.stderr.decode("utf-8", "replace")
    lufs, tp = parse_lufs(log[log.find("Summary:"):])
    if lufs is None or not (LUFS_TARGET[0] <= lufs <= LUFS_TARGET[1]):
        bad.append(f"响度 {lufs} LUFS 超出 {LUFS_TARGET}")
    if tp is None or not (TP_TARGET[0] <= tp <= TP_TARGET[1]):
        bad.append(f"真峰 {tp} dBTP 超出 {TP_TARGET}")
    q = subprocess.run(["ffmpeg", "-v", "info", "-i", str(mp4),
                        "-af", f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_DUR}",
                        "-f", "null", "-"], capture_output=True)
    n = q.stderr.decode("utf-8", "replace").count("silence_start")
    if n:
        bad.append(f"死寂 {n} 段（{SILENCE_NOISE_DB}dB/{SILENCE_MIN_DUR}s）")
    return bad


def check_wipe_ghost(mp4: Path, bounds, bg_by_sid: dict[str, tuple[int, int, int]]):
    bad, rows = [], []
    for (sid, _s, e), (nxt, _ns, _ne) in zip(bounds, bounds[1:]):
        g = decode_gray(mp4, e - 0.15, 1.20)
        hard, cum = wipe_metrics(g)
        dev = ghost_dev(decode_rgb(mp4, e + 0.80), bg_by_sid[nxt])
        rows.append(f"  切点 {e:8.3f}s  单帧跳变 {hard:5.2f}  窗累计 {cum:5.2f}  残影 {dev:5.2f}")
        if hard >= WIPE_MAX_FRAME:
            bad.append(f"{sid}→{nxt} 切幕硬切（单帧跳变 {hard:.1f} ≥ {WIPE_MAX_FRAME}）")
        if cum < WIPE_MIN_CUM:
            bad.append(f"{sid}→{nxt} 切点前后画面未换（累计 {cum:.1f} < {WIPE_MIN_CUM}）")
        if dev >= GHOST_MAX_DEV:
            bad.append(f"{nxt} 幕首残影 {dev:.1f} ≥ {GHOST_MAX_DEV}（上一幕墨迹未擦净）")
    return bad, rows


def check_ink(ep: Path, mp4: Path, bounds):
    import cv2
    from whiteboard_story import kernel as K
    bad, rows = [], []
    for sid, _s, e in bounds:
        fr = decode_rgb(mp4, max(e - 0.4, 0.0))
        bd = cv2.cvtColor(cv2.imread(str(ep / f"build/boards-layout/{sid}.raw.png")),
                          cv2.COLOR_BGR2RGB).astype(np.int16)
        bg = _bg_of(bd)
        ratio = missing_ink_ratio(np.abs(bd - bg).sum(2) > INK_TH,
                                  np.abs(fr - bg).sum(2) > INK_TH)
        rows.append(f"  {sid} 幕末真墨缺墨 {ratio * 100:5.2f}%")
        if ratio > INK_MISSING_MAX:
            bad.append(f"{sid} 幕末缺墨 {ratio * 100:.1f}% > {INK_MISSING_MAX * 100:.0f}%（调度丢笔画）")
    return bad, rows


def _bg_of(img: np.ndarray) -> np.ndarray:
    from whiteboard_story.kernel import estimate_bg
    return np.array(estimate_bg(img.astype(np.uint8)), np.int16)


def check_sweep(ep: Path):
    from whiteboard_story import kernel as K
    bad, rows = [], []
    for sid, _s, e in scene_bounds(ep):
        board, _ink, skel = K.load_board_layers(ep / f"build/boards-layout/{sid}.raw.png")
        h, w = board.shape[:2]
        ann = K.parse_annotation(ep / f"build/annotations/{sid}.annotation.json")
        content = [x for x in ann.elements if x.eid != "layout"]
        tasks = K.build_tasks(content, board, K._trace_merged(skel, (w, h)), skeleton=skel)
        n = sweep_windows(tasks, int(e * 1000) - int(_s * 1000))
        rows.append(f"  {sid} 任务 {len(tasks):4d}  扫荡窗 {n}")
        if n:
            bad.append(f"{sid} 任务表扫荡窗 {n} 个（手可见地移动而墨不长）")
    return bad, rows


def make_sheets(mp4: Path, bounds, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, (sid, s, e) in enumerate(bounds):
        fps = 2 if i == 0 else 1
        n = int((e - s) * fps)
        tile = "8x8" if n > 49 else "7x7"
        out = out_dir / f"sheet_{sid}.png"
        _ffmpeg(["-y", "-ss", f"{s:.3f}", "-i", str(mp4), "-t", f"{e - s - 0.2:.3f}",
                 "-vf", f"fps={fps},scale=480:270,tile={tile}", "-frames:v", "1", str(out)])
        paths.append(out)
    return paths


# ---------------------------------------------------------------- 汇总

def run_all(ep: Path, sheets_dir: Path | None = None, quick: bool = False):
    from whiteboard_story.kernel import estimate_bg
    import cv2
    ep = Path(ep)
    mp4 = ep / "deliverables" / "final.mp4"
    if not mp4.exists():
        return [f"缺成片 {mp4}"], [], []
    bounds = scene_bounds(ep)
    bg_by_sid = {}
    for sid, _s, _e in bounds:
        img = cv2.cvtColor(cv2.imread(str(ep / f"build/boards-layout/{sid}.raw.png")),
                           cv2.COLOR_BGR2RGB)
        bg_by_sid[sid] = estimate_bg(img)
    bad, rows = [], []
    bad += check_spec(mp4)
    if not quick:
        bad += check_audio(mp4)
    b, r = check_sweep(ep)
    bad += b
    rows += ["扫荡审计（任务表）："] + r
    b, r = check_wipe_ghost(mp4, bounds, bg_by_sid)
    bad += b
    rows += ["切幕/残影："] + r
    b, r = check_ink(ep, mp4, bounds)
    bad += b
    rows += ["幕末缺墨（真墨口径）："] + r
    if sheets_dir:
        paths = make_sheets(mp4, bounds, Path(sheets_dir))
        rows += [f"接触表（首幕 2fps、其余 1fps）：{p} " for p in paths]
    return bad, [], rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="成片质量闸口（数值/运动/缺墨/切幕/残影+接触表）")
    ap.add_argument("--episode-dir", required=True)
    ap.add_argument("--sheets-dir", default=None, help="产出人审接触表的目录")
    ap.add_argument("--quick", action="store_true", help="跳过响度/死寂（慢闸）")
    args = ap.parse_args(argv)
    bad, _warn, rows = run_all(Path(args.episode_dir).resolve(), args.sheets_dir, args.quick)
    print("\n".join(rows))
    if bad:
        print(f"qa_gates：阻断 {len(bad)} 项")
        for x in bad:
            print(f"  ✗ {x}")
        return 1
    print("qa_gates：全过")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.exit(main())
