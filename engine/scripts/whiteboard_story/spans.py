#!/usr/bin/env python3
"""narration_spans 派生（ir-alignment.md §8 迁移第 3 步）。

句级边界不新造机制：把每幕旁白按句切分（。？！!?），每句用
`make_annotations_v2._match_phrase_span` 在该幕 words.json 词单元里做
规范化子串匹配，得到真实语音的 start_ms / end_ms（全局坐标）。
匹配不上的句子记 warning，不伪造边界（principles P2）。

产物：words.json 顶层键 `narration_spans`（{scene_id: [{index, text,
start_ms, end_ms}]}），供后续 reveal↔span 邻接窗校验（§7 第 5 项）与
表达层 spans 核对使用。重复运行幂等覆盖。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# whiteboard_story 内模块互相用平铺名导入（make_annotations_v2 自身 `from apply_layout import …`），
# 这里把包目录挂上 sys.path，保证直接执行与被 workflow 导入两种路径都成立。
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_annotations_v2 import (_match_phrase_span, _word_units,  # noqa: E402
                                 split_sentences)


def derive_scene_spans(units: list[dict], narration: str,
                       warnings: list[str], scene_id: str) -> list[dict]:
    """一幕的 narration_spans；匹配失败的句子不进产物，只记 warning。"""
    out: list[dict] = []
    for i, sentence in enumerate(split_sentences(narration)):
        span = _match_phrase_span(units, sentence)
        if span is None:
            warnings.append(f"{scene_id}：句子「{sentence}」未在 words.json 命中 → 不写入 spans")
            continue
        out.append({"index": i, "text": sentence,
                    "start_ms": int(span[0]), "end_ms": int(span[1])})
    return out


def derive_episode(episode_dir: Path) -> tuple[dict, list[str]]:
    """全期派生；返回 ({scene_id: [span,...]}, warnings)。不改文件。"""
    ep = Path(episode_dir)
    words_path = ep / "input" / "words.json"
    script_path = ep / "input" / "script.json"
    if not words_path.exists():
        raise FileNotFoundError(f"缺 {words_path}（先跑 workflow.py voice）")
    words_doc = json.loads(words_path.read_text(encoding="utf-8"))
    scenes: list[dict] = []
    if script_path.exists():
        scenes = json.loads(script_path.read_text(encoding="utf-8")).get("scenes", [])

    warnings: list[str] = []
    result: dict[str, list[dict]] = {}
    for sc_win in words_doc.get("scenes", []):
        idx = int(sc_win["scene_index"])
        sid = (scenes[idx].get("id") if idx < len(scenes) and scenes[idx].get("id")
               else f"scene-{idx + 1:02d}")
        narration = scenes[idx].get("narration", "") if idx < len(scenes) else ""
        if not narration.strip():
            warnings.append(f"{sid}：脚本无旁白，跳过 spans 派生")
            continue
        units = _word_units(words_doc, idx)
        spans = derive_scene_spans(units, narration, warnings, sid)
        # 边界单调检查：后一句起点不得早于前一句终点（防同词多处命中错位）
        for prev, cur in zip(spans, spans[1:]):
            if cur["start_ms"] < prev["end_ms"]:
                warnings.append(f"{sid}：span{cur['index']} 起点早于前句终点，疑似匹配错位")
        result[sid] = spans
    return result, warnings


def write_spans(episode_dir: Path) -> tuple[dict, list[str]]:
    """派生并幂等写回 words.json 的 narration_spans 键。"""
    ep = Path(episode_dir)
    words_path = ep / "input" / "words.json"
    result, warnings = derive_episode(ep)
    words_doc = json.loads(words_path.read_text(encoding="utf-8"))
    words_doc["narration_spans"] = result
    words_path.write_text(json.dumps(words_doc, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    return result, warnings


def main() -> int:
    ap = argparse.ArgumentParser(description="派生 narration_spans 并写回 words.json")
    ap.add_argument("--episode-dir", required=True, type=Path)
    args = ap.parse_args()
    result, warnings = write_spans(args.episode_dir)
    for sid, spans in result.items():
        if not spans:
            continue
        print(f"OK {sid}  {len(spans)} spans  {spans[0]['start_ms']}-{spans[-1]['end_ms']}ms")
    for wmsg in warnings:
        print(f"  ! {wmsg}")
    return 0 if not warnings else 1


if __name__ == "__main__":
    raise SystemExit(main())
