"""板图提示词：主题风格块 + 本幕叙事。不调用任何生图后端。

宿主（Claude Code / Codex / DSH 等）用自己的文生图模型按 prompt 出 PNG。
payload 只描述画面，不含文字。
"""
from __future__ import annotations

import json
from pathlib import Path

WIDTH, HEIGHT = 1920, 1080


def load_style_block(theme_dir: Path) -> str:
    f = Path(theme_dir) / "style-block.txt"
    if not f.exists():
        raise FileNotFoundError(f"主题缺 style-block.txt：{f}")
    return f.read_text(encoding="utf-8").strip()


def build_scene_payload(scene_id: str, subject: str, theme_dir: Path) -> dict:
    subject = (subject or "").strip()
    if not subject:
        raise ValueError(f"{scene_id} 缺 board_subject")
    prompt = (f"{load_style_block(theme_dir)}\n{subject}\n"
              "画面里不要出现可读文字、字母、数字、品牌标识或水印；"
              "不要画从画面边缘伸入的手臂或持笔、持粉笔的手部特写；"
              "允许无文字的箭头、气泡、曲线、节点、人物图标和图示，"
              "画面里人物自身的面部和手部正常表现即可。")
    return {
        "scene": scene_id,
        "prompt": prompt,
        "width": WIDTH,
        "height": HEIGHT,
        "theme": Path(theme_dir).name,
    }


def probe_payload(theme_dir: Path) -> dict:
    probe = json.loads((Path(theme_dir) / "probe.json").read_text(encoding="utf-8"))
    return build_scene_payload("probe", probe["subject"], theme_dir)
