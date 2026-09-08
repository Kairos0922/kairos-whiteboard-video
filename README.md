# kairos-whiteboard-video

**知识 → 白板讲解视频的编译器**：输入任意知识（一篇文章、一个机制、一种观点或争议），
产出一支「边讲边画、音画逐词对齐」的手绘风讲解视频。无需剪辑软件，全程由一套固定规则的
管线完成：知识语义 IR → 认知路径（转变规划）→ 表达编译 → 认知时间线 → 渲染合成。

## 核心特性

- **认知先行的内容设计**：先建 `knowledge_model`（目标主张 / 任务类型 / 心智模型 / 证据）
  与 `learner_model`（约束求解 + 转变规划 + Merge/Split Test），再由表达编译层把每个认知步
  映射为 `DRAW / CONNECT / GROUP / ANNOTATE` 等揭示操作与旁白；Beat 数 = 不可合并的认知
  转变数，不由内容长度决定。判据见 `references/` 方法论（约 2000 行规范）。
- **音画逐词对齐**：所有时间只认真实语音边界（`words.json` 词级时间戳）。字幕逐字高亮、
  画笔逐词推进，画面严格跟随讲解进度揭示——「画面不得无理由领先认知」。
- **三次确认质量门**：内容方向 → 视觉方案 → 最终产物。每次确认支持「整体确认 + 局部修改」，
  其余环节机器全自动执行。
- **主题包（跨期复用轴）**：画风（风格块经宿主模型探针验证后冻结）、手笔素材（含笔尖
  锚点校准）、声音身份均随主题封装；换主题只改一处。
- **渲染引擎**：OpenCV 内核实现分区时序揭示 + 骨架描线 + 蛇形填色；各幕并行渲染
  （7 幕约 1 分钟）；`validate` 自动检查（零阻断才交付）。

## 目录结构

```
SKILL.md            —— 技能总纲（用户路径 / 铁律 / 环境命令）
references/         —— 方法论规范（principles / knowledge-model / learner-model / ...）
engine/             —— Python 引擎（uv 工程；workflow.py 编译管线 + build_video.py 渲染）
themes/             —— 主题包（registry.json 只登记经探针冻结的主题）
projects/<ep-id>/   —— 单期现场（不入库；短周期产物，可由 input/ + 引擎重跑再生）
```

## 快速开始

```bash
cd engine && uv sync                                   # 首次或依赖变化时
uv run python scripts/workflow.py init --title <标题>  # 初始化一期（推荐先读 SKILL.md）
uv run python scripts/workflow.py <command> --episode-dir ../projects/<ep-id>
uv run python scripts/build_video.py --episode-dir ../projects/<ep-id> <layout|annotate|render|assemble>
```

常用 `workflow.py` 命令：`init / status / sync-boards / voice / confirm-voice / prompts /
probe / lint / spans / import / confirm-boards / render / validate`。

- 环境：Python ≥ 3.11、ffmpeg、网络可用（edge-tts 配音与宿主模型板图生成需要）。
- 板图由**当前宿主的文生图模型**生成（Claude Code / Codex / DSH 均可）：引擎只写 prompt、
  收 PNG、检查、渲染；不调本地扩散、不调第三方生图服务。
- 声音默认音色见 `engine/defaults/voice.json`（`--voice` / `--rate` 可覆盖）。

## 测试

```bash
cd engine && uv sync && uv run pytest -q      # 60 用例，含 IR 契约 lint 与渲染内核
```

## License

MIT。渲染数学底座复用 MIT 项目
[whiteboard-video-engine](https://github.com/gnipbao/whiteboard-video-engine)（锁定 rev）。
