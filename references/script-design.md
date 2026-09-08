# 脚本设计法（script-design）

> 定位：本文只回答**这一段具体怎么说**——旁白、板图描述、分区、检查。
> 认知与表达侧已分四层，谁也不许串位：`knowledge-model.md`（教什么）→
> `learner-model.md`（观众的认知要怎样改变、几个 Beat）→ `expression-plan.md`
> （怎么说、怎么画、何时揭示）→ `cognitive-timeline.md`（Scene 分组与揭示时序的落地约束）。
> 本文不产生认知与表达决策，只做填写格式与检查。
> 判据出处 `whiteboard-video-principles.md`；填卡模板 `engine/assets/templates/express-card.template.md`，
> 新项目由 `workflow.py init` 自动生成到 `input/express-card.md`。

## 0. 脚本阶段的产出物：一张卡（八块）+ 一份投影

脚本阶段结束的标准是填完表达设计卡并过人工审。**八块**口径全项目统一（与模板逐块对应）：

| 块 | 内容 | 来源与验收标准 |
|---|---|---|
| ① Knowledge Model | 语义 IR 全字段：`target_claim / task_type / learner / model.core+nodes+relations / learning_outcome / evidence / dependencies / scope / source_coverage` | 过 `knowledge-model.md` §7 出口判据；`scope.exclude` 非空；`misconception` 无样本则 `none` |
| ② Learner Model | `learner_constraints{}` + Transition 表（`from/to_state`、`cognitive_operation`、`obstacle`、`success_condition`）+ 顺序胜出依据 | 每个 Transition 状态差可复述；`learning_outcome` 被覆盖（含 `APPLY`）；Beat 数 = Merge Test 后剩余数 |
| ③ 终图 | 末幕停留画面的全部元素与关系 | = 末 Beat 的累计 delta；能对着它讲出 `learning_outcome.explanation` |
| ④ 功能色表 | 3～4 个功能色 + 绑定概念 | 同色同义贯穿全片，登记后才可加色 |
| ⑤ Beat 列表 | 每步一张 Beat 卡（§2，字段权威表 `learner-model.md` §9） | 状态、操作、障碍、揭示意图齐全；无空差 |
| ⑥ 表达计划 | 每 Beat 一份 `expression_plan`：`expression_goal / narrative(function, spans) / visual(state_before→after, reveal[]) / channel_allocation / elements[]` | `attention_target` 非空；无 `used_by: []` 的装饰元素；每个 reveal 绑一个 `narration_span`；无 `REFRAME`（§5 禁用项） |
| ⑦ Scene 分组 | 每幕一张 Scene 卡（§3，含 `board_subject` 与 panels 预算） | 三个连续性判定；分区 2 至 4 且 ≥ 本幕 reveal 动作数 |
| ⑧ 自检 | 十条检查 + 各层出口判据勾选 | 全勾才交人工审 |

卡过审后写 `input/script.json`——它是 Timeline 的**投影**，不是第二份创作：
每幕 `narration` / `board_subject` / `elements[].phrase` 全部由 Beat 卡搬运与合并而来，
**不允许在写 JSON 时新增认知内容**；发现缺料就回 `knowledge-model.md` 补 IR 重审。

## 1. 十条检查（填卡后逐条过，一条不合格回炉）

1. **画关系，不画装饰**：每幕写出元素间关系（谁指向谁、谁包含谁、谁变成谁）；写不出关系的素材删掉。
2. **状态差必须可描述**：每个 Beat 有 `state_before` / `state_after` 且能一句话区分；
   一个 Beat 不同时产生两个"原来如此"。该不该合并 / 拆分按 `learner-model.md` §7 的
   Merge Test 与 Split Test 判，不靠手感。
3. **抽象落到具体，比喻自带操作解释**：判据见 `whiteboard-video-principles.md` P4；
   每个抽象名词在 Beat 卡上指定具体载体物。
4. **Reveal Constraint**：`Visible ⊆ Required(n) + Deliberate Context`。逐 Beat 勾领先/落后违规，
   合格线 = 0（除登记 `hook`）；量化口径 `cognitive-timeline.md` §9–§10。
5. **文字极少**：每幕标注 ≤7 个字，只做标签不做解说；解说由旁白负责。板图内不得有可读文字。
6. **风格服务理解**：线条可有手绘感但不许凌乱；纹理可以有但不许抢主体。基调由主题包保证，
   脚本层只检查"主对象是否一眼可辨"。
7. **颜色承担信息功能**：同一种颜色始终代表同一种概念；固定 3～4 色并在功能色表登记。
8. **视觉操作必须可归类**：每个 Beat 的 `visual_operation` 取自十种枚举
   （`cognitive-timeline.md` §7）；出现映射不到认知操作的动作，就是炫技，删。
9. **结尾形成心智模型**：收尾幕把全部元素同屏归位一次成总图，且必须等于卡上的终图；
   拿 `rest_line` 自查"观众能否对着这张图讲出来"。
10. **旁白写播讲腔，不写书面语**：短句为主、节奏有起伏、用口语连接词（"其实 / 换句话说 / 你想想"）；
    禁书面句式与长定语。数字读法由声源保证（edge-tts 免操心；换其他声源须先做 TN 归一化再合成与对齐）。

## 2. Beat 卡格式（字段权威表：`learner-model.md` §9 + `cognitive-timeline.md` §6）

一个 Beat = 一次不可再合并的认知转变。卡上按下列顺序填（前三行决定这个 Beat 该不该存在）：

```
### b-NN｜cognitive_operation｜obstacle｜落 scene-NN[, scene-NN]
- state_before：进这一步之前观众持有的（可能是错的）模型
- state_after：离开时持有的模型（与 before 必须可区分，否则这个 Beat 不成立）
- cognitive_operation：IDENTIFY | DISTINGUISH | RELATE | EXPLAIN | APPLY（主 1，必要时标 1 辅）
- obstacle：MISSING | CONFLICT | GAP | ABSTRACTION | OVERLOAD | TRANSFER + 本步的处理方式
- success_condition：可观察的检验（观众能说出 / 判断 / 预测什么），指向 learning_outcome 的某一项
- knowledge_used / knowledge_added：引用与新增的概念 id（对齐 model.nodes）
- evidence_refs：引用 knowledge_model.evidence 的条目 id（溯源用，不在 Beat 里新造事实）
- narration_goal：为了让这次变化发生必须说什么（**不是台词**）
- visual_goal：不画出来观众会卡在哪
- visual_before / visual_after：此刻画面上有什么 / 结束时该有什么（相邻 Beat 必须首尾相接）
- visual_operation：十种枚举（cognitive-timeline §7），主 1 辅 1
- reveal_order：visual_before → visual_after 之间的分区先后 = 分区编号顺序
- anchors：词级锚，逐字出现在本幕旁白里（一个锚 = 一个分区）
- prerequisite_beats：拓扑前置（含跨幕引用）
- timing_role / hook / est_ms：锚点|承接|停留、画面提前的豁免理由、时间预算（仅预算）
```

两条方向纪律：**`narration_goal` 先于 `narration`，`visual_goal` 先于 `board_subject`**。
先写漂亮台词再给它找意义、或先想好画面再倒推它承载什么认知变化，都是反向编译
（`learner-model.md` §10、§13）。

## 3. Scene 卡格式（板面容器，与 Beat 数无固定比例）

Scene 是制作容器不是认知单位：**Beat count ≠ Scene count**。判幕的唯一依据是三个连续性
（visual / cognitive / spatial，定义在 `expression-plan.md` §10）：任一断裂就切幕；
一个 Beat 也可因空间重置拆到多幕，多个 Beat 只要首尾相接同屏就能合幕。分组三依据细则见
`cognitive-timeline.md` §5。

```
### scene-NN｜承载 Beat：b-NN[, b-NN…]（或 b-NN 的分片）｜旁白要点：
- 旁白原文：（该 Scene 内 Beat narration 顺次拼接）
- board_subject：本幕终态画面描述（给宿主文生图模型，写到元素级，禁止任何文字）
- visual_operations：本幕要执行的视觉操作（决定分区数）
- 标注文字：≤7 字；没有则写"无"
- panels：按 reveal_order 排列的分区与各自 anchor
```

**分区预算（写卡时先算，不画完再塞）**：

1. 数本幕的视觉操作：每个需要独立揭示时刻的操作至少 1 个分区；
2. 分区总数必须落在 **2 至 4**（`quality-checklist.md`「板图」段）；超了 → 改分组
   （砍操作、合并同质元素、或把 Beat 拆到下一幕）；不足 2 → 本幕并入相邻 Scene；
3. `panels` 数量 = 该幕 `elements` 数量且序号一一对应（`elements[i].id = "panel-(i+1)"`），
   不等即标注器降级为均分并打 warning——warning = 不合格；
4. 定序：分区编号顺序 = 本幕各 Beat `reveal_order` 拼接后的全局顺序 = 旁白讲述顺序。

跨幕 Beat 的每个分片在自己的幕里各占自己的分区，但 `state_after` 只在最后一片登记一次。

## 4. 三种内容骨架（Beat 动作模板，不是幕数模板）

骨架只给 Beat 的**动作序列**倾向；步数由状态差与跨过测试决定，幕数由分组决策决定，都没有默认值。
**选哪套骨架看 `task_type`（A/B/C/D），不看输入形态**：A 偏破除、C 偏给因、B/D 偏建联。
输入形态与常见 task_type 的对照见 `knowledge-model.md` §6。

**知识科普**（与技术负责人认知类五步法同构）：立题（现象钩子）→ 破除（把错误认知画出来）→
给因（误解根源，桥接）→ 给法（正确心智模型，信息密度最高）→ 收束（马上能做的动作）。
**故事**：立题（人物与想要的东西）→ 建联（障碍画成墙/关卡）→ 转换（转变动画集中点，
前后同构图对比）→ 收束（新状态）。
**观点短打**：立题（断言一句）→ 给因（最强证据一例）→ 破除（反面代价）→ 收束（行动号召）。

三套词汇的对应（旧"节拍词"只是骨架标签，进卡的是 `cognitive_operation`）：

| 骨架节拍 | cognitive_operation | 常见 obstacle |
|---|---|---|
| 立题 | IDENTIFY | ABSTRACTION |
| 破除 | DISTINGUISH | CONFLICT |
| 给因 | EXPLAIN | MISSING |
| 给法 | APPLY | GAP |
| 建联 | RELATE | GAP |
| 收束 | APPLY | TRANSFER |

## 5. 抽象到具体的翻译词典

（表达层判据——比喻要带操作解释、禁自造黑话、忠于来源——在 principles P4；
本表只给"翻成什么画面"的对照。）

| 抽象概念 | 画面载体 | 典型 visual_operation |
|---|---|---|
| 因果 | 箭头、多米诺 | CAUSE |
| 包含 / 分类 | 分组框 | DECOMPOSE |
| 流程 / 步骤 | 有序编号框 | CONNECT |
| 数量 / 对比 | 大小差、计数刻度、左右并排 | CONTRAST |
| 关系 / 交换 | 连线、握手、交换手势 | CONNECT |
| 演进 / 变化 | 同屏前后态并排或原位形变 | TRANSFORM |
| 机制 / 内部过程 | 剖视、流水线、传送带 | DECOMPOSE |
| 筛选 / 把关 | 入口队列 + 闸口 + 通过标记 | DECOMPOSE + CONNECT |
| 删减 / 克制 | 擦除动作 + 剩余骨架 | COUNTEREXAMPLE / HIGHLIGHT |
| 抽象定义落地 | 概念下方挂一个具体载体物 | EXAMPLE |

## 6. 与管线的衔接

1. `workflow.py init --episode-dir projects/<ep-id> --title <标题> --scenes N` 生成
   `input/express-card.md`（`--scenes` 只是初值，分组改了再 `sync-boards`）；**init 不吃主题**；
2. 填块① Knowledge Model → 过 `knowledge-model.md` §7 出口判据（`misconception` 只在有样本支撑时填）；
3. 填块② Learner Model → 约束求解、Transition 规划、Merge/Split Test 得 **Beat 数下界**
   （`learner-model.md` §6–§8）；此时才知道要几幕；
4. 填块③④⑤⑥⑦（终图、功能色表、Beat 卡、Scene 分组、自检）→ 人工审通过后手工置
   `express_card_filled=true`；
5. 投影出 `input/script.json` → `sync-boards`；
6. **主题在此选定**：从 `themes/registry.json` 取现役主题，后续命令统一传**目录路径**
   （`--theme themes/chalkboard-chibi`）；
7. 配音 → 试听 → 第一次人工确认（此后改口播必须 `--force` 并走重跑矩阵）；
8. 板图按 `board_subject`（终态）出图，揭示过程由引擎按 panels 反推；
9. 分区（`input/layout.json`，字段契约 `engine-design.md` §13）→ 预览绘制顺序
   → 第二次人工确认 → 渲染 → 合成 → validate。

（2026-09-03 起，原"script.json 尚无 `beats[]` 与 `knowledge_model` 字段"作废——现已实现）
投影必须包含完整 IR：顶层 `knowledge_model{}` 与 `learner_model{constraints, transitions[]}`
（块①②搬运），每幕 `beats[]`（块⑤搬运，字段权威表 `learner-model.md` §9）。
`workflow.py lint` 在 `sync-boards` 前校验（`ir_contract.py`），缺 IR 即阻断；错误码
`KM.* / LM.* / EP.* / ISA.* / P5.* / P6.* / BOARD.*` 是稳定契约（`ir-alignment.md` §8）。
表达设计卡是给人审的，`script.json` 是机器唯一真相源。代码待办见 `engine-design.md` §12。
