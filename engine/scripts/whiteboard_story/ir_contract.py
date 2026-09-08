"""ir_contract.py — 编译器各层 IR 的机器可读契约与静态校验（`workflow.py lint`）。

定位：`knowledge-model.md` / `learner-model.md` / `expression-plan.md` / `ir-alignment.md` 的
可执行版本。判据本身不在此发明，只做机械检查；错误码与文档小节一一对应，便于回溯。

原则：文档层不再是真相源。缺 IR 即非法（blocking），因为它意味着 Beat 数、操作类型、
揭示动作又回到"临场发挥"，整个编译器就被绕过了（`principles` P5/P6）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---- 枚举（唯一权威：cognitive-timeline §7 / learner-model §3/§5 / expression-plan §3/§5）----

TASK_TYPES = {"A", "B", "C", "D"}                      # knowledge-model §6
CONFIDENCE = {"source-backed fact", "model inference", "teaching simplification"}
COGNITIVE_OPERATIONS = {"IDENTIFY", "DISTINGUISH", "RELATE", "EXPLAIN", "APPLY"}   # learner §3
OBSTACLES = {"MISSING", "CONFLICT", "GAP", "ABSTRACTION", "OVERLOAD", "TRANSFER"}  # learner §5
NARRATIVE_FUNCTIONS = {"DECLARE", "QUESTION", "CONTRAST", "EXPLAIN",
                       "TRACE", "INTERPRET", "GENERALIZE", "CHECK"}                 # expression §3
VISUAL_OPERATIONS = {"INTRODUCE", "CONTRAST", "CONNECT", "DECOMPOSE", "TRANSFORM",
                     "CAUSE", "EXAMPLE", "COUNTEREXAMPLE", "HIGHLIGHT", "SUMMARIZE"}
REVEAL_OPERATIONS = {"DRAW", "CONNECT", "CHANGE", "HIGHLIGHT",
                     "ANNOTATE", "GROUP", "REMOVE", "REFRAME"}                      # expression §5
# 目标机指令集缺口：内核只加墨、无高亮原语、无视口（kernel-design §5 第 6–8 项）
REVEAL_UNSUPPORTED = {"HIGHLIGHT", "REMOVE", "REFRAME"}
CHANNELS = {"verbal", "visual", "shared"}
TIMING_ROLES = {"锚点", "承接", "停留"}

KNOWLEDGE_REQUIRED = ("subject", "target_claim", "task_type", "learner", "model",
                      "learning_outcome", "evidence", "dependencies", "scope",
                      "source_coverage")
CONSTRAINT_KEYS = ("prerequisites", "misconceptions_to_resolve", "essential_relations",
                   "optional_details", "load_budget")


@dataclass(frozen=True)
class Finding:
    severity: str      # blocking | warning
    code: str        # 稳定错误码，文档可引用
    message: str

    def __str__(self) -> str:
        mark = "✗" if self.severity == "blocking" else "!"
        return f"{mark} [{self.code}] {self.message}"


def _blocks(findings: list[Finding]) -> list[Finding]:
    return [f for f in findings if f.severity == "blocking"]


def _b(code: str, msg: str) -> Finding:
    return Finding("blocking", code, msg)


def _w(code: str, msg: str) -> Finding:
    return Finding("warning", code, msg)


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


# ---------------------------------------------------------------- Knowledge Model

def check_knowledge_model(km: Any, out: list[Finding]) -> None:
    if not isinstance(km, dict):
        out.append(_b("KM.MISSING",
                      "script.json 缺 knowledge_model：IR 必须在机器可读位置，不能只写在表达设计卡上"))
        return
    for key in KNOWLEDGE_REQUIRED:
        if not _nonempty(km.get(key)):
            out.append(_b("KM.REQUIRED", f"knowledge_model.{key} 为空（knowledge-model.md §7 必填）"))

    scope = km.get("scope") or {}
    if isinstance(scope, dict) and not _nonempty(scope.get("exclude")):
        out.append(_b("KM.SCOPE",
                      "scope.exclude 为空：写不出省略清单说明还没读懂材料（knowledge-model.md §4）"))

    learner = km.get("learner") or {}
    if isinstance(learner, dict) and _nonempty(learner.get("misconception")) \
            and not _nonempty(str(learner.get("misconception_source", ""))):
        out.append(_w("KM.SCARECROW",
                      "misconception 无样本来源：不许现编稻草人（knowledge-model.md §4）"))

    task_type = str(km.get("task_type") or "")
    for token in [t.strip() for t in task_type.replace("+", " ").split() if t.strip()]:
        if token not in TASK_TYPES:
            out.append(_b("KM.TASK_TYPE", f"task_type「{token}」不在 A/B/C/D 内"))

    outcome = km.get("learning_outcome") or {}
    if isinstance(outcome, dict) and not any(_nonempty(outcome.get(k))
                                             for k in ("recognition", "explanation",
                                                       "prediction", "application")):
        out.append(_b("KM.OUTCOME", "learning_outcome 四项全空：观众学完能做什么必须可观察"))

    evidence_ids: set[str] = set()
    for i, ev in enumerate(km.get("evidence") or []):
        if not isinstance(ev, dict):
            out.append(_b("KM.EVIDENCE", f"evidence[{i}] 不是对象"))
            continue
        if not _nonempty(ev.get("source")):
            out.append(_b("KM.EVIDENCE_SOURCE",
                          f"evidence[{i}] 无 source：来源没有的内容不进片（principles P4）"))
        conf = ev.get("confidence")
        if conf not in CONFIDENCE:
            out.append(_b("KM.EVIDENCE_CONFIDENCE",
                          f"evidence[{i}].confidence「{conf}」不在三档内（knowledge-model.md §5）"))
        if conf == "teaching simplification" and not _nonempty(ev.get("note")):
            out.append(_w("KM.SIMPLIFICATION_UNDOC",
                          f"evidence[{i}] 是教学简化但未写说明：未登记的简化就是幻觉"))
        if _nonempty(ev.get("id")):
            evidence_ids.add(str(ev["id"]))

    model = km.get("model") or {}
    if isinstance(model, dict):
        nodes = {str(n.get("id")) for n in (model.get("nodes") or [])
                 if isinstance(n, dict) and _nonempty(n.get("id"))}
        for i, rel in enumerate(model.get("relations") or []):
            if not isinstance(rel, dict):
                out.append(_b("KM.RELATION", f"model.relations[{i}] 不是对象"))
                continue
            if not _nonempty(rel.get("type")):
                out.append(_b("KM.RELATION_TYPE",
                              f"relations[{i}] 缺关系类型：类型决定线性化（learner-model.md §8）"))
            for end in (rel.get("from"), rel.get("to")):
                if _nonempty(end) and str(end) not in nodes:
                    out.append(_b("KM.RELATION_DANGLING",
                                  f"relations[{i}] 引用了不存在的节点「{end}」"))
    return _cross_check_evidence(km, evidence_ids, out)


def _cross_check_evidence(km: dict, evidence_ids: set[str], out: list[Finding]) -> None:
    if not evidence_ids:
        return
    nodes = (km.get("model") or {}).get("nodes") or []
    covered = set()
    for n in nodes:
        if isinstance(n, dict):
            for ref in n.get("evidence") or []:
                covered.add(str(ref))
    orphans = evidence_ids - covered
    if orphans:
        out.append(_w("KM.EVIDENCE_UNBOUND",
                      "这些 evidence 没挂到任何 model.nodes 上：" + ", ".join(sorted(orphans))))


# ---------------------------------------------------------------- Learner Model

def check_learner_model(lm: Any, beats: list[tuple[str, dict]], out: list[Finding]) -> None:
    if not isinstance(lm, dict):
        out.append(_b("LM.MISSING",
                      "script.json 缺 learner_model：Beat 数量与操作类型必须是求解结果（principles P5）"))
        return

    constraints = lm.get("constraints") or {}
    for key in CONSTRAINT_KEYS:
        if key not in constraints:
            out.append(_b("LM.CONSTRAINTS",
                          f"learner_model.constraints.{key} 缺失（learner-model.md §6 五栏）"))

    transitions = lm.get("transitions") or []
    if not transitions:
        out.append(_b("LM.NO_TRANSITION", "learner_model.transitions 为空"))

    t_ids: set[str] = set()
    for i, tr in enumerate(transitions):
        if not isinstance(tr, dict):
            out.append(_b("LM.TRANSITION", f"transitions[{i}] 不是对象"))
            continue
        tid = str(tr.get("id") or f"t{i + 1}")
        t_ids.add(tid)
        before, after = tr.get("from_state"), tr.get("to_state")
        if not _nonempty(before) or not _nonempty(after):
            out.append(_b("LM.STATE_EMPTY",
                          f"{tid} 缺 from_state/to_state：没有认知状态变化就不该有这个转变"))
        elif str(before).strip() == str(after).strip():
            out.append(_b("LM.STATE_NO_CHANGE", f"{tid} 的 from_state 与 to_state 相同"))
        op = tr.get("cognitive_operation")
        if op not in COGNITIVE_OPERATIONS:
            out.append(_b("LM.OPERATION",
                          f"{tid}.cognitive_operation「{op}」不在五种内（learner-model.md §3）"))
        ob = tr.get("obstacle")
        if ob not in OBSTACLES:
            out.append(_b("LM.OBSTACLE",
                          f"{tid}.obstacle「{ob}」不在六种内（learner-model.md §5）"))
        if not _nonempty(tr.get("success_condition")):
            out.append(_b("LM.SUCCESS_CONDITION",
                          f"{tid} 无可观察的 success_condition，无法验收学习结果"))
        load = tr.get("load")
        budget = constraints.get("load_budget") if isinstance(constraints, dict) else None
        if isinstance(load, int) and isinstance(budget, int) and load > budget:
            out.append(_w("LM.OVERLOAD", f"{tid} 引入 {load} 个新变量 > load_budget={budget}"))
        if not _nonempty(lm.get("ordering_rationale")):
            out.append(_w("LM.ORDER_UNJUSTIFIED",
                          "未记录顺序胜出依据：多条合法线性化时必须写明用了哪条优先级"))

    # 状态链连通：t(i).to_state == t(i+1).from_state
    seq = [t for t in transitions if isinstance(t, dict)]
    for prev, cur in zip(seq, seq[1:]):
        if _nonempty(prev.get("to_state")) and _nonempty(cur.get("from_state")) \
                and str(prev["to_state"]).strip() != str(cur["from_state"]).strip():
            out.append(_b("LM.CHAIN_BROKEN",
                          f"{prev.get('id')} 的 to_state 与 {cur.get('id')} 的 from_state 不接"))

    # P5 主闸：Beat 数必须等于（Merge Test 后的）转变数
    if transitions and beats and len(beats) != len(transitions):
        out.append(_b("P5.BEAT_COUNT",
                      f"Beat 数 {len(beats)} ≠ Transition 数 {len(transitions)}："
                      "Beat 数由不可合并的认知转变决定（principles P5）"))
    return t_ids


# ---------------------------------------------------------------- Expression Plan

def check_beats(beats: list[tuple[str, dict]], scenes: list[dict],
                km: dict | None, layout: dict | None, out: list[Finding]) -> None:
    evidence_ids = set()
    if isinstance(km, dict):
        for ev in km.get("evidence") or []:
            if isinstance(ev, dict) and _nonempty(ev.get("id")):
                evidence_ids.add(str(ev["id"]))

    covered: set[str] = set()
    for sid, sc in scenes:
        for ref in sc.get("beat_refs") or []:
            covered.add(str(ref))
    orphans = [bid for bid, _ in beats if bid not in covered]
    if orphans:
        out.append(_b("EP.ORPHAN_BEAT",
                      "这些 Beat 没有落进任何 Scene：" + ", ".join(orphans)))

    for bid, beat in beats:
        before, after = beat.get("state_before"), beat.get("state_after")
        if not _nonempty(before) or not _nonempty(after):
            out.append(_b("EP.STATE_EMPTY", f"{bid} 缺 state_before/state_after"))
        elif str(before).strip() == str(after).strip():
            out.append(_b("EP.STATE_NO_CHANGE", f"{bid} 的状态差为空"))

        op = beat.get("cognitive_operation")
        if op and op not in COGNITIVE_OPERATIONS:
            out.append(_b("EP.OPERATION", f"{bid}.cognitive_operation「{op}」非法"))
        ob = beat.get("obstacle")
        if ob and ob not in OBSTACLES:
            out.append(_b("EP.OBSTACLE", f"{bid}.obstacle「{ob}」非法"))

        for ref in beat.get("evidence_refs") or []:
            if evidence_ids and str(ref) not in evidence_ids:
                out.append(_b("EP.EVIDENCE_DANGLING",
                              f"{bid} 引用了不存在的 evidence「{ref}」"))

        if not _nonempty(beat.get("narration_goal")):
            out.append(_b("EP.NARRATION_GOAL",
                          f"{bid} 缺 narration_goal：先定要说什么，再写台词（expression-plan.md §11）"))
        if not _nonempty(beat.get("visual_goal")):
            out.append(_b("EP.VISUAL_GOAL", f"{bid} 缺 visual_goal：不画会卡在哪"))

        goal = beat.get("expression_goal") or {}
        if isinstance(goal, dict) and not _nonempty(goal.get("attention_target")):
            out.append(_b("EP.ATTENTION",
                          f"{bid}.expression_goal.attention_target 为空：这一 Beat 要观众注意什么"))

        narr = beat.get("narrative") or {}
        if isinstance(narr, dict):
            if narr.get("function") not in NARRATIVE_FUNCTIONS:
                out.append(_b("EP.NARRATIVE_FUNCTION",
                              f"{bid}.narrative.function「{narr.get('function')}」不在八种内"))
            if not _nonempty(narr.get("spans")):
                out.append(_b("EP.NARRATIVE_SPANS", f"{bid}.narrative.spans 为空"))

        vo = beat.get("visual_operation")
        if vo and vo not in VISUAL_OPERATIONS:
            out.append(_b("EP.VISUAL_OPERATION", f"{bid}.visual_operation「{vo}」不在十种内"))

        reveal = beat.get("reveal") or []
        spans = (narr.get("spans") or []) if isinstance(narr, dict) else []
        if not reveal:
            out.append(_b("EP.NO_REVEAL",
                          f"{bid} 没有 reveal 动作序列：画面不承担揭示（ir-alignment.md §5）"))
        for i, rv in enumerate(reveal):
            if not isinstance(rv, dict):
                out.append(_b("EP.REVEAL_SHAPE", f"{bid}.reveal[{i}] 不是对象"))
                continue
            rop = rv.get("op")
            if rop not in REVEAL_OPERATIONS:
                out.append(_b("EP.REVEAL_OP", f"{bid}.reveal[{i}].op「{rop}」不在八种内"))
            elif rop in REVEAL_UNSUPPORTED:
                out.append(_b("ISA.UNSUPPORTED_OP",
                              f"{bid}.reveal[{i}].op={rop} 目标机不支持（内核只加墨、无高亮/视口）；"
                              "按 expression-plan.md §5 改写：强调→加框、擦除→前后态并排、换尺度→切 Scene"))
            if not _nonempty(rv.get("target")):
                out.append(_b("EP.REVEAL_TARGET", f"{bid}.reveal[{i}] 缺 target"))
            if rv.get("bound_span") is None:
                out.append(_b("EP.REVEAL_UNBOUND",
                              f"{bid}.reveal[{i}] 未绑定 narration_span：时刻必须来自语音边界（P2）"))
            elif not spans:
                out.append(_b("EP.NARRATIVE_SPANS",
                              f"{bid}.narrative.spans 为空，reveal[{i}] 无 span 可绑"))
            else:
                try:
                    idx = int(rv["bound_span"])
                    if not 0 <= idx < len(spans):
                        out.append(_b("EP.SPAN_INDEX",
                                      f"{bid}.reveal[{i}].bound_span={idx} 越界"
                                      f"（spans 共 {len(spans)} 条）"))
                except (TypeError, ValueError):
                    out.append(_b("EP.SPAN_INDEX",
                                  f"{bid}.reveal[{i}].bound_span={rv['bound_span']!r} 不是合法索引"))
            if _nonempty(rv.get("at_ms")):
                out.append(_w("EP.HANDKEYED_TIME",
                              f"{bid}.reveal[{i}].at_ms 被手填：该值由 words.json 编译期回填（P2）"))

        alloc = beat.get("channel_allocation") or {}
        if isinstance(alloc, dict):
            for key in alloc:
                if key not in CHANNELS:
                    out.append(_b("EP.CHANNEL", f"{bid}.channel_allocation 键「{key}」非法"))
            if not any(_nonempty(alloc.get(k)) for k in CHANNELS):
                out.append(_b("EP.CHANNEL_EMPTY",
                              f"{bid} 没有通道分配：VERBAL/VISUAL/SHARED 三问未答（P6）"))

        for i, el in enumerate(beat.get("elements") or []):
            if not isinstance(el, dict):
                out.append(_b("EP.ELEMENT_SHAPE", f"{bid}.elements[{i}] 不是对象"))
                continue
            if not _nonempty(el.get("semantic_role")) or not _nonempty(el.get("cognitive_function")):
                out.append(_b("P6.ELEMENT_NO_ROLE",
                              f"{bid}.elements[{i}] 答不出「代表什么 / 承担哪次认知职责」"))
            if not _nonempty(el.get("used_by")):
                out.append(_w("P6.ORNAMENT",
                              f"{bid}.elements[{i}] used_by 为空：装饰元素应删（principles P6）"))
            if not _nonempty(el.get("introduced_at")):
                out.append(_w("EP.INTRODUCED_AT",
                              f"{bid}.elements[{i}] 未记录引入 Beat，无法查领先违规"))

    # panels ↔ elements 一一对应（Board 层事实，engine-design.md §13）
    if isinstance(layout, dict):
        for sid, sc in scenes:
            panels = (layout.get(sid) or layout.get("scenes", {}).get(sid) or {}).get("panels") or []
            elements = sc.get("elements") or []
            if panels and len(panels) != len(elements):
                out.append(_b("BOARD.PANEL_ELEMENT_MISMATCH",
                              f"{sid}：panels {len(panels)} 个 ≠ elements {len(elements)} 个，"
                              "标注器会降级为均分（principles P2）"))
            if len(panels) > 4 or (panels and len(panels) < 2):
                out.append(_w("BOARD.PANEL_COUNT",
                              f"{sid}：揭示单元 {len(panels)} 个，超出建议的 2 至 4（quality-checklist.md）"))


def check_scenes_format(scenes: list[tuple[str, dict]], out: list[Finding]) -> None:
    """校验 scenes[] 的基本格式：id 字段、命名规范、elements 格式。

    这是渲染管线的前置条件——字段名错误会导致 annotation matched=0/0，
    进而导致渲染失败"零绘制任务"。在 lint 阶段拦截，避免到渲染才暴露。
    """
    import re
    scene_id_pattern = re.compile(r"^scene-\d{2}$")

    for i, (sid, sc) in enumerate(scenes):
        # 1. 必须有 "id" 字段（不能是 "scene_id"）
        if "id" not in sc:
            if "scene_id" in sc:
                out.append(_b("SCENE.ID_FIELD_MISSING",
                    f"第{i+1}幕：用了 scene_id 而非 id，annotation 生成器读不到，会导致 matched=0/0。"
                    f"修复：把 scene_id 改为 id"))
            else:
                out.append(_b("SCENE.ID_FIELD_MISSING",
                    f"第{i+1}幕：缺 id 字段，annotation 生成器会回退为 scene-{i+1:02d}，"
                    f"可能与板图文件名不匹配"))

        # 2. 场景 id 命名规范（不能有 scene-03b）
        if "id" in sc and not scene_id_pattern.match(str(sc["id"])):
            out.append(_b("SCENE.ID_BAD_FORMAT",
                f"第{i+1}幕：id='{sc['id']}' 不符合 scene-XX 格式（如 scene-03b）。"
                f"非标准命名会导致 sync-boards 后场景错位。修复：统一为 scene-{i+1:02d}"))

        # 3. elements 格式校验
        elements = sc.get("elements") or []
        for j, el in enumerate(elements):
            # 必须有 "id" 字段，格式为 "panel-N"
            if "id" not in el:
                if "panel" in el:
                    out.append(_b("SCENE.ELEMENT_ID_FIELD_MISSING",
                        f"{sid} 第{j+1}个 element：用了 panel:{el['panel']} 而非 id:'panel-N'。"
                        f"annotation 生成器读不到，会导致 matched=0/0。"
                        f"修复：把 panel 改为 id:'panel-{el['panel']}'"))
                else:
                    out.append(_b("SCENE.ELEMENT_ID_FIELD_MISSING",
                        f"{sid} 第{j+1}个 element：缺 id 字段（应为 'panel-N' 格式）"))
            elif not str(el["id"]).startswith("panel-"):
                out.append(_b("SCENE.ELEMENT_ID_BAD_FORMAT",
                    f"{sid} 第{j+1}个 element：id='{el['id']}' 不符合 panel-N 格式"))

            # phrase 必须是非空字符串
            phrase = el.get("phrase") or el.get("text") or ""
            if not phrase:
                out.append(_w("SCENE.ELEMENT_PHRASE_EMPTY",
                    f"{sid} 第{j+1}个 element：phrase 为空，annotation 会退回区内均分，手笔时序不精准"))


def lint_script(doc: dict, layout: dict | None = None) -> list[Finding]:
    """校验一期 script.json，返回 findings（不抛异常）。"""
    out: list[Finding] = []
    scenes = [(str(sc.get("id") or f"scene-{i + 1:02d}"), sc)
              for i, sc in enumerate(doc.get("scenes") or [])]
    # 先校验 scenes 基本格式（字段名错误会导致后续所有校验失效）
    check_scenes_format(scenes, out)
    beats: list[tuple[str, dict]] = []
    for sid, sc in scenes:
        for j, beat in enumerate(sc.get("beats") or []):
            if isinstance(beat, dict):
                beats.append((str(beat.get("id") or f"{sid}-b{j + 1}"), beat))

    km = doc.get("knowledge_model")
    check_knowledge_model(km, out)
    t_ids = check_learner_model(doc.get("learner_model"), beats, out)
    check_beats(beats, scenes, km if isinstance(km, dict) else None, layout, out)

    if isinstance(km, dict):
        claim = str((km.get("target_claim") or "")).strip()
        core = str((km.get("model") or {}).get("core") if isinstance(km.get("model"), dict)
                   else km.get("model")).strip()
        if claim and core and claim == core:
            out.append(_b("KM.CLAIM_IS_MODEL",
                          "target_claim 与 model.core 完全相同：只有结论没有机制（knowledge-model.md §7）"))
    return out


def lint_episode(episode_dir: Path) -> list[Finding]:
    script = Path(episode_dir) / "input" / "script.json"
    if not script.exists():
        return [_b("IR.NO_SCRIPT", f"缺 {script}")]
    try:
        doc = json.loads(script.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [_b("IR.BAD_JSON", f"script.json 解析失败：{e}")]
    layout = None
    layout_path = Path(episode_dir) / "input" / "layout.json"
    if layout_path.exists():
        try:
            layout = json.loads(layout_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return [_b("IR.BAD_LAYOUT", f"layout.json 解析失败：{e}")]
    return lint_script(doc, layout)


def summarize(findings: list[Finding]) -> str:
    blocks, warns = _blocks(findings), [f for f in findings if f.severity == "warning"]
    lines = [str(f) for f in findings]
    lines.append(f"lint：阻断 {len(blocks)} 项，警告 {len(warns)} 项")
    return "\n".join(lines)
