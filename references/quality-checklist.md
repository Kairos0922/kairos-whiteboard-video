# 质检清单

> 只做可勾选的执行清单，规则一律引用 `whiteboard-video-principles.md` / `cognitive-timeline.md` /
> `script-design.md`，此处不重复表述。

## 知识前端 IR（拆 Beat 之前）

- [ ] 必填齐全：subject / target_claim / task_type / learner.prior_knowledge /
      model.core / model.nodes / model.relations / evidence / dependencies / scope
- [ ] `task_type` 已判型（A/B/C/D，可混合）；`misconception` 仅在有样本支撑时填，否则 none
- [ ] `model.relations` 把 nodes 连成连通图，每条关系带类型
- [ ] `target_claim` 与 `model.core` 不互相复述（只有结论没有机制 = 不合格）
- [ ] `learning_outcome` 至少一项，且是可观察行为而不是"理解了"
- [ ] 每条 evidence 有 source + confidence 分档；所有 teaching simplification 已登记
- [ ] `scope.exclude` 非空并写明理由；`source_coverage` 与取材一致（截断处标明）
- [ ] claim 单一性：全片只有一个 `target_claim` 与一条连贯链；出现第二个独立主张才拆期
- [ ] 负荷检查：单步新概念数在预算内（超了就拆转变或补前置）；**不得以"怕太长"为理由砍必懂项
      或强行合并 Beat**（时长不设上限，见 `principles` P5）
- [ ] 来源未覆盖的内容（付费墙之后、摘要之外）一律不进片

## Learner Model（排顺序与定 Beat 数之前）

- [ ] 约束五栏齐全：prerequisites / misconceptions_to_resolve / essential_relations /
      optional_details / load_budget（本阶段**不排序**）
- [ ] 每个 Transition 的 from_state → to_state 可一句话区分；`cognitive_operation` 五选一
- [ ] `obstacle` 六选一且写了处理方式；重点复查 OVERLOAD 与 TRANSFER 是否漏检
- [ ] `success_condition` 是可观察行为，并能追溯到 `learning_outcome` 的某一项
- [ ] `learning_outcome` 全覆盖，且收尾含 `APPLY`（用新情境验证，不重复原例）
- [ ] `load ≤ load_budget`，且未连续堆高负荷步（§8 规则 4）
- [ ] 多条合法线性化时写明胜出依据哪条优先级；结论不早于支撑它的模型（规则 6，倒置须写理由）
- [ ] Merge Test 四条件与 Split Test 已跑，**Beat 数 = 剩余 Transition 数**（不由时长反推）

## 表达编译（写 Scene 卡与 board_subject 之前）

- [ ] 每个 Beat 有 `expression_goal`，其中 `attention_target` 非空（决定重音与 HIGHLIGHT 落点）
- [ ] `narrative.function` 取自八种且主 1 辅 1；旁白不是把知识念出来，是在执行功能
- [ ] `visual` 写成 `state_before → state_after` + 离散 `reveal[]`，不是"画某个东西"的静态描述
- [ ] 每个 reveal 动作绑定一个 `narration_span`；时刻由 `words.json` 回填（**无手填秒数**）
- [ ] `reveal[]` 只含当前可编译操作（`DRAW/CONNECT/GROUP/ANNOTATE` + 追加式 `CHANGE`）；
      出现 `HIGHLIGHT` / `REMOVE` / `REFRAME` 即回炉，按 `expression-plan.md` §5 改写
      （强调→加框或语言点名；擦除→前后态并排；换尺度→切 Scene）
- [ ] 通道分配三问已判：有空间结构才画；因果理由归语言；命名与关键动作同步（= 词级锚）
- [ ] 双通道不机械重复（画面已说清的关系不再逐条念）；允许短标注贴关键动作
- [ ] 元素职责四问全答得出（代表什么 / 承担哪次认知职责 / 哪个 Beat 引入 / 之后谁在用）；
      `used_by: []` 且无认知职责 = 装饰 → 删
- [ ] 方向自查两句通过：这句话因认知变化才被说？这一笔因语义边界才被画？

## 脚本与认知时间轴（写 script.json 前）

- [ ] 每个 Beat 卡的 `state_before/after`、`success_condition`、`narration_goal`、`visual_goal` 已填
- [ ] 相邻 Beat 的 `visual_after → visual_before` 首尾相接（接不上 = 画着画着换题）
- [ ] 每个 `visual_operation` 落在十种枚举内，且能映射到五种画面动作之一
- [ ] 终图元素清单 = 各 Beat `visual_delta` 累加（含收束）
- [ ] 相邻 Beat 状态链无空跳；`prerequisite_beats` 拓扑序成立（不用未建立的概念）
- [ ] Reveal Constraint：领先违规 = 0（除卡上登记的 `hook`）；落后不超过一句
- [ ] 每幕分区 2 至 4，且 ≥ 本幕需独立揭示的视觉操作数；跨幕 Beat 每片各占分区
- [ ] `workflow.py lint` 零阻断（`sync-boards` 会自己拦，别绕）；报错按码修：`KM.*` 改知识 IR、
      `LM.*` 改转变规划、`EP.*` 改表达计划、`ISA.*` 换合法操作、`BOARD.*` 修分区与 elements 对齐
- [ ] 旁白无本片自造黑话；每个比喻都能复述出"具体要敲什么"（principles P4）
- [ ] 数字、模型名、做法与来源材料一致，来源没有的内容不进片

## 板图（第二次确认）

- [ ] 幕数 = script.json scenes 条数；每张 16:9、长边 ≥1920px、四角纸白（import 自动查）
- [ ] 分区 2 至 4 个、互不搭界、区间留白 ≥70px、底部 1/5 基本空
- [ ] `layout.json` panels 数量 = 该幕 `elements` 数量且序号一一对应；annotate 零降级 warning（字段契约 `engine-design.md` §13）
- [ ] 全图无文字（编号与标签由版式层叠加）
- [ ] 角色与当期定妆一致
- [ ] 编号顺序 = 绘制顺序 = 旁白叙事顺序

## 渲染前

- [ ] boards_reviewed=true 且 annotated=true
- [ ] 手笔：PNG alpha，笔尖锚点已校准，路径是当期 assets 或 --hand

## 成片终审

- [ ] 笔迹流畅、手部贴线、无跳帧；首帧干净
- [ ] 底部字幕可读，不压内容
- [ ] 总时长与旁白一致（±200ms），结尾停留 ≥0.5s
- [ ] H.264 + AAC、1920×1080、30fps

## 发布前

- [ ] 人工发布；agent 不代发
- [ ] 发布后归档到内容资产库
