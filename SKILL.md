---
name: kairos-whiteboard-video
description: >
  知识 → 白板视频编译器：输入任意知识（文章 / 现象 / 机制 / 观点 / 争议），产出边画边讲、
  音画逐词对齐的手绘风讲解视频。当用户想做"白板动画 / 白板视频 / 白板叙事 / 手绘动画"、
  "把一个知识点做成讲解视频"，或提到"音画对齐、边画边讲、画板视频、白板引擎"时使用；
  即使用户没明说"白板"，只要想把一个机制、对比或流程在一张画布上逐步揭示着讲清楚，也适用。
  不适用于：真人出镜剪辑、图文卡片海报、
  纯资讯播报、纯情绪观点、平铺清单、依赖真实影像的实操内容。
compatibility: 需要 Python 3.11+ 与 uv、ffmpeg、网络访问（edge-tts 语音合成）；板图由宿主文生图模型生成，引擎本身不生图。
metadata:
  version: "1.0"
---

# kairos-whiteboard-video

总纲：**时间从真实语音边界推导，画面按讲解顺序揭示，三次确认（质量门）之间机器不自由发挥。**

本技能是一台编译器：输入知识 → 理解知识（语义 IR）→ 转换成认知路径（Transition 规划）→
转换成语言（旁白功能）→ 转换成视觉揭示过程（reveal 操作）→ 渲染成视频。
一切产物——台词、板图、绘制顺序、字幕时间——都是 Cognitive Timeline 的投影，
下游环节不得自创认知步（`references/cognitive-timeline.md`）。

方法论六原则（判据出处 [references/whiteboard-video-principles.md](references/whiteboard-video-principles.md)）：

- **P1 白板的核心不是手绘，是视觉状态随认知状态增长**：空间结构持续保留 + 渐进绘制改变状态。
- **P2 一切时间从真实语音边界推导**：字数估算只用于立项预算，成片时间只认 `words.json`。
- **P3 视觉信息不得无理由领先于讲解所需的认知信息**：`Visible ⊆ Required + Deliberate Context`，
  这就是"降低 AI 味"的全部含义，与画风无关。
- **P4 先看得懂，再讲得好**：比喻必须自带操作解释，禁止本片自造黑话，数字与做法忠于来源——
  观众复述不出"具体要敲什么"就是不合格。
- **P5 结构由认知转变的数量决定**：Beat 数 = 不可合并的 Transition 数，不由内容长度、目标秒数
  或"科普片五段"决定；**Timeline 是求解结果，不是原始数据**。
- **P6 语言与视觉是同一认知任务的两个通道**：分工互补不机械重复（因果归语言、空间归画面、
  命名与关键动作同步）；**每个视觉元素必须有认知职责**，答不出"为什么它现在存在"就删。

板图由**当前宿主的文生图模型**出 PNG（Claude Code、Codex、DSH 都行）。引擎只写 prompt、收 PNG、检查、渲染。不调本地扩散、不调第三方生图 skill。

## 铁律

- 先认知后制作：Beat 序列未定，不写台词、不出板图；画面不得无理由领先认知（P3），悬念元素须登记 `hook`。
- 三次确认（质量门）：①内容与方向确认后才出场景图；②视觉方案确认后才渲染；③最终产物确认后才交付。每次确认支持"整体确认 + 局部修改"，不增加默认流程确认次数。
- 批量生图制：全部场景图一次性批量生成、批量确认，不搞"一次一张报批"。失败重跑 = 新决策 = 重新请示。适用于任何宿主。
- 发布人工执行，agent 不代发。
- 板图不带文字。编号与标签由版式层叠加。

## 环境与命令

- 技能根 = 本目录（SKILL.md 所在处）。目录布局：`references/` 方法论规范，
  `engine/` Python 引擎（uv 工程），`themes/` 主题包（跨期复用轴），
  `projects/<ep-id>/` 单期现场（input 已确认 / build 可重生 / deliverables 终版 /
  assets 本片角色与手笔；单期产物不入 git）。
- **引擎唯一正确调用方式**（裸 `python` 会因缺 cv2 直接报错）：

  ```bash
  cd engine && uv sync                       # 首次或依赖变化时
  cd engine && uv run python scripts/workflow.py <command> --episode-dir <projects/ep-id>
  cd engine && uv run python scripts/build_video.py --episode-dir <projects/ep-id> <layout|annotate|render|assemble>
  ```

- `workflow.py` 命令：init / status / sync-boards / voice / confirm-voice / prompts / probe /
  lint / spans / import / confirm-boards / render / validate。关键参数：`init --title <标题> [--scenes N]`
  （init 不吃主题）；`prompts --theme <主题目录> [--scene id]`；`import --boards-dir <目录> [--theme]`
  （自动清右下角平台水印；chalk 主题按板底色查四角）；`voice [--voice NAME --rate X --force]`；
  `probe --theme <主题目录>`；`spans` 派生句级 narration_spans 写回 words.json。
- 渲染并行：`build_video.py … render [--jobs N]`（缺省 CPU 核数一半、上限 4；各幕独立子进程，7 幕约 1 分钟）。
- **IR 闸口**：`script.json` 必须承载顶层 `knowledge_model{}` / `learner_model{constraints, transitions[]}`
  与 `scenes[].beats[]`；`sync-boards` 前自动跑 `lint`（`engine/scripts/whiteboard_story/ir_contract.py`），
  缺 IR 即阻断——表达设计卡是给人看的，不是真相源（principles P5；错误码
  `KM.* / LM.* / EP.* / ISA.* / P5.* / P6.* / BOARD.*` 是稳定契约，见
  [references/ir-alignment.md](references/ir-alignment.md) §8）。
- 声音默认：`engine/defaults/voice.json`（YunxiaNeural）。CLI `--voice` 可覆盖。主题不承载声音。
- 现役主题：`themes/registry.json`（只登记经探针验证并冻结的主题；空表表示还没有冻结主题，先走开发者路径入库）。
- **单期时长不设上限**（优质优先）：秒数只做节奏与单步负荷的预算，**不得作为砍 Beat、强行合并
  转变或拆期的理由**；拆期的唯一合法理由是出现第二个独立 `target_claim`（principles P5）。

## 坑（Gotchas）

- 引擎命令必须 `uv run`（见上节）。直接 `python scripts/workflow.py` 报 cv2 缺失。
- 内核"只加墨不减墨"：`HIGHLIGHT`、元素级 `REMOVE`（板擦）、`REFRAME`（视口平移/缩放）
  均未实现，表达计划里出现即非法（`ISA.UNSUPPORTED_OP` 阻断）；改写规则见
  [references/expression-plan.md](references/expression-plan.md) §5
  （强调→加框或语言点名；擦除→前后态并排；换尺度→切 Scene）。
- `engine/tests/test_workflow.py` 硬断言生成的表达卡含"心智模型"字样；
  改卡片模板（`engine/assets/templates/express-card.template.md`）需保留该词或同步改测试。
- `input/layout.json` 的 panels 与该幕 `elements[]` 必须数量相等且按序号一一对应
  （`elements[i].id = "panel-(i+1)"`）；不等 → 标注器降级均分并打 warning，**warning = 不合格**。
- 词级锚找不到才退回区段均分，这是**降级**：出现即改 anchor 重跑，不得带降级进二审（P2）。
- 板图不带可读文字；编号与标签一律由 `layout.json` 的 `texts[]` 叠加。
- `voice --force` 可覆盖已生成音频，但 confirm 之后改口播必须重置指纹、重新试听。
- 板图是内容、版式层是 chrome：渲染吃 `build/boards-layout/<id>.raw.png`（内容原图），
  overlay 只叠标签文字；**分区框/编号圈只在 `<id>.preview.png`（二审预览），不进成片**；
  layout 元素不参与笔画归属——分区矩形必须覆盖该幕全部内容，否则罩不住的笔画被丢弃。
- 手素材跟主题走（`themes/<id>/hands/`），笔尖锚点写同目录 `<name>.tip.json`
  （`{"tip":[x,y]}` 原图坐标）；换手必须重新校准，否则笔尖悬浮或插进板里。
- 带 ops 的分区揭示窗 = 所绑句子边界的并集（不是锚短语的几个词）；句级口径只在
  。？！!? 断句（`split_sentences` 唯一权威）。

## 用户路径（做一期视频）

**三次确认（质量门）流程**：方向→视觉→交付。每次确认之间机器全自动执行，用户不中途干预；每次确认支持"整体确认 + 局部修改"，不增加默认流程确认次数。

**Beat 是认知单位，Scene 是板面容器：Beat count ≠ Scene count**
（一个 Scene 可装多个 Beat，一个 Beat 也可拆到多个 Scene；分组三依据见
`cognitive-timeline.md` §5）。幕数没有默认值，由分组决策得出。

### 第0步：输入知识素材

用户给出任意知识（一句话 / 文章 / 现象 / 问题 / 观点 / 机制 / 争议）。
`workflow.py init --title <标题>` 初始化项目目录（不吃主题，主题在第1次确认时推荐）。
完成 = 项目目录结构就绪 + 表达卡模板已生成。

---

### 第1次确认：内容与方向（Content & Direction）

**AI 全自动执行以下编译步骤，用户不中途干预：**

1. **知识编译（语义 IR）**：按 `references/knowledge-model.md` 填 IR：`target_claim`、`task_type`
   （A 纠错 / B 建立新概念 / C 解释机制 / D 建立概念间关系，可混合）、`learner`、
   `model.core + nodes + relations`、`learning_outcome`、`evidence`、`dependencies`、`scope`。
   **先写 `scope.exclude`**，并先过适用性（`principles` §4）。
2. **Learner Model（转换器）**：按 `references/learner-model.md` 求解：①约束求解；②转变规划
   （每个 Transition 定 `from_state → to_state`、`cognitive_operation`、`obstacle`、`success_condition`）；
   ③线性化按六条优先级排序并记下胜出依据；④过 Merge Test / Split Test 得出 Beat 数下界。
3. **表达编译（Expression Plan）**：按 `references/expression-plan.md`，对每个 Beat 依次产出
   ①`expression_goal`；②`narrative`（八种功能之一）；③`visual`（`state_before → state_after` +
   离散 `reveal_operation`，只允许 `DRAW / CONNECT / GROUP / ANNOTATE` + 追加式 `CHANGE`）；
   ④通道分配 `VERBAL / VISUAL / SHARED`；⑤元素职责表。
4. **Scene 分组与卡审**：用三个连续性判幕（visual + cognitive + spatial），任一断裂即切幕。
   按 `references/script-design.md` 填表达设计卡（八块）并过自检。
5. **生成完整脚本**：每幕 `narration`（完整旁白文本）、`board_subject`（终态画面描述，无文字）、
   `elements[].phrase`（词级锚）。**原样投影**成 `input/script.json`，先 `lint` 零阻断。
6. **推荐主题**：根据知识内容类型自动推荐默认主题（技术类→黑板风、故事类→手绘风等），
   从 `themes/registry.json` 中选；用户可改。

**产出**：表达设计卡（八块）+ 完整脚本（`input/script.json`）+ 推荐主题。

**用户确认**：
- 整体确认 → 进入第2次确认
- 局部修改 → 指出哪部分需要修改（大纲/脚本/主题/Scene分组），AI 只重生成那部分，再次确认

**状态标志**：`content_confirmed=true`、`express_card_filled=true`、`script_confirmed=true`

**完成判据**：卡八块齐全 + 终图 = 末 Beat 累计 delta + 每幕分区 2 至 4 且 ≥ 本幕 reveal 动作数 +
零领先违规 + lint 通过 + 用户确认脚本内容与主题。
`sync-boards` 前自动跑 `lint`，缺 IR 即阻断。

---

### 第2次确认：视觉方案（Visual Design）

**AI 全自动执行以下步骤，用户不中途干预：**

1. **素材准备**：手素材从主题包 `themes/<id>/hands/` 自动取（ResourceResolver 统一解析）；
   跨期复用角色定妆跟主题走；本期专用道具落当期 `assets/`。
2. **批量生成全部场景图 prompt**：`workflow.py prompts --theme <主题目录路径>` 打出所有幕的
   板图 prompt（词表）。
3. **批量生成全部场景图**：宿主模型一次性生成所有幕的 1920×1080 PNG，存 `build/boards/<id>.png`。
   **不搞"一次一张报批"**，全部批量生成后批量确认。
4. **导入与清水印**：`workflow.py import --boards-dir projects/<ep-id>/build/boards`
   （自动清右下角平台水印；chalk 主题按板底色查四角）。
5. **自动分区与标注**：写 `input/layout.json`（panels 与 `elements[]` 数量一一对应），
   `build_video.py … layout` → `annotate` 全自动执行。

**产出**：全部场景图并排预览（`build/boards/` 下所有 PNG）+ 绘制顺序预览
（`build/boards-layout/*.preview.png`，分区框/编号圈只在预览，不进成片）。

**用户确认**：
- 批量确认 → 进入第3次确认
- 单张修改 → 指出哪张场景图需要修改，AI 只重生成那张（重新 import→layout→annotate），再次确认

**状态标志**：`visual_confirmed=true`、`boards_reviewed=true`、`annotated=true`

**完成判据**：每幕一张且 check_board 全 ok + 每幕 matched、零降级 warning（warning = 不合格）+
用户确认全部场景图视觉效果。

---

### 第3次确认：最终产物（Final Delivery）

**AI 全自动执行以下步骤，用户不中途干预：**

1. **TTS 音频生成**：`workflow.py voice`（用默认音色/语速，脚本内容已在第1次确认；
   `--voice` / `--rate` 可覆盖，但不单独确认）。生成 `input/narration.mp3` + `input/words.json`
   （词级时间戳）。
2. **渲染**：`build_video.py … render --jobs N`（并行渲染所有幕，缺省 CPU 核数一半上限 4；
   7 幕约 1 分钟）。
3. **合成**：`build_video.py … assemble`（音画合成 + 词级 ASS 字幕卡拉OK逐字高亮）。
4. **验证**：`workflow.py validate`（零阻断）。

**产出**：最终视频 `deliverables/final.mp4`。

**用户确认**：
- 最终确认 → 交付完成
- 需要修改 → 指出问题，AI 定位到对应环节（内容→回第1次确认 / 视觉→回第2次确认 /
  渲染参数→直接重渲染）修改后重新生成

**状态标志**：`final_confirmed=true`

**完成判据**：validate 报告零阻断 + 视频可正常播放（1920×1080@30fps、音画同步、字幕对齐）+
用户确认最终产物。

---

### 发布

按使用者自己的发布渠道人工发布并归档；agent 不代发。

---

### 流程优化原则

- **合并同类确认**：方向性决策（大纲+脚本+主题）合并为一次确认，用户在同一上下文判断效率最高。
- **低风险环节全自动跳过**：TTS 音频是脚本的确定性产物，脚本确认则音频内容确认，不单独确认。
- **批量确认替代逐个确认**：场景图一次性全部生成并排展示，用户批量确认或单张修改。
- **可修改的确认（不是二选一）**：每次确认不是"全接受或全拒绝"，而是"整体确认 + 局部修改"。
- **智能默认值**：主题 AI 推荐默认、音频用默认音色/语速，用户不主动修改就用默认。
- **回退机制**：第3次确认发现问题时，可回退到第1次（内容问题）或第2次（视觉问题）修改后重生成。

## 开发者路径（加主题）

按 `references/theme-onboarding.md`。完成 = registry 有该 id 且风格块冻结。探针同样走宿主模型，同样批准制。

## 分支指针（何时读哪份）

- 判选题适用性、或 Beat 切分 / 揭示时序 / 旁白判据起争议 → [references/whiteboard-video-principles.md](references/whiteboard-video-principles.md)（第一性原理与 AI 味判据）
- 用户路径第 1 步：填知识语义 IR、决定砍什么 → [references/knowledge-model.md](references/knowledge-model.md)
- 第 2 步：约束求解、Transition 规划、Merge/Split Test 定 Beat 数 → [references/learner-model.md](references/learner-model.md)
- 第 3 步：怎么说 / 怎么画 / 何时揭示、元素职责、非法操作改写 → [references/expression-plan.md](references/expression-plan.md)
- 第 4 步：Scene 分组、揭示时序与时间窗约束 → [references/cognitive-timeline.md](references/cognitive-timeline.md)
- 填表达设计卡（八块卡 + 十条检查）时 → [references/script-design.md](references/script-design.md)
- 返工重跑、`layout.json` 契约（§13）、代码待办（§12）→ [references/engine-design.md](references/engine-design.md)
- 换手素材、排查渲染质量问题 → [references/kernel-design.md](references/kernel-design.md)
- 每次人工确认与成片交付之前 → [references/quality-checklist.md](references/quality-checklist.md)
- 开发者加主题 → [references/theme-onboarding.md](references/theme-onboarding.md)
- 新主题取风格块、打磨画风 → [references/style-library-handdrawn.md](references/style-library-handdrawn.md)
- 动 IR 字段、查错误码、排迁移顺序 → [references/ir-alignment.md](references/ir-alignment.md)
