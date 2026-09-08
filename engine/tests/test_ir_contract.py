"""ir_contract 静态校验的行为测试：每条 blocking 都要能被单独触发，合法夹具必须零阻断。"""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from whiteboard_story import ir_contract as ic  # noqa: E402


def _beat(bid="b1", before=None, after=None, **over):
    beat = {
        "id": bid,
        "state_before": before if before is not None else "以为 AI 平庸是模型不行",
        "state_after": after if after is not None else "知道是逐词预测挑最安全答案",
        "cognitive_operation": "EXPLAIN",
        "obstacle": "MISSING",
        "evidence_refs": ["e1"],
        "narration_goal": "解释为什么要求随机也没用",
        "visual_goal": "不画出岔路口观众看不出它每次都选同一条",
        "expression_goal": {"attention_target": "那条粗的砖红路"},
        "narrative": {"function": "EXPLAIN", "spans": ["它每写一个词", "都挑最多人满意的"]},
        "visual_operation": "DECOMPOSE",
        "reveal": [
            {"op": "DRAW", "target": "brain", "bound_span": 0},
            {"op": "CONNECT", "target": "brain→safe", "bound_span": 1},
        ],
        "channel_allocation": {"verbal": ["因果"], "visual": ["布局"], "shared": ["最安全"]},
        "elements": [{"id": "brain", "semantic_role": "AI 内部", "cognitive_function": "承载机制",
                      "introduced_at": bid, "used_by": [bid]}],
    }
    beat.update(over)
    return beat


def legal_doc(scenes=("scene-01",)):
    """N 幕的合法夹具：N 个链式 transition + N 个 beat，一 Beat 一幕。

    供 test_workflow 复用——`sync-boards` 会先跑 IR 校验，夹具必须合法。
    """
    states = ["以为 AI 平庸是模型不行"] + [f"第 {i + 1} 步后持有的模型" for i in range(len(scenes))]
    transitions = []
    beats = []
    doc_scenes = []
    for i, sid in enumerate(scenes):
        bid = f"b{i + 1}"
        transitions.append({
            "id": f"t{i + 1}", "from_state": states[i], "to_state": states[i + 1],
            "cognitive_operation": "EXPLAIN", "obstacle": "MISSING",
            "success_condition": f"能说出第 {i + 1} 步的变化", "load": 1})
        beats.append({"id": bid, **{k: v for k, v in _beat(
            bid, before=states[i], after=states[i + 1]).items() if k != "id"}})
        doc_scenes.append({
            "id": sid, "beat_refs": [bid],
            "narration": "它每写一个词，都挑最多人满意的。",
            "board_subject": "大脑剖面与两条岔路",
            "beats": [beats[-1]],
            "elements": [{"id": "panel-1", "phrase": "每写一个词"}]})
    return {
        "knowledge_model": {
            "subject": "为什么 AI 做的设计都长一样",
            "target_claim": "AI 设计平庸是选择机制偏保守，随机性须由人从外部注入",
            "task_type": "A + C",
            "learner": {"prior_knowledge": ["用过 AI 生成页面"], "misconception": "我提示词写得不好",
                        "misconception_source": "评论区高频疑问"},
            "model": {"core": "逐词预测 → 挑最多人满意 → 结构性保守 → 外部注入随机",
                      "nodes": [{"id": "predict", "evidence": ["e1"]},
                                {"id": "conservative", "evidence": ["e1"]}],
                      "relations": [{"from": "predict", "to": "conservative", "type": "causes"}]},
            "learning_outcome": {"explanation": "说清为什么要求随机仍雷同",
                                 "application": "下次先跑代码拿随机字符"},
            "evidence": [{"id": "e1", "claim": "四个实例产出同构页面",
                          "source": "Technique 1", "confidence": "source-backed fact"}],
            "dependencies": ["知道提示词是什么"],
            "scope": {"include": ["为什么平庸", "注入随机"],
                      "exclude": [{"idea": "图像生成接 API", "reason": "纯工具配置"}]},
            "source_coverage": "部分（正文止于 Technique 6）",
        },
        "learner_model": {
            "constraints": {"prerequisites": ["知道提示词是什么"],
                            "misconceptions_to_resolve": ["提示词不好"],
                            "essential_relations": ["predict→conservative"],
                            "optional_details": ["作者前史"], "load_budget": 1},
            "ordering_rationale": "t2 先于 t3 依据 learner-model §8 规则 5",
            "transitions": transitions,
        },
        "scenes": doc_scenes,
    }


def _doc():
    return legal_doc()


def codes(findings):
    return {f.code for f in findings}


class HappyPathTest(unittest.TestCase):
    def test_clean_doc_has_no_blockers(self):
        findings = ic.lint_script(_doc())
        blockers = [f for f in findings if f.severity == "blocking"]
        self.assertEqual([], [str(b) for b in blockers])


class MissingIRTest(unittest.TestCase):
    def test_absent_ir_is_blocking(self):
        doc = {"scenes": [{"id": "scene-01", "narration": "x",
                           "elements": [{"id": "panel-1", "phrase": "x"}]}]}
        self.assertIn("KM.MISSING", codes(ic.lint_script(doc)))
        self.assertIn("LM.MISSING", codes(ic.lint_script(doc)))

    def test_beat_without_state_change_blocked(self):
        doc = _doc()
        doc["scenes"][0]["beats"][0]["state_after"] = doc["scenes"][0]["beats"][0]["state_before"]
        self.assertIn("EP.STATE_NO_CHANGE", codes(ic.lint_script(doc)))


class EnumerationTest(unittest.TestCase):
    def test_bad_cognitive_operation(self):
        doc = _doc()
        doc["learner_model"]["transitions"][0]["cognitive_operation"] = "MOTIVATE"
        self.assertIn("LM.OPERATION", codes(ic.lint_script(doc)))

    def test_bad_obstacle(self):
        doc = _doc()
        doc["scenes"][0]["beats"][0]["obstacle"] = "BOREDOM"
        self.assertIn("EP.OBSTACLE", codes(ic.lint_script(doc)))

    def test_bad_narrative_function(self):
        doc = _doc()
        doc["scenes"][0]["beats"][0]["narrative"]["function"] = "HOOK"
        self.assertIn("EP.NARRATIVE_FUNCTION", codes(ic.lint_script(doc)))

    def test_bad_task_type(self):
        doc = _doc()
        doc["knowledge_model"]["task_type"] = "E"
        self.assertIn("KM.TASK_TYPE", codes(ic.lint_script(doc)))

    def test_dangling_relation_and_evidence(self):
        doc = _doc()
        doc["knowledge_model"]["model"]["relations"][0]["to"] = "ghost"
        doc["scenes"][0]["beats"][0]["evidence_refs"] = ["e9"]
        found = codes(ic.lint_script(doc))
        self.assertIn("KM.RELATION_DANGLING", found)
        self.assertIn("EP.EVIDENCE_DANGLING", found)


class ISAConstraintTest(unittest.TestCase):
    """目标机指令集缺口：HIGHLIGHT / REMOVE / REFRAME 在实现前即非法。"""

    def test_unsupported_reveal_ops_blocked(self):
        for op in sorted(ic.REVEAL_UNSUPPORTED):
            doc = _doc()
            doc["scenes"][0]["beats"][0]["reveal"][0] = {"op": op, "target": "cache", "bound_span": 0}
            self.assertIn("ISA.UNSUPPORTED_OP", codes(ic.lint_script(doc)), msg=op)

    def test_supported_ops_pass(self):
        for op in ("DRAW", "CONNECT", "GROUP", "ANNOTATE"):
            doc = _doc()
            doc["scenes"][0]["beats"][0]["reveal"][0] = {"op": op, "target": "cache", "bound_span": 0}
            self.assertNotIn("ISA.UNSUPPORTED_OP", codes(ic.lint_script(doc)), msg=op)

    def test_reveal_without_span_binding_blocked(self):
        doc = _doc()
        doc["scenes"][0]["beats"][0]["reveal"][0].pop("bound_span")
        self.assertIn("EP.REVEAL_UNBOUND", codes(ic.lint_script(doc)))

    def test_handkeyed_time_warns_not_blocks(self):
        doc = _doc()
        doc["scenes"][0]["beats"][0]["reveal"][0]["at_ms"] = 1200
        findings = ic.lint_script(doc)
        self.assertIn("EP.HANDKEYED_TIME", codes(findings))
        self.assertEqual([], [f for f in findings if f.severity == "blocking"])


class P5CountTest(unittest.TestCase):
    def test_beat_count_must_equal_transition_count(self):
        doc = _doc()
        doc["scenes"][0]["beats"].append(_beat("b2"))
        self.assertIn("P5.BEAT_COUNT", codes(ic.lint_script(doc)))

    def test_orphan_beat_blocked(self):
        doc = _doc()
        doc["learner_model"]["transitions"].append({
            "id": "t2", "from_state": "知道是逐词预测挑最安全答案",
            "to_state": "知道随机须外部注入", "cognitive_operation": "APPLY",
            "obstacle": "GAP", "success_condition": "能说出第一步跑什么代码"})
        doc["scenes"][0]["beats"].append(_beat("b2"))
        doc["scenes"][0]["beat_refs"] = ["b1"]        # b2 没落幕
        found = codes(ic.lint_script(doc))
        self.assertIn("EP.ORPHAN_BEAT", found)


class QualityRuleTest(unittest.TestCase):
    def test_empty_scope_exclude_blocked(self):
        doc = _doc()
        doc["knowledge_model"]["scope"]["exclude"] = []
        self.assertIn("KM.SCOPE", codes(ic.lint_script(doc)))

    def test_claim_equals_model_blocked(self):
        doc = _doc()
        same = "同一句话"
        doc["knowledge_model"]["target_claim"] = same
        doc["knowledge_model"]["model"]["core"] = same
        self.assertIn("KM.CLAIM_IS_MODEL", codes(ic.lint_script(doc)))

    def test_evidence_without_source_blocked(self):
        doc = _doc()
        doc["knowledge_model"]["evidence"][0]["source"] = "  "
        self.assertIn("KM.EVIDENCE_SOURCE", codes(ic.lint_script(doc)))

    def test_bad_confidence_blocked(self):
        doc = _doc()
        doc["knowledge_model"]["evidence"][0]["confidence"] = "obvious"
        self.assertIn("KM.EVIDENCE_CONFIDENCE", codes(ic.lint_script(doc)))

    def test_ornament_element_warns(self):
        doc = _doc()
        doc["scenes"][0]["beats"][0]["elements"].append(
            {"id": "sparkle", "semantic_role": "装饰星光", "cognitive_function": "让画面不空",
             "introduced_at": "b1", "used_by": []})
        self.assertIn("P6.ORNAMENT", codes(ic.lint_script(doc)))

    def test_element_without_role_blocked(self):
        doc = _doc()
        doc["scenes"][0]["beats"][0]["elements"][0]["cognitive_function"] = ""
        self.assertIn("P6.ELEMENT_NO_ROLE", codes(ic.lint_script(doc)))

    def test_chain_break_blocked(self):
        doc = _doc()
        doc["learner_model"]["transitions"].append({
            "id": "t2", "from_state": "另一个起点", "to_state": "知道随机须外部注入",
            "cognitive_operation": "APPLY", "obstacle": "GAP", "success_condition": "能复述第一步"})
        doc["scenes"][0]["beats"].append(_beat("b2"))
        self.assertIn("LM.CHAIN_BROKEN", codes(ic.lint_script(doc)))

    def test_channel_allocation_empty_blocked(self):
        doc = _doc()
        doc["scenes"][0]["beats"][0]["channel_allocation"] = {}
        self.assertIn("EP.CHANNEL_EMPTY", codes(ic.lint_script(doc)))

    def test_missing_attention_target_blocked(self):
        doc = _doc()
        doc["scenes"][0]["beats"][0]["expression_goal"] = {}
        self.assertIn("EP.ATTENTION", codes(ic.lint_script(doc)))


class BoardGateTest(unittest.TestCase):
    def test_panel_element_mismatch_blocked(self):
        doc = _doc()
        layout = {"scene-01": {"panels": [{"x": 0, "y": 0, "w": 10, "h": 10},
                                          {"x": 20, "y": 0, "w": 10, "h": 10}]}}
        self.assertIn("BOARD.PANEL_ELEMENT_MISMATCH", codes(ic.lint_script(doc, layout)))

    def test_matching_panels_pass(self):
        doc = _doc()
        layout = {"scene-01": {"panels": [{"x": 0, "y": 0, "w": 10, "h": 10}]}}
        self.assertNotIn("BOARD.PANEL_ELEMENT_MISMATCH", codes(ic.lint_script(doc, layout)))


class MutationSafetyTest(unittest.TestCase):
    """校验器不得改入参，也不得因单条数据畸形而抛异常。"""

    def test_does_not_mutate_input(self):
        doc = _doc()
        snapshot = copy.deepcopy(doc)
        ic.lint_script(doc)
        self.assertEqual(snapshot, doc)

    def test_malformed_entries_do_not_raise(self):
        doc = _doc()
        doc["knowledge_model"]["evidence"] = ["not-a-dict"]
        doc["scenes"][0]["beats"][0]["reveal"] = ["nope"]
        doc["scenes"][0]["beats"][0]["elements"] = [None]
        doc["learner_model"]["transitions"] = ["bad"]
        findings = ic.lint_script(doc)
        self.assertTrue(any(f.severity == "blocking" for f in findings))


if __name__ == "__main__":
    unittest.main()
