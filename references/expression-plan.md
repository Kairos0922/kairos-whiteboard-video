# Expression Plan（认知 Beat → 语言 + 视觉）

> 本层回答编译器最值钱的问题：**这一个认知变化，具体怎么被说、被看见、被揭示。**
> 上游 `learner-model.md` §9 的 Beat 字段表，下游 `cognitive-timeline.md` §5 的 Scene 分组与渲染管线。
> 判据出处 `whiteboard-video-principles.md`（P1 视觉随认知增长、P3 Reveal、P4 看得懂、P6 双通道互补）。

## 1. 核心原则：两条通道，一个认知任务

语言和视觉**不是两个独立生成器**，是同一个认知任务的两种表达通道。由此得三条纪律：

1. 一个 Beat 先出 `expression_goal`（要观众注意什么），**不直接生成旁白**；
2. 通道之间要**互补**，不要机械重复：画面已经表达清楚的关系，旁白不必逐项再念一遍；
3. 也不能"能不写字就不写"走极端——冗余原则是有条件的，**短而贴住关键动作的屏幕标注**
   反而降低负荷（本项目里就是版式层叠加的 ≤7 字标签，见 §7 ANNOTATE）。

研究口径要诚实：多媒体学习研究支持分段、信号提示、空间邻接、时间邻接、连贯性这些原则能
**降低无关处理、改善部分学习结果**，不是一切场景都成立（Cambridge Handbook of Multimedia
Learning 第 11、12 章；Heliyon 2023 白板动画实验）。所以本层规则写成**可检查的编译约束**，
不写成"这样一定更好"的断言。

## 2. 第一步：expression_goal

```yaml
expression_goal:
  beat_id:
  learner_change:    # = Beat.state_before → state_after（从 learner-model 搬来，不重写）
  essential_message: # 这一 Beat 必须传达的那一句（不是台词，是命题内容）
  evidence_needed:   # 成立所需的证据（引用 knowledge_model.evidence 的 id）
  attention_target:  # 想让观众注意画面/论述上的哪一点
```

`attention_target` 是本层的枢纽字段：它同时决定旁白的重音落在哪、以及画面强调落在哪个元素
（`HIGHLIGHT` 原语未实现，落点是 `GROUP` 加框或语言点名，见 §5）。**没有它，视觉与语言就会各说各的。**

## 3. 第二步：Narration（八种语言功能）

旁白不是"把知识念出来"，它每句都在执行一个功能：

| function | 干什么 | 典型句式 |
|---|---|---|
| `DECLARE` | 告诉观众一个事实 | "它每写一个词，都在猜下一个" |
| `QUESTION` | 抛出需要解决的问题 | "那问题出在哪？" |
| `CONTRAST` | 指出两个状态的区别 | "看起来随机，其实不是随机" |
| `EXPLAIN` | 解释关系或因果 | "因为它挑的是最多人满意的答案" |
| `TRACE` | 沿着过程讲下去 | "先跑代码，拿到字符串，再照着定配色" |
| `INTERPRET` | 说明当前画面意味着什么 | "这两条路，走的就是上面那条" |
| `GENERALIZE` | 从例子升到规则 | "所以结论是：随机得从外面给" |
| `CHECK` | 让观众自检当前理解 | "换成你的项目，第一步该干什么？" |

```yaml
narrative:
  function: EXPLAIN
  spans:                       # 分句，供 §5 通道映射与 §6 边界对齐使用
    - "AI 每写一个词，都在猜下一个词放什么最稳"
    - "它天生就爱挑最多人满意的答案"
  text:                        # 最终播讲文本（spans 拼接，写播讲腔，P4）
```

一个 Beat 通常 1 个主功能 + 至多 1 个辅助功能。`CHECK` 只在 `learning_outcome` 有
`application / prediction` 时才用，位置在收束 Beat，别当口头禅。

## 4. 第三步：Visual（画面不是配图）

```yaml
visual:
  function:            # 与 narrative.function 同源但不要求同名（互补即体现在差异上）
  objective:           # 这块画面承担什么认知职责（= Beat.visual_goal）
  objects: []          # 参与的对象 id（必须是终图里的元素，不许临时新增）
  relations: []        # 对象间关系（带类型）
  state_before:        # = Beat.visual_before（此刻板上已有什么）
  state_after:         # = Beat.visual_after
  operation:           # §5 离散 Reveal 操作序列，不写"画一个缓存"这种静态描述
```

写法上的差别就是本层的意义：不是"画缓存"，而是"**关系发生了变化**"。

```yaml
# 反例（静态配图）
visual: {operation: "画缓存、数据库、箭头"}

# 正例（揭示过程）
visual:
  state_before: request → database
  state_after:  request → cache → response
  operation:    [DRAW(cache), CONNECT(request→cache), CONNECT(cache→response), REMOVE(request→database)]
```

## 5. 四套词汇的关系（必须先对齐再写代码）

系统里存在四套动作词汇，各自只在一层有效，**不许跨层混用**：

| 层 | 词汇 | 数量 | 回答什么 |
|---|---|---|---|
| 认知目标 | `cognitive_operation`（learner-model §3） | 5 | 观众脑子里要发生什么 |
| 视觉意图 | `visual_operation`（cognitive-timeline §7） | 10 | 画面上打算表达什么 |
| 揭示操作 | `reveal_operation`（本文下表） | 8 | 板上**这一步做哪个动作** |
| 内核动作 | 出现 / 连接 / 移动 / 转换 / 消失（kernel-design） | 5 | 渲染器实际执行的图元操作 |

编译方向：`cognitive_operation → visual_operation → reveal_operation[] → 内核动作`。

### reveal_operation 八种（离散，第一版只这八种）

| 操作 | 含义 | 映射到内核动作 | 现状 |
|---|---|---|---|
| `DRAW` | 出现新对象 | 出现（骨架描线 + 蛇形填色） | ✅ 已支持 |
| `CONNECT` | 建立两对象关系 | 连接（画线/箭头） | ✅ 已支持 |
| `CHANGE` | 修改已有对象状态 | 转换（新笔画覆盖旧状态） | ⚠️ 仅"追加笔"式改变，无法擦掉已画像素 |
| `HIGHLIGHT` | 突出已存在的信息 | —— | ❌ 无原生动作；现只能靠重描加深或加框近似（近似即 `GROUP`/`CHANGE`） |
| `ANNOTATE` | 加短标签或指示 | 出现（版式层文字，非板图） | ✅ 由 `layout.json` 的 `texts` 承担 |
| `GROUP` | 把已有对象组织成整体 | 出现 + 连接（框） | ✅ 已支持 |
| `REMOVE` | 移除视觉信息 | 消失 | ❌ 逐元素擦除未实现；板擦/翻页在 `kernel-design` §5 v2 路线图 |
| `REFRAME` | 改变视觉关注区域 | —— | ❌ **内核无视口能力**（无平移 / 缩放 / 裁切） |

**当前可编译集合 = `DRAW` / `CONNECT` / `GROUP` / `ANNOTATE`（+ 追加式的 `CHANGE`）。**
`HIGHLIGHT` / `REMOVE` / `REFRAME` 在内核扩展之前**禁止出现在 Expression Plan 里**：

- 要强调 → 改用 `GROUP`（加框）或在 `narrative` 里点名（词级锚天然就是 spotlight）；
- 要擦除 → 改切 Scene（清屏重装），或把"减法"这件事交给**新画面对比**（先画满再画干净的骨架，
  靠 `DRAW` 追加实现，不删像素）；
- 要换尺度 → 切 Scene。

这三条不是妥协话术，是编译器的**目标机指令集约束**：写不出可执行操作的计划就是非法计划。
内核若按 `kernel-design` §5 扩出描字、清场与（未来）视口，再逐项解禁。

**一个真实的非法计划**（本期挂起那期，Beat「做减法」）：原写法是
`visual.operation = [REMOVE(光晕), REMOVE(彩字), REMOVE(多余的框)]`，
画面上是一只橡皮把装饰擦掉。按上表，`REMOVE` 当前**编译不下去**——内核只会往画布上加墨，
不会减。三种合法改写：

1. **前后态并排**（`DRAW` + `CONTRAST`）：左半屏画"堆满装饰的版本"，右半屏画"删干净后的骨架"，
   减法变成看得见的对比——最省改动，且 `relations` 反而更清楚；
2. **两分区顺序画**（`DRAW` × 2）：先揭示臃肿版，再揭示干净版，干净版覆盖式登场（不擦，只加）；
3. **交给旁白 + 版式标注**（`ANNOTATE`）：语言承担"删了什么"，画面只呈现删完的结果。

这个例子说明目标机约束不是限制表达，而是**逼出更强的表达**：并排对比比"擦掉"更能承载
`DISTINGUISH` 这个认知操作。计划编译期应当把非法操作连同这三条改写一起报出来
（`engine-design.md` §12 第 7 条的校验项）。

## 6. 通道分配：VERBAL / VISUAL / SHARED

每个 Beat 把它的信息分到三类，这是防"念图"和"看图猜"的正面手段：

```yaml
channel_allocation:
  verbal:   []   # 只靠语言传递：因果、理由、顺序连接词、抽象规则
  visual:   []   # 只靠画面传递：空间布局、并列对比、量的多少、位置关系
  shared:   []   # 必须同步：新概念命名时刻、关键动作发生时、结论成立时刻
```

分配三问（按顺序判）：

1. **这个信息有空间结构吗？** 有 → `visual`（旁白重复它只是浪费观众的听觉带宽）；
2. **它是理由或因果链吗？** 是 → `verbal`（画箭头只能表示"有关"，表示不了"为什么"）；
3. **观众会听到这个词但不知道指哪个吗？** 是 → `shared`，且必须靠 `reveal` 的时间对齐解决
   （词级锚就是它的手段，见 §7）。

重复度检查（可量）：`shared` 之外的信息若在旁白与画面里**同时首次出现且表达同一命题**，
记一次冗余（redundancy）告警；反过来，`visual` 项若观众要靠猜（既没说也没标），
记一次断连告警。二者的合格线都由人工在第二次确认时勾（`quality-checklist.md` 表达层节）。

## 7. 边界链：Narration Boundary → Semantic Boundary → Reveal Boundary

现有规则"时间从真实语音边界推导"（P2）保留并加细一层。**画面动作不按秒均匀发生，
而在语义边界附近发生**：

```
Narration Boundary  旁白分句（words.json 的词级边界，实测）
      ↓ 对齐
Semantic Boundary   认知信息被引入 / 关系被解释 / 结论成立（= expression_goal 的转折点）
      ↓ 触发
Reveal Boundary     某个 reveal_operation 的开画时刻
```

编译规则三条：

1. 每个 `reveal` 项必须绑定一个 `narration_span`（它的 `at` 由该 span 的
   `start_ms` 推导，**不许手填秒数**）；
2. `at` 与该 span 起点的偏差容忍窗 = ±1 个分区窗口，超出即 P3 违规（领先或落后）；
3. 相邻 reveal 之间不插"为了节奏"的空动作——没有认知职责的动作就是噪声（§9 元素职责）。

时间邻接（temporal contiguity）是这条的工程动机：说到的和画出来的越接近，观众自己配对的负担越小。

```yaml
reveal:
  - op: DRAW
    target: cache
    bound_span: 1            # 第 1 句旁白
    at_ms: null              # 由 words.json 编译期回填
  - op: CONNECT
    target: request→cache
    bound_span: 1
  - op: GROUP
    target: cache
    bound_span: 2            # 加框近似强调（HIGHLIGHT 未实现，§5；at_ms 由 words.json 回填）
```

## 8. Expression Plan（本层的产物对象）

```yaml
expression_plan:
  beat_id:
  expression_goal: {learner_change, essential_message, evidence_needed, attention_target}
  narrative:       {function, spans[], text}
  visual:          {function, objective, objects[], relations[], state_before, state_after}
  reveal:          [{op, target, bound_span, at_ms}]
  channel_allocation: {verbal[], visual[], shared[]}
  elements:                         # §9，每个元素必须有认知职责
    - {id, semantic_role, cognitive_function, introduced_at, used_by[]}
```

它回答的正是 §1 那句话。一个 Beat 一份 Plan；跨幕 Beat 每片一份子 Plan（共用同一
`expression_goal`，`state_after` 只在最后一片成立）。

## 9. 每个视觉元素必须有认知职责

```yaml
element:
  id:
  semantic_role:      # 它代表什么（这个概念在终图里的角色）
  cognitive_function: # 它承担哪次认知职责（对应哪个 visual_operation）
  introduced_at:      # 哪个 Beat 引入（不得早于认知准备好它的时刻，P3）
  used_by: []         # 之后被哪些 Beat 复用（空 = 只为好看）
```

判据一刀切：**答不出"为什么它现在存在"就删**（这就是连贯性原则在工程里的样子——与教学
目标无关的材料只会增加无关处理）。`used_by: []` 且 `cognitive_function` 为空 = 装饰 =
进 `scope.exclude`，最多留作主题包允许的少量纸面/板面纹理（主题层职责，不占分区）。

## 10. Scene 由三个连续性决定（不是内容长度）

```
Scene = 能在同一个空间状态里连续表达的 Beat 组合
判定 = visual continuity + cognitive continuity + spatial continuity
```

- **visual continuity**：后一个 Beat 的 `state_before` = 前一个的 `state_after`（不重置画面）；
- **cognitive continuity**：观众不需要放下旧模型另起炉灶（同一解释模型内推进）；
- **spatial continuity**：新增元素画得下、分区预算不超（每幕 2 至 4，`quality-checklist.md`）、
  不遮挡已讲内容。

三条任一断裂 → 切 Scene（清屏重装）。这就是原先"Beat Grouping 三依据"的形式化版本，
`cognitive-timeline.md` §5 以本节为准，不再另立判据。

## 11. 编译方向纪律（防反向）

```
expression_goal → narrative / reveal → 具体句子与具体笔画
```

禁止反向：先写好顺口台词再给它找画面、或先想好一个漂亮构图再倒推它承载什么认知变化。
自检问两句：**这句话是因为要发生某个认知变化才被说的吗？这一笔是因为某个语义边界才被画的吗？**
任一答不上来即反向编译（这也是降 AI 味在语言侧的真正落点，比"别用书面语"深一层）。

## 12. 一个完整小样（缓存，Beat=B3）

```yaml
expression_plan:
  beat_id: b3
  expression_goal:
    learner_change: "知道请求会经过缓存 → 知道命中时数据库被绕过"
    essential_message: "缓存命中后，请求不需要再次访问数据库"
    evidence_needed: [e2]          # 请求路径发生变化
    attention_target: "request→cache 这条新路径，以及被断开的那条旧路径"
  narrative:
    function: EXPLAIN
    spans:
      - "如果缓存里已经有数据"
      - "请求就不用再跑一趟数据库"
    text: "如果缓存里已经有数据，请求就不用再跑一趟数据库。"
  visual:
    function: CONTRAST
    objective: "让'少跑一趟'变成看得见的绕行"
    objects: [request, cache, database, response]
    relations: [request→cache, cache→response, request→database(断开)]
    state_before: "request → database"
    state_after:  "request → cache → response；request → database 被划断"
  reveal:
    - {op: DRAW,    target: cache,            bound_span: 1}
    - {op: CONNECT, target: request→cache,    bound_span: 1}
    - {op: CHANGE,  target: request→database, bound_span: 2}   # 追加式划断（画斜线，不擦像素）
    - {op: CONNECT, target: cache→response,   bound_span: 2}
    - {op: GROUP,   target: {cache, response}, bound_span: 2}  # 加框代替 HIGHLIGHT（未实现）
  channel_allocation:
    verbal: ["为什么少跑一趟（因果）"]
    visual: ["三条路径的空间布局、被断开的那条在哪"]
    shared: ["缓存这个词出现的那一刻 = DRAW(cache) 的开画时刻"]
  elements:
    - {id: cache,    semantic_role: 缓存层,   cognitive_function: 承接请求的中转,
       introduced_at: b2, used_by: [b3, b4, b5]}
    - {id: database, semantic_role: 数据源,   cognitive_function: 被绕过的成本中心,
       introduced_at: b2, used_by: [b3, b5]}
```

`at_ms` 全部留空由 `words.json` 回填；`shared` 那一项正是词级锚存在的理由——
`anchors: ["缓存"]` 绑定 `DRAW(cache)` 的时刻。

## 13. 与其他文档的分工

| 事项 | 归属 |
|---|---|
| 几个 Beat、什么认知操作、什么障碍 | `learner-model.md` |
| Beat 落到哪几幕、分区预算、揭示时序的形式约束 | `cognitive-timeline.md` §5–§6 + 本文 §10 |
| 每句旁白的功能、每个画面对象、每次 reveal 操作与绑定 | **本文** |
| 具体台词的口语化与 P4 检查 | `script-design.md` §1 第 10 条 + §5 词典 |
| 板图终态描述（给宿主模型）与内核动作 | `engine-design.md` / `kernel-design.md` |

本文与 `cognitive-timeline.md` §6.1「逆向切图」的关系：那节是本文的前身与临时近似，
定稿后 Scene 侧只保留"终图 → 分区"的落地映射（`engine-design.md` §13），切图算法以本文 §4/§7 为准。
