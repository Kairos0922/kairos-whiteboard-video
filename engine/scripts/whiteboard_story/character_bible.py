"""角色身份圣经：跨场景复用的稳定角色描述。

原则：
- 角色 ID 是跨幕稳定键；
- immutable 字段是不可随幕变化的视觉锚点；
- allowed_variations 只允许姿势、表情、视角和剧情道具等受控变化；
- 可选 reference_image 用于宿主模型做图像参考，但渲染引擎不依赖它。
"""
from __future__ import annotations

import json
from pathlib import Path


SCHEMA = "whiteboard-story/characters@2"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_characters(episode_dir: Path) -> list[dict]:
    """优先 input/characters.json，兼容旧 input/characters.txt。"""
    root = Path(episode_dir)
    path = root / "input" / "characters.json"
    data = _read_json(path)
    if data is not None:
        chars = data.get("characters") or []
        if isinstance(chars, list):
            return [c for c in chars if isinstance(c, dict)]
        return []

    legacy = root / "input" / "characters.txt"
    if legacy.exists():
        text = legacy.read_text(encoding="utf-8").strip()
        if text:
            return [{
                "id": "legacy-character-sheet",
                "name": "Legacy Character Sheet",
                "immutable": {"description": text},
                "allowed_variations": ["pose", "expression", "view_angle", "story_props"],
            }]
    return []


def _as_list(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    return []


def reference_images_for_character(episode_dir: Path, character: dict) -> list[Path]:
    root = Path(episode_dir).resolve()
    raw = character.get("reference_images") or character.get("reference_image")
    paths: list[Path] = []
    for item in _as_list(raw):
        p = Path(item).expanduser()
        if not p.is_absolute():
            p = root / p
        paths.append(p.resolve())
    return paths


def canonical_sheet_path(episode_dir: Path) -> Path:
    return (Path(episode_dir) / "input" / "character-sheet.png").resolve()


def validate_canonical_sheet(episode_dir: Path) -> list[str]:
    """校验项目级 canonical character sheet；它是跨幕身份的视觉母版。"""
    path = canonical_sheet_path(episode_dir)
    if not path.exists():
        return [f"缺 canonical character sheet：{path}；先运行 character-sheet 并导入一张母版图"]
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        return [f"canonical character sheet 格式不支持：{path.name}"]
    try:
        from PIL import Image
        with Image.open(path) as img:
            if img.width < 512 or img.height < 512:
                return [f"canonical character sheet 分辨率过低：{img.size}（至少 512×512）"]
            img.verify()
    except Exception as exc:
        return [f"canonical character sheet 无法读取：{path}：{exc}"]
    return []


def validate_character_references(episode_dir: Path, chars: list[dict]) -> list[str]:
    """验证可选的单角色参考图；canonical sheet 是必须的项目级母版。"""
    errors: list[str] = []
    for c in chars:
        cid = str(c.get("id") or "").strip()
        refs = reference_images_for_character(episode_dir, c)
        for ref in refs:
            if not ref.exists():
                errors.append(f"{cid} 参考图不存在：{ref}")
            elif ref.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                errors.append(f"{cid} 参考图格式不支持：{ref.name}")
    return errors


def validate_characters(chars: list[dict]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for i, c in enumerate(chars):
        cid = str(c.get("id") or "").strip()
        if not cid:
            errors.append(f"角色[{i}] 缺 id")
            continue
        if cid in seen:
            errors.append(f"角色 id 重复：{cid}")
        seen.add(cid)
        immutable = c.get("immutable")
        if not isinstance(immutable, dict) or not immutable:
            errors.append(f"{cid} 缺 immutable 视觉锚点")
    return errors


def render_prompt_block(chars: list[dict], character_ids: list[str] | None = None) -> str:
    """生成跨场景复用的强约束角色块；不要求模型创建未被场景引用的角色。"""
    if not chars:
        return ""

    wanted = set(str(x) for x in (character_ids or []) if str(x).strip())
    selected = [c for c in chars if not wanted or str(c.get("id")) in wanted]
    if not selected:
        selected = chars

    lines = [
        "CHARACTER CONSISTENCY LOCK — HARD:",
        "Character IDs are persistent across the entire video. Never redesign an existing character.",
        "For every referenced character, preserve the same head shape, hair silhouette, hair color, skin tone,",
        "eye style, glasses/accessory shape, outfit silhouette, dominant colors, and body proportions in every scene.",
        "Allowed variation is limited to pose, gesture, facial expression, camera/view angle, and scene-specific props.",
        "Do not swap colors, change hairstyle, replace glasses, change clothing family, age the character, or turn",
        "the character into a different art style. If a character is tiny, simplify details by reduction only;",
        "do not invent a new face. Keep the identity anchors visible even at small scale.",
    ]

    for c in selected:
        cid = str(c.get("id"))
        name = str(c.get("name") or cid)
        lines.append(f"CHARACTER ID [{cid}] — {name}")
        immutable = c.get("immutable") or {}
        for key, value in immutable.items():
            label = str(key).replace("_", " ")
            lines.append(f"- IMMUTABLE {label}: {value}")
        refs = c.get("reference_images") or c.get("reference_image")
        if refs:
            if isinstance(refs, str):
                refs = [refs]
            lines.append(f"- REFERENCE IMAGES: {', '.join(str(x) for x in refs)}")
        allowed = c.get("allowed_variations") or [
            "pose", "gesture", "facial expression", "view angle", "scene props"
        ]
        lines.append(f"- ALLOWED VARIATIONS ONLY: {', '.join(str(x) for x in allowed)}")
    return "\n".join(lines)


def scene_character_ids(scene: dict) -> list[str]:
    ids: list[str] = []
    raw = scene.get("character_ids") or scene.get("characters") or []
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                ids.append(item)
            elif isinstance(item, dict):
                cid = item.get("id") or item.get("character_id") or item.get("characterId")
                if cid:
                    ids.append(str(cid))
    for el in scene.get("elements") or []:
        if not isinstance(el, dict):
            continue
        cid = el.get("character_id") or el.get("characterId")
        if cid:
            ids.append(str(cid))
    # 保持声明顺序、去重
    return list(dict.fromkeys(ids))


def character_reference_manifest(episode_dir: Path, chars: list[dict], character_ids: list[str] | None = None) -> list[dict]:
    wanted = set(str(x) for x in (character_ids or []) if str(x).strip())
    selected = [c for c in chars if not wanted or str(c.get("id")) in wanted]
    canonical = canonical_sheet_path(episode_dir)
    return [{
        "character_id": str(c.get("id")),
        "name": str(c.get("name") or c.get("id")),
        "reference_images": [str(p) for p in reference_images_for_character(episode_dir, c)],
        "canonical_sheet": str(canonical) if canonical.exists() else None,
        "reference_priority": ["canonical_sheet", "reference_images"],
    } for c in selected]


def build_character_sheet_prompt(chars: list[dict], theme_name: str | None = None) -> str:
    """生成可供宿主模型一次性绘制 canonical character sheet 的提示词。"""
    block = render_prompt_block(chars)
    if not block:
        return ""
    theme_note = f" Theme: {theme_name}." if theme_name else ""
    return (
        "CANONICAL CHARACTER SHEET — HARD REFERENCE MASTER.\n"
        "Create one clean reference sheet containing every character below, three-quarter full body or waist-up, "
        "neutral pose, facing mostly forward, isolated on the exact theme background, with each character clearly "
        "separated. This sheet becomes the canonical appearance reference for later scenes."
        + theme_note + "\n\n" + block
    )


def validate_scene_refs(chars: list[dict], scenes: list[dict]) -> list[str]:
    """检查脚本引用的 character_id 是否都存在于角色圣经。"""
    known = {str(c.get("id")) for c in chars if c.get("id")}
    errors: list[str] = []
    for i, scene in enumerate(scenes):
        sid = str(scene.get("id") or f"scene-{i + 1:02d}")
        refs = scene_character_ids(scene)
        missing = [cid for cid in refs if cid not in known]
        if missing:
            errors.append(f"{sid} 引用了未知 character_id：{', '.join(missing)}")
    return errors
