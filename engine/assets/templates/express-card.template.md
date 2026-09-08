# 表达设计卡 · {{TITLE}}

> 填卡即立项。全卡过人工审后才进入板图生成。八块口径与定义：
> 判据 `references/whiteboard-video-principles.md`；语义 IR `references/knowledge-model.md`；
> 认知转换 `references/learner-model.md`；表达编译 `references/expression-plan.md`；
> 时序与揭示 `references/cognitive-timeline.md`；填写格式与十条检查 `references/script-design.md`。
- 创建：{{DATE}}
- 输入形态：一句话 / 文章 / 现象 / 问题 / 观点 / 机制 / 争议（决定抓取方式，不决定任务类型）
- 适用性：本知识有可增长的结构（纯资讯 / 纯情绪 / 平铺清单 / 依赖真实影像 → 改做别的形态）

## ① Knowledge Model（语义 IR；字段定义 knowledge-model.md §3）

- subject：（讨论对象，一句话）
- 一句话心智模型：（target_claim 与 model.core 的人读合并，审卡第一眼看这行）
- target_claim：【必填】观众最终该接受的命题，可被反驳
- task_type：A 纠正误解 | B 建立新概念 | C 解释机制 | D 建立概念间关系（可混合）
- learner.prior_knowledge：【必填】观众进片时已有什么（逐条，决定每步能不能说）
- learner.misconception：有样本支撑才填，否则写 none（**不许现编稻草人**）
- model.core：【必填】带方向的解释链条（并列名词不算模型）
- model.nodes：/ model.relations：（每条关系带类型：causes / depends-on / part-of / contrasts-with / enables / balances）
- learning_outcome：recognition / explanation / prediction / application（**至少一项**，动词开头、可观察）
- evidence：逐条 `claim + source + confidence`，confidence ∈ source-backed fact / model inference / teaching simplification
- dependencies：前置概念；jargon 翻成大白话的写法
- scope.include：/ **scope.exclude：先写这一栏——写不出省略清单说明没读懂材料**
- source_coverage：取材范围与截断处（未覆盖内容一律不进片）

## ② Learner Model（约束求解 + 转变规划；定义 knowledge-model §9 / learner-model §6–§8）

约束求解（不排序）：

- prerequisites：（必须提前建立的概念；标明"假定已有"还是"本片自建"）
- misconceptions_to_resolve：（依 task_type 可为空）
- essential_relations：（取自 model.relations 的哪几条）
- optional_details：（与本次 claim 无关、或可留到下期的细节——**不是"为缩短而砍"的清单**）
- load_budget：（单个 Transition 的新变量上限，默认 1；管单步负荷，**总时长不设上限**）

转变规划（排序 + 合并）：

```
### t-NN｜IDENTIFY|DISTINGUISH|RELATE|EXPLAIN|APPLY｜obstacle=…
- from_state → to_state：
- required_knowledge：/ evidence_refs：/ success_condition：（可观察，指向 learning_outcome）
- load：
```

状态链（规划结果的直观视图）：

```
S0：（观众进入时持有的解释模型）
 ↓ t1
S1：…
 ↓ tN
SN：（离开时持有的模型，应能一句话讲出 learning_outcome.explanation）
```

- 顺序胜出依据：（多条合法线性化时，写明按 `learner-model.md` §8 第几条定下这条）
- **Beat 数下界 = 过完 Merge Test / Split Test 后剩余的 Transition 数**（不是先定幕数再填）

## ③ 终图（先写它，再倒推每一步长哪一块）

- 元素：
- 关系：（谁指向谁、谁包含谁、谁变成谁）

## ④ 功能色表（3～4 色，同色同义）

| 颜色 | 绑定概念 | 用在哪类元素 |
|---|---|---|
| （例）砖红 | 问题 / 平庸 | 被否定的方案、冗余装饰 |

## ⑤ Beat 列表（认知单位；字段权威表 learner-model.md §9）

```
### b-NN｜cognitive_operation｜obstacle｜落 scene-NN[, scene-NN]
- state_before → state_after：
- success_condition：
- knowledge_used / knowledge_added / evidence_refs：
- narration_goal：（不是台词）
- visual_goal：
- visual_before → visual_after：
- visual_operation：INTRODUCE|CONTRAST|CONNECT|DECOMPOSE|TRANSFORM|CAUSE|EXAMPLE|COUNTEREXAMPLE|HIGHLIGHT|SUMMARIZE（主1辅1）
- reveal_order：
- anchors：（逐字出现在旁白里，一个锚 = 一个分区）
- prerequisite_beats：
- timing_role：锚点 | 承接 | 停留
- hook：无 /（画面提前的理由）
- est_ms：（字数 ÷ 4.2 字每秒，仅预算）
```

## ⑥ 表达计划（每个 Beat 一份；定义 expression-plan.md §2–§9）

```
### b-NN｜expression_plan
- expression_goal：learner_change / essential_message / evidence_needed / **attention_target**
- narrative：function（DECLARE|QUESTION|CONTRAST|EXPLAIN|TRACE|INTERPRET|GENERALIZE|CHECK，主1辅1）
             spans[]（分句，供 reveal 绑定与时间对齐）
- visual：function / objective / objects[] / relations[] / state_before → state_after
- reveal[]：{op: DRAW|CONNECT|CHANGE|HIGHLIGHT|ANNOTATE|GROUP|REMOVE（REFRAME 禁用）,
            target, bound_span}   # 时刻由 words.json 回填，不手填秒数
- channel_allocation：verbal[]（因果/理由/规则） / visual[]（空间结构、量的对比） /
                      shared[]（命名与关键动作必须同步的时刻 = 词级锚）
- elements[]：{id, semantic_role, cognitive_function, introduced_at, used_by[]}
              # used_by 为空且无认知职责 = 装饰 → 删
```

方向自查两句：这句话是**因为要发生某个认知变化**才被说的吗？这一笔是**因为某个语义边界**
才被画的吗？任一答不上 = 反向编译。

## ⑦ Scene 分组（板面容器；Beat count ≠ Scene count）

```
### scene-NN｜承载 Beat：b-NN[, b-NN…]（或某 Beat 的分片）
- 旁白原文：
- board_subject：（终态画面，写到元素级，禁止任何文字）
- visual_operations：（决定本幕分区数）
- 标注文字（≤7 字）：
- panels：（按 reveal_order 排列的分区与各自 anchor）
```

分区预算：本幕分区数 = 需独立揭示时刻的视觉操作数，且必须落在 **2 至 4**；超了改分组，不画完再塞。

## 自检（全部勾选才交人工审）

- [ ] Knowledge Model 过 `knowledge-model.md` §7 出口判据：`scope.exclude` 非空、
      `target_claim` 与 `model.core` 不互相复述、`misconception` 无样本支撑则填 none
- [ ] 十条检查逐条过（`script-design.md` §1）
- [ ] 每个 Transition 的 from/to_state 可一句话区分；`obstacle` 无漏检（重点查 OVERLOAD 与 TRANSFER）
- [ ] `learning_outcome` 各项被 Transition 覆盖，且收尾有 `APPLY`（缺它观众不会迁移）
- [ ] 多条合法顺序时，已写明按 `learner-model.md` §8 哪一条胜出
- [ ] Beat 数 = Merge Test 后剩余 Transition 数（有推导链，不是先定幕数）
- [ ] 每个 Beat 的 `state_before/after` 非空且可区分；`success_condition` 可观察
- [ ] 相邻 Beat 的 `visual_after → visual_before` 首尾相接（接不上就是画着画着换题）
- [ ] 每个 `visual_operation` 都在十种枚举内，映射到五种画面动作之一
- [ ] 终图 = 末 Beat 累计 delta，能对着它讲出 `learning_outcome.explanation`
- [ ] 逐 Beat 查过 Reveal Constraint：领先违规 = 0（除已登记 hook）、落后不超一句
- [ ] 每幕分区 2 至 4 且 ≥ 本幕视觉操作数；panels 数 = elements 数
- [ ] 旁白无本片自造黑话；每个比喻都能复述出"具体要敲什么"（principles P4）
