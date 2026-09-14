"""冒烟测试：workflow 状态机往返 + 板图自动检查 + chalk 墨迹判定。

运行（本工具目录先 uv sync，依赖 cv2/numpy/PIL）：
  uv run python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from test_ir_contract import legal_doc  # noqa: E402  夹具：IR 合法才能过 sync-boards 闸
from whiteboard_story import review_images  # noqa: E402
from whiteboard_story import prompt_builder  # noqa: E402
from workflow import cmd_import, cmd_init, cmd_prompts, cmd_status  # noqa: E402


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ep = Path(self.tmp.name) / "episode"
        self.args = type("Args", (), {"boards_dir": None, "out": None})()

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_status_prompts_roundtrip(self):
        self.assertEqual(cmd_init(self.ep, "测试片", self.args), 0)
        state = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(state["phases"]["script_audio_confirmed"])   # 新项目从待审起步
        self.assertFalse(state["phases"]["express_card_filled"])      # 表达设计卡第一步门
        # 三个确认标志全为 False = 无焊死的确认记录（schema v2：confirmations 为 dict）
        self.assertFalse(any(state["confirmations"].values()))
        express = (self.ep / "input" / "express-card.md").read_text(encoding="utf-8")
        self.assertIn("表达设计卡", express)
        self.assertIn("心智模型", express)
        self.assertEqual(len(state["boards"]), 0)
        self.assertEqual(cmd_status(self.ep, self.args), 0)
        (self.ep / "input/script.json").write_text(
            json.dumps(legal_doc(("scene-01", "scene-02")), ensure_ascii=False), encoding="utf-8")
        from workflow import cmd_sync_boards
        self.assertEqual(cmd_sync_boards(self.ep, self.args), 0)
        state = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        self.assertEqual([b["scene"] for b in state["boards"]], ["scene-01", "scene-02"])

    def test_import_accepts_paper_and_rejects_chalk(self):
        import cv2
        import numpy as np

        self.assertEqual(cmd_init(self.ep, "测试片", self.args), 0)
        (self.ep / "input/script.json").write_text(
            json.dumps(legal_doc(("scene-01", "scene-02")), ensure_ascii=False), encoding="utf-8")
        from workflow import cmd_sync_boards
        self.assertEqual(cmd_sync_boards(self.ep, self.args), 0)
        boards = self.ep / "boards"
        boards.mkdir()
        self.args.boards_dir = str(boards)
        good = np.zeros((1080, 1920, 3), np.uint8)
        good[:] = (235, 242, 245)  # 暖白纸面 BGR（paper 模式，四角亮度 > 185）
        # 补足内容以通过空白闸门（std≥15 且边缘占比≥0.5%，review_images 新契约）
        for i in range(24):
            cv2.line(good, (300, 80 + i * 40), (1500, 80 + i * 40), (60, 60, 60), 2)
        cv2.imwrite(str(boards / "scene-01.png"), good)
        bad = np.zeros((1080, 1920, 3), np.uint8)
        bad[:] = (48, 58, 32)  # #203A30 黑板绿 BGR：paper 模式判「不像纸面白」
        cv2.imwrite(str(boards / "scene-02.png"), bad)
        rc = cmd_import(self.ep, self.args)
        self.assertEqual(rc, 2)
        state = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        by_scene = {b["scene"]: b for b in state["boards"]}
        self.assertEqual(by_scene["scene-01"]["status"], "ok")
        self.assertEqual(by_scene["scene-02"]["status"], "failed")
        self.assertFalse(state["phases"]["boards_reviewed"])

    def test_import_from_build_boards_in_place(self):
        """--boards-dir 就是 build/boards（SKILL 文档用法）时不能自复制崩溃。"""
        import cv2
        import numpy as np

        self.assertEqual(cmd_init(self.ep, "测试片", self.args), 0)
        (self.ep / "input/script.json").write_text(
            json.dumps(legal_doc(("scene-01",)), ensure_ascii=False), encoding="utf-8")
        from workflow import cmd_sync_boards
        self.assertEqual(cmd_sync_boards(self.ep, self.args), 0)
        boards = self.ep / "build" / "boards"
        boards.mkdir(parents=True, exist_ok=True)
        good = np.zeros((1080, 1920, 3), np.uint8)
        good[:] = (235, 242, 245)  # 暖白纸面：合法板图
        for i in range(24):
            cv2.line(good, (300, 80 + i * 40), (1500, 80 + i * 40), (60, 60, 60), 2)
        cv2.imwrite(str(boards / "scene-01.png"), good)
        self.args.boards_dir = str(boards)
        self.assertEqual(cmd_import(self.ep, self.args), 0)
        state = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["boards"][0]["status"], "ok")
        self.assertTrue((boards / "scene-01.png").exists())


class IRLintGateTest(unittest.TestCase):
    """旧式 script.json（只有幕 + 旁白 + 分区）不再能进现场阶段：文档层不再是真相源。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ep = Path(self.tmp.name) / "episode"
        self.args = type("Args", (), {})()

    def tearDown(self):
        self.tmp.cleanup()

    def _legacy_script(self):
        (self.ep / "input").mkdir(parents=True, exist_ok=True)
        (self.ep / "input/script.json").write_text(json.dumps({
            "scenes": [{"id": "scene-01", "narration": "一。", "board_subject": "一个杯子",
                        "elements": [{"id": "panel-1", "phrase": "一"}]}]
        }, ensure_ascii=False), encoding="utf-8")

    def test_sync_boards_blocked_without_ir(self):
        from workflow import cmd_init, cmd_sync_boards
        self.assertEqual(cmd_init(self.ep, "旧结构片", self.args), 0)
        self._legacy_script()
        self.assertEqual(cmd_sync_boards(self.ep, self.args), 1)
        state = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        self.assertEqual([], state["boards"])          # 被拦时不写现场

    def test_lint_reports_missing_ir_and_exit_code(self):
        from workflow import cmd_init, cmd_lint
        self.assertEqual(cmd_init(self.ep, "旧结构片", self.args), 0)
        self._legacy_script()
        self.assertEqual(cmd_lint(self.ep, self.args), 1)

    def test_legal_ir_passes_lint(self):
        from workflow import cmd_init, cmd_lint
        self.assertEqual(cmd_init(self.ep, "合规片", self.args), 0)
        (self.ep / "input").mkdir(parents=True, exist_ok=True)
        (self.ep / "input/script.json").write_text(
            json.dumps(legal_doc(), ensure_ascii=False), encoding="utf-8")
        self.assertEqual(cmd_lint(self.ep, self.args), 0)

    def test_confirm_content_blocks_ir_contract_violations(self):
        """第1次确认必须真的消费 lint 的阻断项：缺 IR 不得被确认（principles P5）。"""
        from workflow import cmd_confirm_content, cmd_init
        self.assertEqual(cmd_init(self.ep, "旧结构片", self.args), 0)
        self._legacy_script()
        self.assertEqual(cmd_confirm_content(self.ep, self.args), 3)
        state = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(state["confirmations"]["content_confirmed"])
        self.assertFalse(state["phases"]["express_card_filled"])

    def test_confirm_content_sets_gate_flags_on_legal_ir(self):
        from workflow import cmd_confirm_content, cmd_init
        self.assertEqual(cmd_init(self.ep, "合规片", self.args), 0)
        (self.ep / "input").mkdir(parents=True, exist_ok=True)
        (self.ep / "input/script.json").write_text(
            json.dumps(legal_doc(), ensure_ascii=False), encoding="utf-8")
        self.assertEqual(cmd_confirm_content(self.ep, self.args), 0)
        state = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(state["confirmations"]["content_confirmed"])
        self.assertTrue(state["phases"]["express_card_filled"])
        self.assertTrue(state["phases"]["script_audio_confirmed"])


class CheckBoardTest(unittest.TestCase):
    def _img(self, w, h, bgr):
        import cv2
        import numpy as np

        img = np.zeros((h, w, 3), np.uint8)
        img[:] = bgr
        return img

    def test_ok_board_passes(self):
        import cv2
        import tempfile
        import numpy as np

        img = self._img(1920, 1080, (235, 242, 245))  # 暖白纸面
        # 补足内容以通过空白闸门（std≥15 且边缘占比≥0.5%，review_images 新契约）
        for i in range(24):
            cv2.line(img, (300, 80 + i * 40), (1500, 80 + i * 40), (60, 60, 60), 2)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "b.png"
            cv2.imwrite(str(p), img)
            r = review_images.check_board(p)
        self.assertTrue(r["ok"], r["errors"])

    def test_wrong_aspect_fails(self):
        import cv2
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "b.png"
            cv2.imwrite(str(p), self._img(1080, 1080, (48, 58, 32)))
            r = review_images.check_board(p)
        self.assertFalse(r["ok"])
        self.assertTrue(any("16:9" in e for e in r["errors"]))

    def test_wrong_corner_color_fails(self):
        import cv2
        import tempfile
        import numpy as np

        img = self._img(1920, 1080, (48, 58, 32))  # 黑板绿：paper 模式下四角不达标
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "b.png"
            cv2.imwrite(str(p), img)
            r = review_images.check_board(p)
        self.assertFalse(r["ok"])


class VoiceWiringTest(unittest.TestCase):
    """voice → confirm-voice → validate 接线（mock edge-tts，不联网）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ep = Path(self.tmp.name) / "episode"
        self.args = type("Args", (), {"script": None, "voice": "zh-CN-YunxiNeural",
                                      "rate": "+0%", "force": False, "theme": None})()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_script(self):
        (self.ep / "input").mkdir(parents=True, exist_ok=True)
        (self.ep / "input/script.json").write_text(
            json.dumps({"scenes": [{"id": "scene-01", "narration": "测试。",
                                    "elements": []}]}, ensure_ascii=False),
            encoding="utf-8")

    def _fake_make_voice(self, script, episode_dir, voice="zh-CN-YunxiNeural",
                         rate="+0%", volume="+0%", pitch="+0Hz"):
        ep = Path(episode_dir)
        (ep / "input").mkdir(parents=True, exist_ok=True)
        words = {"granularity": "word", "duration_ms": 3000,
                 "scenes": [{"scene_index": 0, "start_ms": 0, "end_ms": 3000}],
                 "words": [{"scene_index": 0, "text": "测试",
                            "start_ms": 0, "end_ms": 900}]}
        (ep / "input/words.json").write_text(
            json.dumps(words, ensure_ascii=False), encoding="utf-8")
        (ep / "input/narration.mp3").write_bytes(b"mp3-bytes")
        (ep / "input/captions.srt").write_text(
            "1\n00:00:00,000 --> 00:00:03,000\n测试。\n", encoding="utf-8")
        return {"durations_ms": [3000], "total_ms": 3000, "word_count": 1,
                "words_json": ep / "input" / "words.json"}

    def test_voice_does_not_confirm_confirm_writes_fingerprints(self):
        import unittest.mock as mock

        from workflow import cmd_confirm_voice, cmd_init, cmd_voice
        self.assertEqual(cmd_init(self.ep, "接线片", self.args), 0)
        self._write_script()
        with mock.patch("whiteboard_story.providers.voice.make_voice",
                        side_effect=self._fake_make_voice) as mv:
            self.assertEqual(cmd_voice(self.ep, self.args), 0)
            self.assertEqual(mv.call_count, 1)
        state = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(state["phases"]["script_audio_confirmed"])  # 合成≠确认
        self.assertNotIn("voice_fingerprints", state)
        # 三件套不齐时确认必须拒绝
        (self.ep / "input/captions.srt").unlink()
        rc_missing = type("Args", (), {})()
        self.assertEqual(cmd_confirm_voice(self.ep, rc_missing), 1)
        self._fake_make_voice(None, self.ep)   # 补回文件
        self.assertEqual(cmd_confirm_voice(self.ep, type("Args", (), {})()), 0)
        state = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(state["phases"]["script_audio_confirmed"])
        fp = state["voice_fingerprints"]
        self.assertEqual(set(fp), {"narration.mp3", "captions.srt", "words.json"})
        from whiteboard_story.providers.voice import compute_voice_fingerprints
        self.assertEqual(fp, compute_voice_fingerprints(self.ep / "input"))

    def test_voice_after_confirm_requires_force(self):
        import unittest.mock as mock

        from workflow import cmd_init, cmd_voice
        self.assertEqual(cmd_init(self.ep, "闸门片", self.args), 0)
        self._write_script()
        st = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        st["phases"]["script_audio_confirmed"] = True
        (self.ep / "state.json").write_text(json.dumps(st, ensure_ascii=False),
                                            encoding="utf-8")
        with mock.patch("whiteboard_story.providers.voice.make_voice") as mv:
            self.assertEqual(cmd_voice(self.ep, self.args), 3)     # 无 --force 拦下
            mv.assert_not_called()
            self.args.force = True
            # force 放行后正常合成
            with mock.patch("whiteboard_story.providers.voice.make_voice",
                            side_effect=self._fake_make_voice):
                self.assertEqual(cmd_voice(self.ep, self.args), 0)
        # 已确认状态未被 voice 重合成破坏（force 只放行合成，不代作确认）
        st2 = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(st2["phases"]["script_audio_confirmed"])

    def test_validate_wiring_reports_and_writes_file(self):
        from workflow import cmd_init, cmd_validate
        self.assertEqual(cmd_init(self.ep, "验收片", self.args), 0)
        rc = cmd_validate(self.ep, self.args)
        self.assertEqual(rc, 1)          # 空项目必有阻断（缺三件套、缺成片）
        report = (self.ep / "build/review/validate-report.md").read_text(encoding="utf-8")
        self.assertIn("阻断项", report)
        self.assertIn("口播指纹复核", report)


class VoiceIdentityTest(unittest.TestCase):
    """声音身份解析与一致性（2026-08-28：主题 voice 块 > CLI 覆盖 > 内建默认）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ep = Path(self.tmp.name) / "episode"
        self.theme = Path(self.tmp.name) / "theme.json"
        self.theme.write_text(json.dumps({"voice": {
            "backend": "edge-tts", "name": "zh-CN-YunyangNeural", "rate": "+5%"}},
            ensure_ascii=False), encoding="utf-8")
        self.args = type("Args", (), {"script": None, "voice": None, "rate": None,
                                      "theme": None, "force": False})()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_script(self):
        (self.ep / "input").mkdir(parents=True, exist_ok=True)
        (self.ep / "input/script.json").write_text(
            json.dumps({"scenes": [{"id": "scene-01", "narration": "测试。",
                                    "elements": []}]}, ensure_ascii=False),
            encoding="utf-8")

    def _fake_make_voice(self, script, episode_dir, voice="zh-CN-YunxiNeural",
                         rate="+0%", volume="+0%", pitch="+0Hz"):
        ep = Path(episode_dir)
        (ep / "input").mkdir(parents=True, exist_ok=True)
        words = {"granularity": "word", "voice": voice, "duration_ms": 3000,
                 "scenes": [{"scene_index": 0, "start_ms": 0, "end_ms": 3000}],
                 "words": [{"scene_index": 0, "text": "测试",
                            "start_ms": 0, "end_ms": 900}]}
        (ep / "input/words.json").write_text(
            json.dumps(words, ensure_ascii=False), encoding="utf-8")
        (ep / "input/narration.mp3").write_bytes(b"mp3-bytes")
        (ep / "input/captions.srt").write_text(
            "1\n00:00:00,000 --> 00:00:03,000\n测试。\n", encoding="utf-8")
        return {"durations_ms": [3000], "total_ms": 3000, "word_count": 1,
                "words_json": ep / "input" / "words.json"}

    def test_theme_default_and_cli_override_and_state_persistence(self):
        import unittest.mock as mock

        from workflow import cmd_init, cmd_voice
        self.assertEqual(cmd_init(self.ep, "身份片", self.args), 0)
        self._write_script()
        # 1) 主题默认生效并落 state
        self.args.theme = str(self.theme)
        with mock.patch("whiteboard_story.providers.voice.make_voice",
                        side_effect=self._fake_make_voice) as mv:
            self.assertEqual(cmd_voice(self.ep, self.args), 0)
            _, kwargs = mv.call_args
            self.assertEqual(kwargs["voice"], "zh-CN-YunyangNeural")   # 主题默认
            self.assertEqual(kwargs["rate"], "+5%")
        state = json.loads((self.ep / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["voice_identity"]["name"], "zh-CN-YunyangNeural")
        self.assertEqual(state["theme"], str(self.theme))              # 首传即登记
        # 2) CLI 显式覆盖主题
        self.args.voice = "zh-CN-XiaoxiaoNeural"
        with mock.patch("whiteboard_story.providers.voice.make_voice",
                        side_effect=self._fake_make_voice) as mv:
            self.assertEqual(cmd_voice(self.ep, self.args), 0)
            _, kwargs = mv.call_args
            self.assertEqual(kwargs["voice"], "zh-CN-XiaoxiaoNeural")  # CLI 优先
        # 3) --theme 免传：state.theme 已登记，主题默认继续生效
        self.args.voice = None
        self.args.theme = None
        with mock.patch("whiteboard_story.providers.voice.make_voice",
                        side_effect=self._fake_make_voice) as mv:
            self.assertEqual(cmd_voice(self.ep, self.args), 0)
            _, kwargs = mv.call_args
            self.assertEqual(kwargs["voice"], "zh-CN-YunyangNeural")

    def test_validate_warns_on_voice_identity_drift(self):
        import unittest.mock as mock

        from whiteboard_story import validate
        from workflow import cmd_init, cmd_voice
        self.assertEqual(cmd_init(self.ep, "漂移片", self.args), 0)
        self._write_script()
        self.args.theme = str(self.theme)
        with mock.patch("whiteboard_story.providers.voice.make_voice",
                        side_effect=self._fake_make_voice):
            self.assertEqual(cmd_voice(self.ep, self.args), 0)
        # words.json 声音与 state 身份一致 → 无漂移警告
        blockers, warnings, _ = validate.validate(self.ep)
        self.assertFalse(any("声音身份漂移" in w for w in warnings))
        # 篡改 words.json 的 voice → 漂移警告
        wd = json.loads((self.ep / "input/words.json").read_text(encoding="utf-8"))
        wd["voice"] = "zh-CN-SomeoneElseNeural"
        (self.ep / "input/words.json").write_text(
            json.dumps(wd, ensure_ascii=False), encoding="utf-8")
        blockers, warnings, _ = validate.validate(self.ep)
        self.assertTrue(any("声音身份漂移" in w for w in warnings),
                        f"应报漂移警告：{warnings}")


class PromptBuilderTest(unittest.TestCase):
    def test_prompts_writes_host_payload_not_local_t2i(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        ep = Path(tmp.name) / "episode"
        theme = Path(tmp.name) / "theme"
        theme.mkdir()
        (theme / "style-block.txt").write_text("细彩铅白纸手绘。", encoding="utf-8")
        args = type("Args", (), {})()
        self.assertEqual(cmd_init(ep, "词表片", args), 0)
        (ep / "input/script.json").write_text(json.dumps({
            "scenes": [{"id": "scene-01", "narration": "杯子。",
                        "board_subject": "一只白瓷杯放在空白纸上"}]
        }, ensure_ascii=False), encoding="utf-8")
        args.theme = str(theme)
        args.scene = None
        self.assertEqual(cmd_prompts(ep, args), 0)
        payload = json.loads((ep / "input/prompts/scene-01.prompt.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["width"], 1920)
        self.assertEqual(payload["height"], 1080)
        self.assertIn("白瓷杯", payload["prompt"])
        self.assertIn("不要出现可读文字", payload["prompt"])
        self.assertIn("允许无文字的箭头", payload["prompt"])
        self.assertNotIn("text2image", payload["prompt"])
        self.assertNotIn("mflux", payload["prompt"])


# 渲染内核相关测试（原 ChalkThrTest：stream_render 墨迹判定）随内核待补一并暂停，
# 补回内核时从 git 历史恢复该测试类。

if __name__ == "__main__":
    unittest.main()
