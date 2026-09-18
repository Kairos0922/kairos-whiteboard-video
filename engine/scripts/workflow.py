#!/usr/bin/env python3
"""白板叙事引擎入口。确定性操作都从这里进。

用法：
  python workflow.py init            --episode-dir <dir> --title <title> [--scenes N]
  python workflow.py status          --episode-dir <dir>
  python workflow.py sync-boards     --episode-dir <dir>
      # 按 input/script.json 的幕数重写 state.boards（幕数跟脚本走）；先跑 lint，缺 IR 即阻断
  python workflow.py voice           --episode-dir <dir> [--script <file>] [--voice NAME]
                                     [--rate X] [--theme <theme-dir>] [--force]
  python workflow.py confirm-voice   --episode-dir <dir>
  python workflow.py prompts         --episode-dir <dir> --theme <theme-dir> [--scene id]
      # 打出宿主模型要用的板图 prompt（不生图）。全部幕一次性批量出图、批量确认。
  python workflow.py probe           --theme <theme-dir>
      # 主题探针 prompt。验证画风用；探针图为临时产物，不入主题包。
  python workflow.py lint            --episode-dir <dir>
      # 编译器 IR 静态校验：knowledge_model / learner_model(transitions) / beats(reveal 操作、
      # 通道分配、元素职责) + P5「Beat 数 = 转变数」。有阻断项退出码 1。
  python workflow.py spans           --episode-dir <dir>
      # 派生 narration_spans（句级边界自 words.json 词单元匹配），幂等写回 words.json。
  python workflow.py import          --episode-dir <dir> --boards-dir <dir> [--theme <theme-dir>]
      # 比例正确的板图等比缩放到 1920×1080，清右下角水印，逐张 check_board
  python workflow.py render          --episode-dir <dir>   # 闸门：boards_reviewed
  python workflow.py validate        --episode-dir <dir>
      # 交付前闸门（whiteboard_story/validate.py），有阻断项退出码 1

三次确认（质量门）——state.json.confirmations 的唯一写入口，按顺序过：
  python workflow.py confirm-content --episode-dir <dir>
      # 第1次：内容与方向。script.json 存在且 lint 零阻断才放行；
      # 同步置 express_card_filled / script_audio_confirmed（脚本确认即音频内容确认）
  python workflow.py confirm-visual  --episode-dir <dir>
      # 第2次：视觉方案。全部板图自动检查 ok 且 annotated=true 才放行；同步置 boards_reviewed
  python workflow.py confirm-final   --episode-dir <dir>
      # 第3次：最终产物。deliverables/final.mp4 存在才放行；同步置 finalized
  # 旧命令 confirm-boards 等价于 confirm-visual（不含 annotated 检查），保留兼容旧期次。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from whiteboard_story import character_bible, ir_contract, prompt_builder, review_images  # noqa: E402

SCHEMA = "whiteboard-story-video/state@2"
EXPRESS_TEMPLATE = Path(__file__).resolve().parents[1] / "assets/templates/express-card.template.md"
ENGINE_VOICE = Path(__file__).resolve().parents[1] / "defaults/voice.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="minutes")


def _write_state(root: Path, state: dict) -> None:
    state["updated"] = _now()
    (root / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2),
                                     encoding="utf-8")


def _load_state_or_fail(episode_dir: Path) -> dict | None:
    state_path = episode_dir / "state.json"
    if not state_path.exists():
        print("未初始化：先跑 workflow.py init")
        return None
    state = json.loads(state_path.read_text(encoding="utf-8"))
    _migrate_confirmations(state)
    return state


def _migrate_confirmations(state: dict) -> None:
    """兼容旧格式：confirmations 从列表（确认历史）迁移为 dict（质量门标志）。
    旧列表移到 confirmation_log，confirmations 改为 dict。
    """
    raw = state.get("confirmations")
    if isinstance(raw, list):
        state["confirmations"] = {}
        state["confirmation_log"] = raw
    elif not isinstance(raw, dict):
        state["confirmations"] = {}
    state.setdefault("confirmation_log", [])


def _scene_ids_from_script(episode_dir: Path) -> list[str]:
    script = episode_dir / "input" / "script.json"
    if not script.exists():
        return []
    doc = json.loads(script.read_text(encoding="utf-8"))
    ids = []
    for i, sc in enumerate(doc.get("scenes", [])):
        ids.append(sc.get("id") or f"scene-{i + 1:02d}")
    return ids


def _board_stub(sid: str) -> dict:
    return {"scene": sid, "file": None, "checks": None, "status": "pending"}


def _sync_boards_list(state: dict, ids: list[str]) -> None:
    by = {b["scene"]: b for b in state.get("boards", [])}
    state["boards"] = [by.get(sid) or _board_stub(sid) for sid in ids]


def cmd_init(episode_dir: Path, title: str, args) -> int:
    episode_dir.mkdir(parents=True, exist_ok=True)
    for sub in ("input", "build/boards", "build/annotations", "build/scenes",
                "deliverables", "assets"):
        (episode_dir / sub).mkdir(parents=True, exist_ok=True)
    state_path = episode_dir / "state.json"
    if state_path.exists():
        print("state.json 已存在，跳过 init（如需重来先人工处理该文件）")
        return 0
    express = episode_dir / "input" / "express-card.md"
    if EXPRESS_TEMPLATE.exists() and not express.exists():
        express.write_text(EXPRESS_TEMPLATE.read_text(encoding="utf-8")
                           .replace("{{TITLE}}", title)
                           .replace("{{DATE}}", _now()[:10]), encoding="utf-8")
    # 角色圣经：项目级永久身份键。存在即复用，不按幕重新发明角色。
    chars_template = Path(__file__).resolve().parents[1] / "assets/templates/characters.json"
    chars_path = episode_dir / "input" / "characters.json"
    if chars_template.exists() and not chars_path.exists():
        chars_path.write_text(chars_template.read_text(encoding="utf-8"), encoding="utf-8")
    n = getattr(args, "scenes", None)
    if n is not None and n < 1:
        print("--scenes 必须 ≥ 1")
        return 1
    ids = [f"scene-{i:02d}" for i in range(1, n + 1)] if n else []
    state = {
        "schema": SCHEMA,
        "episode_dir": str(episode_dir),
        "title": title,
        "created": _now(), "updated": _now(),
        # 三次确认（质量门）：方向→视觉→交付
        "confirmations": {
            "content_confirmed": False,   # 第1次：内容与方向（大纲+脚本+主题）
            "visual_confirmed": False,    # 第2次：视觉方案（全部场景图批量确认）
            "final_confirmed": False,     # 第3次：最终产物（视频交付确认）
        },
        # 底层操作状态（兼容旧流程，用于跟踪各步骤执行情况）
        "phases": {
            "express_card_filled": False,
            "script_audio_confirmed": False,
            "boards_generated": False, "boards_reviewed": False,
            "annotated": False, "rendered": False, "finalized": False,
        },
        "boards": [_board_stub(s) for s in ids],
        "confirmation_log": [],
    }
    _write_state(episode_dir, state)
    print(f"init ok: {state_path}")
    if ids:
        print(f"预留 {len(ids)} 幕；脚本写完后跑 sync-boards 以脚本为准")
    else:
        print("幕数未预留：写完 input/script.json 后跑 sync-boards")
    print(f"第一步：填表达设计卡 {express}（references/script-design.md）")
    return 0


def cmd_status(episode_dir: Path, args) -> int:
    state = _load_state_or_fail(episode_dir)
    if state is None:
        return 1
    conf = state.get("confirmations", {})
    phases = state["phases"]
    print(f"episode: {state['title']}  ({state['episode_dir']})")
    print()
    print("=== 三次确认（质量门）===")
    print(f"  {'✓' if conf.get('content_confirmed') else '○'} 第1次确认：内容与方向（大纲+脚本+主题）")
    print(f"  {'✓' if conf.get('visual_confirmed') else '○'} 第2次确认：视觉方案（全部场景图批量确认）")
    print(f"  {'✓' if conf.get('final_confirmed') else '○'} 第3次确认：最终产物（视频交付）")
    print()
    print("=== 底层操作状态 ===")
    for k, v in phases.items():
        print(f"  {'✓' if v else '·'} {k}")
    n_boards = len(state["boards"])
    n_ok = sum(1 for b in state["boards"] if b["status"] == "ok")
    print(f"boards: {n_ok}/{n_boards} 通过自动检查")
    script_ids = _scene_ids_from_script(episode_dir)
    if script_ids and [b["scene"] for b in state["boards"]] != script_ids:
        print(f"脚本有 {len(script_ids)} 幕，state.boards 不一致，跑 sync-boards")
    print()
    print("=== 下一步 ===")
    if not conf.get("content_confirmed"):
        print("第1次确认：AI 编译知识→生成脚本+推荐主题 → 用户确认内容与方向")
        print("  （填表达设计卡 → 写 script.json → lint 通过 → 用户确认）")
    elif not conf.get("visual_confirmed"):
        print("第2次确认：AI 批量生成全部场景图 → layout→annotate → 用户批量确认视觉")
        print("  （prompts → 宿主批量出图 → import → layout → annotate → 用户确认）")
    elif not conf.get("final_confirmed"):
        print("第3次确认：AI 全自动 TTS→渲染→合成→验证 → 用户确认最终产物")
        print("  （voice → render → assemble → validate → 用户确认）")
    else:
        print("全部确认完成，可交付发布")
    return 0


def cmd_sync_boards(episode_dir: Path, args) -> int:
    state = _load_state_or_fail(episode_dir)
    if state is None:
        return 1

    # ---- 场景命名统一规范：自动修复非标准命名（如 scene-03b）----
    # 非标准命名会导致 sync-boards 后场景错位、板图文件名不匹配。
    # 自动重命名为 scene-XX，同时重命名 build/boards/ 中的对应文件。
    import re
    scene_id_pattern = re.compile(r"^scene-\d{2}$")
    script_path = episode_dir / "input" / "script.json"
    if script_path.exists():
        doc = json.loads(script_path.read_text(encoding="utf-8"))
        renamed = []
        for i, sc in enumerate(doc.get("scenes", [])):
            old_id = sc.get("id") or sc.get("scene_id") or ""
            new_id = f"scene-{i+1:02d}"
            if old_id != new_id:
                # 重命名板图文件
                for ext in ("png", "jpg", "jpeg"):
                    old_board = episode_dir / "build" / "boards" / f"{old_id}.{ext}"
                    new_board = episode_dir / "build" / "boards" / f"{new_id}.{ext}"
                    if old_board.exists() and not new_board.exists():
                        old_board.rename(new_board)
                        renamed.append(f"{old_id}.{ext} → {new_id}.{ext}")
                    # input/boards/ 也重命名
                    old_input = episode_dir / "input" / "boards" / f"{old_id}.{ext}"
                    new_input = episode_dir / "input" / "boards" / f"{new_id}.{ext}"
                    if old_input.exists() and not new_input.exists():
                        old_input.rename(new_input)
                sc["id"] = new_id
                # 移除可能存在的 scene_id 字段
                sc.pop("scene_id", None)
                renamed.append(f"{old_id} → {new_id}")
        if renamed:
            script_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  ✓ 场景命名自动修复（{len(renamed)} 项）：")
            for r in renamed:
                print(f"    {r}")

    ids = _scene_ids_from_script(episode_dir)
    if not ids:
        print("缺 input/script.json 或 scenes[] 为空")
        return 1
    findings = ir_contract.lint_episode(episode_dir)
    blockers = [f for f in findings if f.severity == "blocking"]
    if blockers:
        print("sync-boards 被拦：script.json 的 IR 不合法（先修文档再进现场阶段）")
        for f in blockers:
            print(f"  ✗ {f.code}  {f.message}")
        for f in [x for x in findings if x.severity == "warning"]:
            print(f"  ! {f.code}  {f.message}")
        return 1
    _sync_boards_list(state, ids)
    state["phases"]["boards_generated"] = all(b["status"] == "ok" for b in state["boards"])
    state["phases"]["boards_reviewed"] = False
    _write_state(episode_dir, state)
    print(f"sync-boards ok：{len(ids)} 幕（" + ", ".join(ids) + "）")
    return 0


def _load_engine_voice() -> dict:
    if not ENGINE_VOICE.exists():
        return {"backend": "edge-tts", "name": "zh-CN-YunxiaNeural", "rate": "+0%"}
    try:
        return json.loads(ENGINE_VOICE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"backend": "edge-tts", "name": "zh-CN-YunxiaNeural", "rate": "+0%"}


def _load_theme_voice(theme_path: str | None) -> tuple[dict, str]:
    if not theme_path:
        return {}, ""
    tp = Path(theme_path)
    # state.theme 存的是主题目录，voice 块在目录里的 theme.json；没这个文件=主题不声明音色
    if tp.is_dir():
        tp = tp / "theme.json"
    if not tp.exists():
        return {}, ""
    try:
        data = json.loads(tp.read_text(encoding="utf-8"))
        tv = data.get("voice", {}) or {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"! 主题声音块读取失败（退引擎默认）：{tp}：{e}")
        return {}, ""
    return (tv, str(tp)) if tv else ({}, "")


# ---- TTS 参数智能推荐（按知识类型）----
# 业界最佳实践：教育类=清晰中速，技术类=0.9x慢速，故事类=活泼语调
TTS_RECOMMENDATIONS = {
    "technical": {
        "voice": "zh-CN-YunxiaNeural",
        "rate": "-5%",
        "reason": "技术类内容：稍慢语速帮助理解复杂概念",
    },
    "educational": {
        "voice": "zh-CN-YunxiaNeural",
        "rate": "+0%",
        "reason": "教育科普类：清晰中速，权威但亲切",
    },
    "story": {
        "voice": "zh-CN-YunxiNeural",
        "rate": "+5%",
        "reason": "故事类：活泼音色，稍快节奏增强叙事感",
    },
    "opinion": {
        "voice": "zh-CN-YunjianNeural",
        "rate": "+0%",
        "reason": "观点评论类：沉稳男声，增强说服力",
    },
    "default": {
        "voice": "zh-CN-YunxiaNeural",
        "rate": "+0%",
        "reason": "默认：知性女声，通用知识讲解",
    },
}


def _infer_knowledge_type(script_path: Path) -> str:
    """从 script.json 推断知识类型：technical/educational/story/opinion/default。"""
    if not script_path.exists():
        return "default"
    try:
        doc = json.loads(script_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "default"
    # 优先从 knowledge_model.task_type 推断
    km = doc.get("knowledge_model", {})
    task_type = km.get("task_type", "").upper()
    if task_type in ("C", "MECHANISM"):
        return "technical"
    if task_type in ("B", "CONCEPT"):
        return "educational"
    if task_type in ("A", "CORRECTION"):
        return "opinion"
    # 从 narration 文本关键词推断
    narration = " ".join(sc.get("narration", "") for sc in doc.get("scenes", []))
    narration_lower = narration.lower()
    story_keywords = ["故事", "人物", "经历", "历史", "传说", "案例"]
    tech_keywords = ["算法", "代码", "技术", "架构", "系统", "原理", "机制", "模型"]
    opinion_keywords = ["应该", "必须", "观点", "认为", "批判", "反思"]
    if any(k in narration for k in story_keywords):
        return "story"
    if any(k in narration for k in tech_keywords):
        return "technical"
    if any(k in narration for k in opinion_keywords):
        return "opinion"
    return "educational"


def cmd_voice(episode_dir: Path, args) -> int:
    from whiteboard_story.providers import voice as voice_mod
    state = _load_state_or_fail(episode_dir)
    if state is None:
        return 1
    # 闸门：同时支持新流程（confirmations.content_confirmed）和旧流程（phases.script_audio_confirmed）
    content_confirmed = (state.get("confirmations", {}).get("content_confirmed")
                         or state["phases"].get("script_audio_confirmed"))
    if content_confirmed and not args.force:
        print("闸门：本片已过第一次人工确认（内容与方向）。改口播请加 --force，并按 engine-design 重跑矩阵重算下游。")
        return 3
    script = Path(args.script) if args.script else episode_dir / "input" / "script.json"
    if not script.exists():
        print(f"缺口播脚本：{script}")
        return 1
    engine_voice = _load_engine_voice()
    theme_voice, theme_src = _load_theme_voice(
        getattr(args, "theme", None) or state.get("theme"))
    cli_voice, cli_rate = getattr(args, "voice", None), getattr(args, "rate", None)
    base = {**engine_voice, **theme_voice}
    # TTS 参数智能推荐：用户未显式指定且无主题 voice 时，按知识类型推荐
    knowledge_type = _infer_knowledge_type(script)
    recommendation = TTS_RECOMMENDATIONS.get(knowledge_type, TTS_RECOMMENDATIONS["default"])
    if cli_voice or cli_rate:
        src = "CLI 显式参数"
        final_voice = cli_voice or base.get("name") or recommendation["voice"]
        final_rate = cli_rate or base.get("rate") or recommendation["rate"]
    elif theme_voice:
        src = f"主题 voice（{theme_src}）"
        final_voice = base.get("name") or recommendation["voice"]
        final_rate = base.get("rate") or recommendation["rate"]
    else:
        src = f"智能推荐（知识类型={knowledge_type}）"
        final_voice = recommendation["voice"]
        final_rate = recommendation["rate"]
        print(f"✓ TTS 智能推荐：{recommendation['reason']}")
    identity = {
        "backend": base.get("backend", "edge-tts"),
        "name": final_voice,
        "rate": final_rate,
    }
    if getattr(args, "theme", None) and state.get("theme") != str(args.theme):
        # 统一存储绝对路径，避免相对路径基准不一致导致 ResourceResolver 解析失败
        theme_path = Path(args.theme)
        if not theme_path.is_absolute():
            theme_path = (episode_dir / theme_path).resolve()
        state["theme"] = str(theme_path)
    # TTS 重试机制：最多3次，指数退避 2s→4s→8s，只重试网络相关错误
    MAX_TTS_RETRY = 3
    TTS_RETRY_DELAYS = [2, 4, 8]
    RETRYABLE_EXCEPTIONS = (ConnectionError, TimeoutError, OSError)
    r = None
    last_error = None
    for attempt in range(MAX_TTS_RETRY):
        try:
            r = voice_mod.make_voice(script, episode_dir,
                                     voice=identity["name"], rate=identity["rate"])
            break
        except RETRYABLE_EXCEPTIONS as e:
            last_error = e
            if attempt < MAX_TTS_RETRY - 1:
                delay = TTS_RETRY_DELAYS[attempt]
                print(f"↻ TTS 第{attempt + 1}次失败（{type(e).__name__}: {e}），{delay}s后重试...")
                import time as _time
                _time.sleep(delay)
            else:
                print(f"✗ TTS 失败（已重试{MAX_TTS_RETRY}次）：{type(e).__name__}: {e}")
        except Exception as e:
            # 非网络错误（如文本过长、音色不存在）不重试
            print(f"✗ TTS 失败（不可重试错误）：{type(e).__name__}: {e}")
            return 1
    if r is None:
        if last_error:
            print(f"✗ TTS 最终失败：{type(last_error).__name__}: {last_error}")
        return 1
    if last_error:
        print(f"✓ TTS 重试成功（第{attempt + 1}次）")
    state["voice_identity"] = {**identity, "resolved_from": src, "decided_at": _now()}
    ids = _scene_ids_from_script(episode_dir)
    if ids:
        _sync_boards_list(state, ids)
    _write_state(episode_dir, state)
    print(f"声音身份：{identity['name']} rate={identity['rate']}（{src}）")
    print(f"三件套已生成：total {r['total_ms']}ms，词级词条 {r['word_count']} 条")
    print("试听 input/narration.mp3；确认后跑 confirm-voice")
    return 0


def cmd_confirm_voice(episode_dir: Path, args) -> int:
    from whiteboard_story.providers import voice as voice_mod
    state = _load_state_or_fail(episode_dir)
    if state is None:
        return 1
    missing = [n for n in ("narration.mp3", "captions.srt", "words.json")
               if not (episode_dir / "input" / n).exists()]
    if missing:
        print("三件套不齐：" + "、".join(missing))
        return 1
    fp = voice_mod.compute_voice_fingerprints(episode_dir / "input")
    state["voice_fingerprints"] = fp
    already = bool(state["phases"].get("script_audio_confirmed"))
    state["phases"]["script_audio_confirmed"] = True
    # 同步新流程：voice 成功即内容已确认（兼容旧流程，新流程在 confirm-content 时已设置）
    conf = state.setdefault("confirmations", {})
    if not conf.get("content_confirmed"):
        conf["content_confirmed"] = True
    log = state.setdefault("confirmation_log", [])
    if not any(c.get("kind") == "script_audio" for c in log):
        log.append({"at": _now(), "kind": "script_audio"})
    _write_state(episode_dir, state)
    print(("确认记录已更新" if already else "第一次确认完成") +
          f"：voice_fingerprints×{len(fp)}")
    print("下一步：prompts → 批量生成场景图 → import")
    return 0


def _theme_dir(args, state: dict | None = None) -> Path | None:
    raw = getattr(args, "theme", None) or (state or {}).get("theme")
    if not raw:
        return None
    p = Path(raw)
    if p.is_file():
        return p.parent
    return p


def cmd_prompts(episode_dir: Path, args) -> int:
    state = _load_state_or_fail(episode_dir)
    if state is None:
        return 1
    theme = _theme_dir(args, state)
    if theme is None or not theme.exists():
        print("缺主题目录：--theme themes/<id> 或先在 voice 时登记 state.theme")
        return 1
    theme_check = review_images.validate_theme_package(theme)
    if not theme_check["ok"]:
        print("主题包合同未通过：")
        for msg in theme_check["errors"]:
            print(f"  ✗ {msg}")
        return 1
    for msg in theme_check["warnings"]:
        print(f"  ! {msg}")
    script = episode_dir / "input" / "script.json"
    if not script.exists():
        print(f"缺 {script}")
        return 1
    scenes = json.loads(script.read_text(encoding="utf-8")).get("scenes", [])
    chars = character_bible.load_characters(episode_dir)
    char_errors = character_bible.validate_characters(chars)
    if char_errors:
        print("角色圣经校验：")
        for msg in char_errors:
            print(f"  ✗ {msg}")
        return 1
    character_sheet = character_bible.render_prompt_block(chars)
    want = getattr(args, "scene", None)
    out_dir = episode_dir / "input" / "prompts"
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for i, sc in enumerate(scenes):
        sid = sc.get("id") or f"scene-{i + 1:02d}"
        if want and sid != want:
            continue
        character_ids = character_bible.scene_character_ids(sc)
        references = character_bible.character_reference_manifest(episode_dir, chars, character_ids)
        payload = prompt_builder.build_scene_payload(
            sid, sc.get("board_subject") or sc.get("subject") or "", theme,
            n_islands=len(sc.get("elements") or []),
            character_sheet=character_sheet,
            character_ids=character_ids,
            character_references=references)
        dest = out_dir / f"{sid}.prompt.json"
        dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"===== {sid} =====")
        print(payload["prompt"])
        print(f"→ {dest}  {payload['width']}x{payload['height']}")
        n += 1
    if want and n == 0:
        print(f"脚本里没有 {want}")
        return 1
    print(f"\n共 {n} 张。报批通过后，宿主模型一次一张生成 PNG，落到 build/boards/<id>.png，再 import。")
    if chars:
        ref_prompt = character_bible.build_character_sheet_prompt(chars, theme_name=theme.name)
        ref_path = episode_dir / "input" / "character-sheet.prompt.txt"
        ref_path.write_text(ref_prompt + "\n", encoding="utf-8")
        manifest = character_bible.character_reference_manifest(episode_dir, chars)
        manifest_path = episode_dir / "input" / "character-reference-manifest.json"
        manifest_path.write_text(json.dumps({
            "schema": character_bible.SCHEMA,
            "theme": theme.name,
            "characters": manifest,
            "canonical_sheet_required": True
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"角色圣经：{len(chars)} 个稳定角色；已写 canonical prompt + reference manifest")
    else:
        print("角色圣经为空：本期若存在跨幕人物，请先填写 input/characters.json，再批量出图。")
    if getattr(args, "theme", None):
        # 统一存储绝对路径：--theme 按当前工作目录写（../themes/<id>），这里已验证它存在，
        # 若改按 episode_dir 为基准拼接会存进一个不存在的目录，voice/render 才炸。
        theme_path = Path(theme).resolve()
        state["theme"] = str(theme_path)
        _write_state(episode_dir, state)
    return 0


def cmd_probe(args) -> int:
    theme = Path(args.theme)
    if theme.is_file():
        theme = theme.parent
    if not theme.exists():
        print(f"主题目录不存在：{theme}")
        return 1
    theme_check = review_images.validate_theme_package(theme)
    if not theme_check["ok"]:
        print("主题包合同未通过：")
        for msg in theme_check["errors"]:
            print(f"  ✗ {msg}")
        return 1
    payload = prompt_builder.probe_payload(theme)
    print(payload["prompt"])
    print(f"\n尺寸 {payload['width']}x{payload['height']}。报批 1 张后宿主模型生成临时探针；目检结束即删除，不写入 {theme}")
    return 0


def cmd_import(episode_dir: Path, args) -> int:
    state = _load_state_or_fail(episode_dir)
    if state is None:
        return 1
    boards_dir = Path(args.boards_dir)
    if not boards_dir.exists():
        print(f"目录不存在：{boards_dir}")
        return 1
    theme = _theme_dir(args, state)
    if theme is None or not theme.exists():
        # 兜底：script.json 的 theme 字段（仓库相对路径）
        script_path = episode_dir / "input" / "script.json"
        if script_path.exists():
            rel = json.loads(script_path.read_text(encoding="utf-8")).get("theme")
            if rel:
                cand = Path(rel)
                if not cand.is_absolute():
                    cand = Path(__file__).resolve().parents[2] / rel
                if cand.exists():
                    theme = cand
    if theme is not None:
        theme_check = review_images.validate_theme_package(theme)
        if not theme_check["ok"]:
            print("主题包合同未通过，拒绝 import：")
            for msg in theme_check["errors"]:
                print(f"  ✗ {msg}")
            return 3
        for msg in theme_check["warnings"]:
            print(f"  ! {msg}")
    else:
        print("! 未解析到主题目录：跳过主题合同闸门，但建议显式提供 --theme")
    ids = [b["scene"] for b in state["boards"]]
    if not ids:
        ids = sorted(p.stem for p in boards_dir.glob("scene-*.png"))
        state["boards"] = [_board_stub(s) for s in ids]
    if not ids:
        print("state.boards 为空且目录里没有 scene-*.png；先 sync-boards 或放入板图")
        return 1
    all_ok = True
    for b in state["boards"]:
        f = boards_dir / f"{b['scene']}.png"
        if not f.exists():
            b["status"] = "missing"
            b["file"] = None
            all_ok = False
            print(f"✗ {b['scene']}: 缺 {f.name}")
            continue
        norm = review_images.normalize_board_size(f)
        if norm.get("scaled"):
            ow, oh = norm["size"]
            if norm.get("cropped"):
                cw, ch = norm["cropped"]
                print(f"  · {b['scene']}: {ow}x{oh} → 居中裁 {cw}x{ch} → 1920x1080"
                      f"（比例非精确 16:9，已裁边等比放大）")
            else:
                print(f"  · {b['scene']}: {ow}x{oh} → 1920x1080（自动等比缩放）")
        # 顺序有实测依据：先清水印、后归一底色。底色归一会连半透明角标自己的颜色一起平移，
        # 把它推出 WM_GLYPH_MAX_DIST 的标定窗口，角标反而检不出来（一期实盘 7 张里 3 张漏检）。
        wm_result = review_images.strip_watermark(f)
        if wm_result.get("detected"):
            if wm_result.get("removed"):
                print(f"  · {b['scene']}: 已清除水印（{len(wm_result['regions'])}个区域，残留率{wm_result['residual_ratio']}）")
            else:
                all_ok = False
                b["status"] = "failed"
                b["errors"] = b.get("errors", []) + [f"水印清除失败（残留率{wm_result['residual_ratio']}），请手动处理或重新生成无水印板图"]
                print(f"  ✗ {b['scene']}: 检测到水印但清除失败（残留率{wm_result['residual_ratio']}），请手动处理或重新生成无水印板图")
                continue
        bg_norm = review_images.normalize_board_bg(f, theme)
        if bg_norm.get("normalized"):
            bgr, tgt, moved = bg_norm["bg"], bg_norm["target"], bg_norm["moved_ratio"]
            print(f"  · {b['scene']}: 板底色 ({bgr[2]},{bgr[1]},{bgr[0]}) → 主题 "
                  f"({tgt[2]},{tgt[1]},{tgt[0]})，平移 {moved:.0%} 底色像素")
        r = review_images.check_board(f, theme_dir=theme)
        b["file"] = str(f)
        b["checks"] = r["info"]
        b["errors"] = r["errors"]
        b["warnings"] = r["warnings"]
        b["status"] = "ok" if r["ok"] else "failed"
        if r["ok"]:
            print(f"✓ {b['scene']}: {r['info']['width']}x{r['info']['height']}")
        else:
            all_ok = False
            print(f"✗ {b['scene']}: " + "；".join(r["errors"]))
        for w in r["warnings"]:
            print(f"  ! {w}")
        # 自动复制板图到 build/boards/（消除手动 cp 步骤）
        # 只有检查通过的板图才复制；failed 的保留原文件供人工处理
        if r["ok"]:
            build_boards_dir = episode_dir / "build" / "boards"
            build_boards_dir.mkdir(parents=True, exist_ok=True)
            dest = build_boards_dir / f"{b['scene']}.png"
            import shutil
            if dest.exists() and dest.samefile(f):
                continue  # --boards-dir 就是 build/boards，板图已在原位
            shutil.copy2(f, dest)
            print(f"  → 已复制到 build/boards/{b['scene']}.png")
    state["phases"]["boards_generated"] = all_ok
    state["phases"]["boards_reviewed"] = False
    _write_state(episode_dir, state)
    return 0 if all_ok else 2


def cmd_confirm_boards(episode_dir: Path, args) -> int:
    state = _load_state_or_fail(episode_dir)
    if state is None:
        return 1
    if not state["phases"].get("boards_generated"):
        print("闸门：自动检查未全过，不确认")
        return 3
    if not all(b["status"] == "ok" for b in state["boards"]):
        print("闸门：仍有板图 failed/missing")
        return 3
    state["phases"]["boards_reviewed"] = True
    # 同步更新质量门：第2次确认（视觉方案）
    conf = state.setdefault("confirmations", {})
    conf["visual_confirmed"] = True
    log = state.setdefault("confirmation_log", [])
    if not any(c.get("kind") == "boards" for c in log):
        log.append({"at": _now(), "kind": "boards"})
    _write_state(episode_dir, state)
    print("第二次确认完成：boards_reviewed=true, visual_confirmed=true")
    return 0


def cmd_confirm_content(episode_dir: Path, args) -> int:
    """第1次确认：内容与方向（大纲+脚本+主题）。
    检查 script.json 存在且 lint 通过，设置 content_confirmed=true。
    脚本确认即音频内容确认（TTS 参数用默认），同步设置 script_audio_confirmed=true。
    """
    state = _load_state_or_fail(episode_dir)
    if state is None:
        return 1
    script_path = episode_dir / "input" / "script.json"
    if not script_path.exists():
        print("闸门：input/script.json 不存在，不确认")
        return 3
    # 跑 lint 检查 IR 契约（阻断项非空即拒绝：缺 IR = Beat 数回到临场发挥，principles P5）
    try:
        findings = ir_contract.lint_episode(episode_dir)
    except Exception as e:
        print(f"闸门：lint 执行失败（{e}），不确认")
        return 3
    blockers = [f for f in findings if f.severity == "blocking"]
    if blockers:
        print(f"闸门：lint 有 {len(blockers)} 项阻断，不确认")
        for f in blockers:
            print(f"  ✗ {f.code}  {f.message}")
        return 3
    conf = state.setdefault("confirmations", {})
    conf["content_confirmed"] = True
    state["phases"]["express_card_filled"] = True
    state["phases"]["script_audio_confirmed"] = True
    log = state.setdefault("confirmation_log", [])
    if not any(c.get("kind") == "content" for c in log):
        log.append({"at": _now(), "kind": "content"})
    _write_state(episode_dir, state)
    print("第1次确认完成：content_confirmed=true（内容与方向已确认）")
    print("下一步：批量生成全部场景图 → import → layout → annotate → 第2次确认")
    return 0


def cmd_confirm_visual(episode_dir: Path, args) -> int:
    """第2次确认：视觉方案（全部场景图批量确认）。
    检查全部场景图已生成且通过检查，设置 visual_confirmed=true。
    同步设置 boards_reviewed=true。
    """
    state = _load_state_or_fail(episode_dir)
    if state is None:
        return 1
    if not state["phases"].get("boards_generated"):
        print("闸门：场景图自动检查未全过，不确认")
        return 3
    if not all(b["status"] == "ok" for b in state["boards"]):
        print("闸门：仍有板图 failed/missing")
        return 3
    if not state["phases"].get("annotated"):
        print("闸门：标注未完成（annotated=false），不确认")
        return 3
    conf = state.setdefault("confirmations", {})
    conf["visual_confirmed"] = True
    state["phases"]["boards_reviewed"] = True
    log = state.setdefault("confirmation_log", [])
    if not any(c.get("kind") == "visual" for c in log):
        log.append({"at": _now(), "kind": "visual"})
    _write_state(episode_dir, state)
    print("第2次确认完成：visual_confirmed=true（视觉方案已确认）")
    print("下一步：全自动 TTS→渲染→合成→验证 → 第3次确认")
    return 0


def cmd_confirm_final(episode_dir: Path, args) -> int:
    """第3次确认：最终产物（视频交付）。
    检查最终视频存在，设置 final_confirmed=true。
    """
    state = _load_state_or_fail(episode_dir)
    if state is None:
        return 1
    final_path = episode_dir / "deliverables" / "final.mp4"
    if not final_path.exists():
        print("闸门：deliverables/final.mp4 不存在，不确认")
        return 3
    conf = state.setdefault("confirmations", {})
    conf["final_confirmed"] = True
    state["phases"]["finalized"] = True
    log = state.setdefault("confirmation_log", [])
    if not any(c.get("kind") == "final" for c in log):
        log.append({"at": _now(), "kind": "final"})
    _write_state(episode_dir, state)
    print("第3次确认完成：final_confirmed=true（最终产物已确认）")
    print("全部确认完成，可交付发布")
    return 0


def cmd_render(episode_dir: Path, args) -> int:
    state = _load_state_or_fail(episode_dir)
    if state is None:
        return 1
    if not state["phases"]["boards_reviewed"]:
        print("闸门未过：板图人工二审未通过，不渲染")
        return 3
    if not state["phases"]["annotated"]:
        print("闸门未过：缺少标注")
        return 3
    print("渲染入口就绪：build_video.py render（须显式 --hand 或项目 assets/hand-pen.png）")
    return 0


def cmd_validate(episode_dir: Path, args) -> int:
    from whiteboard_story import validate as validate_mod
    blockers, warnings, info = validate_mod.validate(episode_dir)
    rp = validate_mod.render_report(episode_dir, blockers, warnings, info)
    print(f"validate：阻断 {len(blockers)} 项，警告 {len(warnings)} 项")
    for b in blockers:
        print(f"  ✗ {b}")
    for w in warnings:
        print(f"  ! {w}")
    print(f"报告：{rp}")
    if getattr(args, "full", False):
        from whiteboard_story import qa_gates
        qbad, _qwarn, rows = qa_gates.run_all(
            episode_dir, getattr(args, "sheets_dir", None))
        print("\n".join(rows))
        print(f"qa_gates：阻断 {len(qbad)} 项")
        for b in qbad:
            print(f"  ✗ {b}")
        blockers = blockers + qbad
    return 1 if blockers else 0


def cmd_lint(episode_dir: Path, args) -> int:
    findings = ir_contract.lint_episode(episode_dir)
    blockers = [f for f in findings if f.severity == "blocking"]
    warnings = [f for f in findings if f.severity == "warning"]
    for f in blockers:
        print(f"  ✗ {f.code}  {f.message}")
    for f in warnings:
        print(f"  ! {f.code}  {f.message}")
    print(f"lint：阻断 {len(blockers)} 项，警告 {len(warnings)} 项")
    return 1 if blockers else 0


def cmd_spans(episode_dir: Path, args) -> int:
    from whiteboard_story import spans as spans_mod
    try:
        result, warnings = spans_mod.write_spans(episode_dir)
    except FileNotFoundError as e:
        print(f"✗ {e}")
        return 1
    for sid, sp in result.items():
        if sp:
            print(f"OK {sid}  {len(sp)} spans  {sp[0]['start_ms']}-{sp[-1]['end_ms']}ms")
    for wmsg in warnings:
        print(f"  ! {wmsg}")
    print(f"narration_spans 已写回 input/words.json（{len(result)} 幕）")
    return 1 if warnings else 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="workflow.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_init = sub.add_parser("init")
    p_init.add_argument("--episode-dir", required=True)
    p_init.add_argument("--title", required=True)
    p_init.add_argument("--scenes", type=int, default=None,
                        help="预留幕数；缺省留空，以 script.json 为准")
    p_status = sub.add_parser("status")
    p_status.add_argument("--episode-dir", required=True)
    p_sync = sub.add_parser("sync-boards")
    p_sync.add_argument("--episode-dir", required=True)
    p_voice = sub.add_parser("voice")
    p_voice.add_argument("--episode-dir", required=True)
    p_voice.add_argument("--script", default=None)
    p_voice.add_argument("--voice", default=None)
    p_voice.add_argument("--rate", default=None)
    p_voice.add_argument("--theme", default=None,
                         help="主题目录或 theme.json；只用来登记 state.theme 与可选 voice 覆盖")
    p_voice.add_argument("--force", action="store_true")
    p_cvoice = sub.add_parser("confirm-voice")
    p_cvoice.add_argument("--episode-dir", required=True)
    p_prompts = sub.add_parser("prompts")
    p_prompts.add_argument("--episode-dir", required=True)
    p_prompts.add_argument("--theme", default=None)
    p_prompts.add_argument("--scene", default=None)
    p_probe = sub.add_parser("probe")
    p_probe.add_argument("--theme", required=True)
    p_lint = sub.add_parser("lint")
    p_lint.add_argument("--episode-dir", required=True)
    p_spans = sub.add_parser("spans")
    p_spans.add_argument("--episode-dir", required=True)
    p_import = sub.add_parser("import")
    p_import.add_argument("--episode-dir", required=True)
    p_import.add_argument("--boards-dir", required=True)
    p_import.add_argument("--theme", default=None,
                          help="主题目录；决定底色检查口径（paper 暖白 / chalk 板绿），缺省自 state 或 script.json 推导")
    p_cboards = sub.add_parser("confirm-boards")
    p_cboards.add_argument("--episode-dir", required=True)
    p_ccontent = sub.add_parser("confirm-content",
                                 help="第1次确认：内容与方向（大纲+脚本+主题）")
    p_ccontent.add_argument("--episode-dir", required=True)
    p_cvisual = sub.add_parser("confirm-visual",
                                help="第2次确认：视觉方案（全部场景图批量确认）")
    p_cvisual.add_argument("--episode-dir", required=True)
    p_cfinal = sub.add_parser("confirm-final",
                               help="第3次确认：最终产物（视频交付）")
    p_cfinal.add_argument("--episode-dir", required=True)
    p_render = sub.add_parser("render")
    p_render.add_argument("--episode-dir", required=True)
    p_validate = sub.add_parser("validate")
    p_validate.add_argument("--episode-dir", required=True)
    p_validate.add_argument("--full", action="store_true",
                            help="加跑 qa_gates 成片闸口（扫荡/切幕/残影/缺墨/规格/响度）")
    p_validate.add_argument("--sheets-dir", default=None,
                            help="--full 时产出人审接触表的目录（首幕 2fps、其余 1fps）")
    args = ap.parse_args()
    if args.cmd == "probe":
        return cmd_probe(args)
    episode_dir = Path(args.episode_dir).resolve()
    dispatch = {
        "init": lambda: cmd_init(episode_dir, args.title, args),
        "status": lambda: cmd_status(episode_dir, args),
        "sync-boards": lambda: cmd_sync_boards(episode_dir, args),
        "voice": lambda: cmd_voice(episode_dir, args),
        "confirm-voice": lambda: cmd_confirm_voice(episode_dir, args),
        "prompts": lambda: cmd_prompts(episode_dir, args),
        "lint": lambda: cmd_lint(episode_dir, args),
        "spans": lambda: cmd_spans(episode_dir, args),
        "import": lambda: cmd_import(episode_dir, args),
        "confirm-boards": lambda: cmd_confirm_boards(episode_dir, args),
        "confirm-content": lambda: cmd_confirm_content(episode_dir, args),
        "confirm-visual": lambda: cmd_confirm_visual(episode_dir, args),
        "confirm-final": lambda: cmd_confirm_final(episode_dir, args),
        "render": lambda: cmd_render(episode_dir, args),
        "validate": lambda: cmd_validate(episode_dir, args),
    }
    return dispatch[args.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
