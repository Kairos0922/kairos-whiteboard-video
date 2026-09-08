# 认知时间轴（cognitive-timeline）

> 本文回答一个问题：**这些认知变化按什么顺序、以什么揭示节奏发生。**
> 上游是 `learner-model.md`（Transition 规划结果，其上游为 `knowledge-model.md`），
> 下游是 `script-design.md`（这一段具体怎么说）。判据出处 `whiteboard-video-principles.md`。
> 本文只消费已定序的 Transition 链，负责时序、Scene 分组与揭示设计；**不在此层增删或重排 Beat**。

## 0. 契约与位置

```
输入：Learner Model 的规划结果（`learner-model.md`）
      · learner_constraints{}：前置 / 待破误解 / 必讲关系 / 可省细节 / 负荷预算
      · transitions[]：已定序的 Transition 链（operation + obstacle + success_condition）
      · beat_count_range：过完 Merge Test 的不可合并转变数（本层不得再增删）
      其上游：Knowledge Model → Knowledge Graph（target_claim / model.nodes+relations / learner /
      learning_outcome / evidence / scope）
输出：Cognitive Timeline 的时序面——Scene 分组、揭示顺序、分区预算、时间窗
下游：Timeline 决定 Beat 序列落几幕、板图内容、揭示顺序、音画对齐
```

**Timeline 不是"带时间的脚本"，是"学习者状态转移序列"。** 脚本、板图、字幕时间都只是它的投影。
Narrative 不在第一层：先定"观众要经历哪些认知变化"，再定"每个变化怎么发生"，
最后才轮到"用什么语言解释、用什么视觉操作揭示"。

## 1. 完整编译链（本项目的中端定位）

```
Knowledge
  ↓ knowledge-model.md
Knowledge Model            教什么 / 观众是谁 / 建什么模型 / 学到什么程度 / 不解释什么
  ↓ 同一层的产出视图
Knowledge Graph            model.nodes + model.relations（偏序结构，不是一条线）
  ↓ learner-model.md（两阶段：约束求解 → 转变规划）
Learner Model              Transition 序列 = S0→S1→…→Sn，每步一种认知操作、一类认知障碍
  ↓ 本文（规划结果的时序化与揭示设计；**Timeline 是求解结果，不是手写的分幕表**）
Cognitive Timeline         顺序、分组、揭示时序、时间
  ↓ learner-model.md §9（字段权威表）
Beat Specification         state / obstacle / knowledge / narration_goal / visual_* / prerequisite
  ↓ expression-plan.md（本层的表达分支：怎么说 + 怎么画 + 何时揭示）
Expression Plan            expression_goal / narrative(function, spans) / reveal[](op, target, span)
                           / channel_allocation(VERBAL|VISUAL|SHARED) / elements[](认知职责)
  ↓ script-design.md
Narrative（旁白文本） + Visual Reveal Specification（分区与动作序列）
  ↓ 本文 §5 分组落地（判据定义在 expression-plan §10：三个连续性）
Scene / Board Specification
  ↓ engine-design.md / kernel-design.md
Reveal Timeline → Audio Sync → Render
```

## 2. Cognitive Graph ≠ Cognitive Timeline

知识天然不是线性的：

```
A
├── B
│   └── C
└── D
    └── E
```

但视频必须在时间上线性化（`A → B → C → D → E`）。所以**Timeline 是对知识结构做了一次
面向学习者的时间化编译**——这才是本项目"编译器"的实质内容，也是 Skill 沉淀的核心。

排序不在此定义：**线性化的六条优先级、依赖拓扑与负荷规则见 `learner-model.md` §8，
候选 Transition 的合并与拆分判据见 §7。** 本文只消费其结果（一条已定序的 Transition 链），
并负责把它落成时序、分组与揭示设计。**同一条规则不在两处写。**

## 3. 核心对象：Learner State Transition Timeline

```
S0：A 看起来就是这样（观众进入前的解释模型）
 ↓ b1
S1：发现 A 有异常（原模型解释不了某个现象）
 ↓ b2
S2：引入 B（新变量登场）
 ↓ b3
S3：理解 A → B 的关系
 ↓ b4
S4：能用 B 反过来解释原来的 A，并预判一个新情形
```

每个 `Si` = 观众此刻**拥有的解释模型**。Timeline 的合法性判据只有一条：

> 相邻状态之间必须存在**可明确描述**的差异，且该差异由本 Beat 的语言 + 视觉操作造成。

差异写不出来（"讲得更清楚了"不算），这个 Beat 就不该存在——该情形下的合并 / 拆分判据
在 `learner-model.md` §7（Merge Test 四条件、Split Test 触发器），不在本文重述。

## 4. Beat 的时序侧约定

Beat 的**正式定义、字段权威表、合并与拆分测试**都在
`learner-model.md`（定义 §1、字段 §9、测试 §7）。本文只补三条时序侧约定：

- **时长是 Beat 的结果，不是它的约束**：一句旁白可承载半个 Beat，一个 Beat 可长到三句；
- Beat 可以跨幕（§5 分组），但状态差只在最后一片达成；
- Beat 的揭示时刻由它的词级锚决定（§8），不由排期表决定。

Beat 的旧"动作类型"（立题 / 破除 / 给因 / 给法 / 建联 / 收束）不再是 Beat 字段，
降级为骨架节拍词，与五种 `cognitive_operation` 的对应见 `learner-model.md` §3 与 `script-design.md` §4。

## 5. Beat Grouping：Scene 只是制作容器

**上一轮"1 Beat 不跨 Scene、1 Scene 含 1～3 Beat"作废。** 正确关系是：

```
Cognitive Beat  →  Beat Grouping  →  Scene  →  Board
   认知单位          分组决策         板面容器   一张终态图
```

- **Beat count ≠ Scene count**。两个方向都允许：
  - 一个 Scene 装多个 Beat：条件是它们**共享同一板面结构、构成连续的视觉揭示过程**；
  - 一个 Beat 拆到多个 Scene：条件是**视觉空间必须重置**（换主体、换尺度、换时间层），
    或一块板面已无法继续承载当前模型。此时该 Beat 的状态差在**最后一个 Scene** 达成，
    前序 Scene 只做铺垫，`state_after` 仍只写一次（写在 Beat 上，不写在 Scene 上）。
- 分组决策的三个连续性（**定义在 `expression-plan.md` §10，本文不重述**）：
  visual continuity（`state_after` 与下一 Beat 的 `state_before` 相接）、
  cognitive continuity（观众不必放下旧模型）、spatial continuity（画得下、分区够、不遮挡）。
  任一断裂 → 切 Scene。
- **分区仍是硬约束**：每幕 `panels` 2 至 4 个（`quality-checklist.md`「板图」段）。
  分组时先算分区预算：本幕承载的视觉操作数 ≤ 分区数；超了就是分组错了，
  不是"画完再塞"。跨幕 Beat 的每个分片在自己的幕里各占自己的分区。
- 换主题、换画风不改 Timeline；换 Timeline 必然重算 Scene 分组与板图。

## 6. Beat 的时序侧字段（权威字段表在 `learner-model.md` §9）

Beat 的完整字段（state / obstacle / knowledge / narration_goal / visual_before / visual_after /
visual_operation / prerequisite_beats / success_condition）以 `learner-model.md` §9 为准，
本文不再抄一份（两处字段表必然漂移）。本文只管这四个时序侧字段：

```yaml
# 追加在 learner-model §9 之上
  reveal_order:             # visual_before → visual_after 之间的分区先后 = 分区编号顺序
  timing_role:              # 锚点(自带 phrase 决定揭示时刻) | 承接(共享前 Beat 窗口)
                            # | 停留(不引入新信息，让模型落地) —— 见 §8
  hook: false               # true = 故意让画面领先认知，须写理由（§9 唯一豁免）
  scenes: [scene-NN]        # 本 Beat 落在哪些幕（1..n，支持跨幕，见 §5）
  est_ms:                   # 预算用；真实时间只认 words.json（principles P2）
```

`claim / evidence` 的严谨性要求（写不出证据就降级为观点、来源未覆盖不进片）
在 `knowledge-model.md` §4–§5，Beat 只是引用其条目 id，不另立一套。

### 6.1 终图 → 分区预算（切图算法已迁至 `expression-plan.md`）

本节原先叫"逆向切图"，是表达层的**前身与临时近似**。定稿后的分工：

- **怎么把认知变化切成语言与揭示动作** → `expression-plan.md` §2–§7（expression_goal、
  八种语言功能、`reveal_operation`、通道分配、元素职责）；
- **本文只管落地**：末 Beat 的 `visual_after` = 终图；每幕分区数 = 该幕需独立揭示时刻的
  `reveal` 动作数，且必须落在 2 至 4；分区编号顺序 = `reveal_order` 拼接后的全局顺序 =
  旁白讲述顺序。

Step 1 仍是"先写终图"：最后一个 Beat 结束时画面该是什么样，列出全部元素与关系，
再按 Beat 反向分配 add / modify / remove（由 `expression-plan.md` §5 的操作序列推导），
查依赖（箭头不得早于两端节点）与 Reveal（§9），最后交给分组（§5）。
顺序不能反：先有终图再有 delta，先有 delta 再有 Scene。反过来做（先切幕再想画什么）就退化成台词分镜。

## 7. visual_operation：认知操作 → 视觉操作（标准化枚举）

第一版只允许这十种。它们**不是视觉风格，是认知操作对应的视觉操作**：

| 操作 | 认知意图 | 白板上的做法 | 映射到引擎的五种画面动作 |
|---|---|---|---|
| `INTRODUCE` | 让新对象进入模型 | 主体登场、命名 | 出现 |
| `CONTRAST` | 建立两对象差异 | 左右并排、同构图对照 | 出现 + 移动 |
| `CONNECT` | 建立关系 | 连线、箭头 | 连接 |
| `DECOMPOSE` | 整体拆成部分 | 剖视、爆炸图、括号分组 | 出现 + 连接 |
| `TRANSFORM` | 展示状态变化 | 同一位置形变、前后态替换 | 转换 |
| `CAUSE` | 展示因果链 | 多米诺、链式箭头 | 连接 + 移动 |
| `EXAMPLE` | 抽象落到具体 | 概念下方挂一个具体载体物 | 出现 |
| `COUNTEREXAMPLE` | 打破错误直觉 | 反例上打叉、塌陷、擦除 | 出现 + 消失 |
| `HIGHLIGHT` | 强调已出现的关键部分 | 圈、加粗、变色（功能色） | 转换（不改结构） |
| `SUMMARIZE` | 重组已建立的模型 | 全要素归位成总图 | 移动 + 连接 |

规则：一个 Beat 主用一种操作（可加一种辅助）；五种画面动作（出现/连接/移动/转换/消失）
由 `visual_operation` 推导，**不允许出现映射不到任何认知操作的动作**——那就是炫技。
`HIGHLIGHT` 只能作用于已揭示的元素，对未揭示元素做高亮等同提前剧透（§9）。

**本节是"视觉意图"层，不是执行层。** 系统共有四层词汇，编译方向与映射表在
`expression-plan.md` §5：

```
cognitive_operation(5，learner-model §3)      观众脑子里要发生什么
  → visual_operation(10，本节)                画面上打算表达什么
    → reveal_operation(8，expression-plan §5) 板上这一步做哪个离散动作
      → 内核五种画面动作（kernel-design）      渲染器实际执行的图元操作
```

跨层混用（例如把 `TRANSFORM` 直接写进渲染任务，或把 `DRAW` 当认知目标）视为编译错误。

## 8. timing_role 与时间化

- **锚点**：Beat 自带词级锚（`anchors` → `elements[].phrase`），揭示时刻由该锚的
  `start_ms` 决定。承担新信息的主 Beat 必须是锚点。
- **承接**：共享前一锚的窗口（连接句、过渡），不单独占锚点；不得引入新概念。
- **停留**：讲完后不塞新东西，让模型落地（`COMPLETE_TAIL_MS` 与末幕定格）。收束 Beat 后必留。

其余口径不变：中文旁白约 4.2 字/秒只用于立项预算，且它是**节奏预算不是时长闸门**——
本项目单期不设时长上限，绝不为压秒数删 Beat 或合并认知转变（`principles` P5）；
真实时间一律以 `words.json` 为准；
找不到锚点退回区段均分是**降级**，出现即须改 anchor，不得带 warning 进二审（principles P2）。

## 9. Reveal Constraint（形式化，取代"不要 AI 味"）

```
Beat n 期间：Visible ⊆ Required(n) + Deliberate Context
```

即：**当前已揭示的画面信息，只能是"此刻该被理解的必要信息"加上"明确登记的背景信息"，
不能提前把观众尚未被引导理解的关键关系画全。**

讲到 B 而 C 尚未引入时，C 可以合法地处于四种状态：板外 / 不可见区域 / 尚未绘制 /
非关键装饰位置；但不能无理由完整展示 `A → B → C`——那等于视觉替观众提前完成了推理。

本项目的一个结构性事实要注意：**整幕板图是终态**（`principles` §3：模型管终态），
所以 C 一定"存在于图上"。约束因此只作用在**揭示时序**上，即 C 所在分区不得早于
它的锚点被画出来。这条让 Reveal Constraint 在引擎里可检可判，而不是靠感觉。
唯一豁免是 `hook: true`（悬念元素），且必须写明理由。

## 10. Beat 的六项 QA（未来的自动检查基础）

| 维度 | 自动问题 | 现状 / 落点 |
|---|---|---|
| Cognitive | 是否有明确的 before / after？ | 可静态查字段非空且不等；现人工 |
| Narrative | 旁白是否真的完成了这次状态转移？ | 半自动：claim 关键短语是否出现在 narration 中 |
| Visual | 视觉是否承担了认知任务（映射到 §7 某个操作）？ | 可静态查 `visual_operation` ∈ 枚举 |
| Reveal | 关键关系是否在正确时间出现（§9）？ | 待建：分区开画时刻 vs 锚点 `start_ms`，进 validate 阻断 |
| Dependency | 是否用了观众尚未建立的前置概念？ | 待建：`dependencies` 拓扑序校验 |
| Timing | 认知变化是否有足够时间发生？ | 待建：`est_ms` 与 `words.json` 实测差、停留窗是否留足 |

六项全过才算 Timeline 合格；其中 Reveal 与 Dependency 是最容易静默失败的。

## 11. 一句话公式

```
BEAT = State Change + Language + Visual Operation + Temporal Placement
```

编译方向恒为：`Knowledge → State Change → Language → Visual Operation → Temporal Placement`。
任何一步反向（先写好台词再想配什么画）都不算编译，算凑稿。

## 12. 与现有实现物的映射（增量）

| 概念 | 落地物 | 状态 |
|---|---|---|
| Knowledge Model | `knowledge-model.md` 全量 schema；落在卡块① | ✅ 已独立成层（语义 IR）；`script.json.knowledge_model{}` 已承载并强制校验（`ir_contract.py`） |
| Learner Model | `learner-model.md`；落在卡块②的 Transition 表 | ✅ 已成层；`script.json.learner_model{constraints, transitions[]}` 已承载并强制校验 |
| Learner State Timeline | 卡「Beat 列表」 | ✅ `scenes[].beats[]` 已承载并强制校验（缺 IR 即阻断，`workflow.py lint`） |
| Beat 字段表（权威） | `learner-model.md` §9 + 本文 §6 时序侧字段 | ⚠️ 文档层 |
| `visual_operation` | 卡的「变化类型」字段（旧五动作） | ⚠️ 需升级为枚举 + 动作推导 |
| Beat Grouping / `scenes[]` | 靠 Scene 卡人工归属 | ⚠️ 文档层 |
| Reveal Constraint 检查 | 人工肉眼 + `quality-checklist` 勾选 | ❌ 静态检查待建（`engine-design.md` §12） |
| 词级锚 / 揭示窗口 | `elements[].phrase` + `words.json` | ✅ 已闭环 |
| 终态板图 + 分区揭示 | `board_subject` + `layout.json` + kernel | ✅ 已闭环 |
