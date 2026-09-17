"""板图提示词：主题风格块 + 本幕叙事。不调用任何生图后端。

宿主（Claude Code / Codex / DSH 等）用自己的文生图模型按 prompt 出 PNG。
payload 只描述画面，不含文字。
"""
from __future__ import annotations

import json
from pathlib import Path

WIDTH, HEIGHT = 1920, 1080

# 揭示岛纪律：内核按分区矩形归属笔画，罩不住的笔画会被丢弃，所以板面必须能切成
# n 个互不接触的矩形。生图模型默认爱画贯穿全板的边框、地平线和跨区连线，必须显式禁止。
_ISLAND_RULE = (
    "Composition discipline (hard): this board is drawn to be revealed in {n} separate islands, one after "
    "another. Each island described above is a closed group of marks inside its own stated box. Islands never "
    "touch: leave at least 12% of the board width and 11% of its height of untouched board green between any "
    "two islands, and keep every island at least 5% away from all four edges. No rounded frame, border, box, "
    "table, shelf, ground line, or baseline may run across the whole board or wrap more than one island. An "
    "arrow, line, or connector belongs to exactly one island and stays entirely within that island's box; "
    "never draw a line from one island to another."
)


def load_style_block(theme_dir: Path) -> str:
    f = Path(theme_dir) / "style-block.txt"
    if not f.exists():
        raise FileNotFoundError(f"主题缺 style-block.txt：{f}")
    return f.read_text(encoding="utf-8").strip()


def build_scene_payload(scene_id: str, subject: str, theme_dir: Path,
                        n_islands: int | None = None,
                        character_sheet: str | None = None) -> dict:
    subject = (subject or "").strip()
    if not subject:
        raise ValueError(f"{scene_id} 缺 board_subject")
    parts = [load_style_block(theme_dir)]
    if character_sheet and character_sheet.strip():
        parts.append(character_sheet.strip())
    parts.append(subject)
    if n_islands and n_islands > 1:
        parts.append(_ISLAND_RULE.format(n=n_islands))
    parts.append("画面里不要出现可读文字、字母、数字、品牌标识或水印；"
                 "不要画从画面边缘伸入的手臂或持笔、持粉笔的手部特写；"
                 "允许无文字的箭头、气泡、曲线、节点、人物图标和图示，"
                 "画面里人物自身的面部和手部正常表现即可。")
    prompt = "\n".join(parts)
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
