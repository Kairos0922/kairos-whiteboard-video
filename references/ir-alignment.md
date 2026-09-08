# IR 对齐审计（现有工程 → Knowledge→Whiteboard Video 编译器）

> 方法：对照的是**代码实际读的字段**与七级 IR，不是文档之间的措辞。每条处置都给了证据位置。
> 处置四值：**保留**（原地不动）/ **移动**（换层，语义不变）/ **废弃**（删或降级为派生量）/
> **新增**（编译器需要但工程还没有）。
> 本轮只出审计结论，未改代码。改动排期见 §8。

## 1. 七级 IR 与实现物现状

| IR 层 | 核心问题 | 现在的实现物 | 状态 |
|---|---|---|---|
| Knowledge | 我们知道什么 | `express-card.md` 块①（文档层） | ⚠️ 有文档无 schema，代码不认识 |
| Learner | 观众要改变什么 | 块② Transition 表（文档层） | ⚠️ 同上 |
| Cognitive | 按什么顺序改变 | 块⑤ Beat 列表（文档层） | ⚠️ 同上 |
| Expression | 怎么说、怎么画 | 块⑥ 表达计划（文档层） | ❌ 代码完全没有对应结构 |
| Scene | 哪些变化共享一个空间 | `input/script.json` 的 `scenes[]` | ✅ 有，但**只能表达"一幕一段话"，不能表达 Beat↔Scene 多对多** |
| Board | 最终板面长什么样 | `build/boards/<id>.png` + `input/layout.json` panels | ✅ 已闭环 |
| Render | 每一笔什么时候出现 | `annotations/<id>.json` + `kernel.build_tasks` | ✅ 已闭环，但**粒度只有 panel** |

结论：断口在 **Expression → Scene → Board** 这三级的接缝上。前四段 IR 目前只活在 Markdown 里，
编译器一落到 `script.json` 就把它们压扁成了"幕 + 词级锚"。

## 2. `script-design.md` 逐项处置

| 现有字段 / 规则 | 处置 | 理由与落点 |
|---|---|---|
| `scenes[].narration` | **移动 → 派生** | 它现在是一级输入；应是 `beats[].narrative.spans` 拼接的产物（`engine-design.md` §12 第 7 条）。旧期次无 beats 时保留手填兼容路径 |
| `scenes[].board_subject` | **移动 → 派生** | 应是该幕 `visual.state_after` + 元素清单的文本化（`expression-plan.md` §4）。仍作为给宿主模型的 prompt 输入，但不再手写 |
| `scenes[].elements[].phrase` | **保留，降级语义** | 它是 SHARED 通道的词级锚，是唯一能把 reveal 绑到语音的机制（`expression-plan.md` §6/§7）。但 `elements[]` 应从"分区清单"改挂到 `reveal[].target` |
| `elements[].id = panel-N` | **保留，加约束** | 标注器按序号 zip（`make_annotations_v2.py:245–265`），必须继续与 panels 同序同数；新增校验：不等即阻断（现在只 warning） |
| 卡块「变化类型：出现/连接/移动/转换/消失」 | **废弃为手填项** | 内核五种动作是**结果**，应由 `reveal_operation` 推导（`expression-plan.md` §5 映射表）。手填会出现"写了转换但没画变化的东西" |
| 卡块「标注文字 ≤7 字」 | **保留**，改名 `label` | 它是 `layout.json.texts[]` 的输入，属于 Board IR 的合法字段，不是表达层字段 |
| 卡块「panels + reveal_order」 | **保留 → 拆分** | 分区坐标是 Board/Scene 层；`reveal_order` 是 Expression 层。同一格里混着两层，是"画完再塞分区"的根因 |
| 十条检查 #1–#10 | **保留**，改为从 IR 生成勾选 | 十条本身仍然成立；但 #4/#8/#9 应变成可静态检查（见 §7） |
| §4 三种骨架 | **保留**为 `task_type` 倾向 | 已在 `knowledge-model.md` §6 与 `script-design.md` §4 对齐，无代码影响 |
| §5 翻译词典 | **保留** | 它是 `EXAMPLE/CONTRAST/DECOMPOSE` 的选材手册，唯一"具体化"资产 |
| `est_ms` / 4.2 字每秒 | **保留为预算** | 已明确它不是时长闸门（`cognitive-timeline.md` §7） |

**本层新增字段**：`beats[]`（含 `state_before/after`、`cognitive_operation`、`obstacle`、
`narration{function,spans}`、`visual{state_before,state_after}`、`reveal[]`、`channel_allocation`、
`elements[]{id,semantic_role,cognitive_function,introduced_at,used_by}`）、`scenes[].beat_refs[]`
（多对多映射的唯一真相）。

## 3. `engine-design.md` 逐项处置

| 现有条目 | 处置 | 理由 |
|---|---|---|
| §0 现状基线表（教程 8 步覆盖度 55%） | **废弃** | 已加时效声明但内容仍在误导；voice/words/validate 都已实现。建议整表删除，改为一行指向 §12/§13 |
| §1 五层架构（providers/themes/workflow/kernel/compose） | **保留 + 上移** | 五层是**后端**；新增"第 0 层 IR"已在 §1 文字里，但架构图未画。补：`IR 层 → workflow → 五层` |
| §2 `words.json` 时间轴心 | **保留**，扩字段 | 词级边界是 reveal 绑定的地基；新增派生物 `narration_spans[]`（句级边界直接来自现成的 `captions.srt`，**不用新造机制**） |
| §3 八阶段管线 | **保留**，插两阶段 | 在"建项目"与"脚本"之间插 1) IR 抽取 2) Transition 规划 3) 表达编译；原"脚本"阶段改为"IR → script.json 投影" |
| `state.json` phases 七项 | **保留 + 新增 3 项** | 现有 `express_card_filled` 一个布尔盖住了三层。新增 `knowledge_model_ok / learner_plan_ok / expression_plans_ok`，否则人工审无法定位审的是哪一层 |
| `project.json`（§1 契约里） | **废弃** | 代码从未实现，实际用 `state.json.theme` + CLI `--theme`。保留会诱导别人去找不存在的文件 |
| §8 重跑矩阵 | **保留 + 补两行** | 缺"IR 层改了"的行。改 `target_claim`/`task_type` → 全链重跑；改 Transition 序列 → 表达计划起重跑；改 reveal 操作 → 标注与渲染重跑 |
| §13 `layout.json` 契约 | **保留**，`panels.color` 降级 | 预览色无语义；标签 `texts[]` 才是 Board IR 的字段 |
| §12 七条待办 | **保留为排期** | 本文 §8 就是它的执行顺序，两者合并避免双写；第 7 条（`script.json` 降级为编译产物）对应本文 §2 的三条移动结论 |

## 4. `kernel-design.md` 逐项处置（关键冲突都在这层）

| 现有实现 | 处置 | 理由 |
|---|---|---|
| annotation `elements[].kind ∈ {layout, panel}` | **扩展**（保留值） | 表达层要求 `DRAW/CONNECT/GROUP/ANNOTATE/CHANGE` 的离散序列，当前**没有任何字段承载操作类型**——渲染器只认"这块区域什么时候开始上墨" |
| `region` = 矩形 + 质心归属（`kernel.py:127`） | **保留**，但它是冲突源 | 见 §5：一个矩形=一次揭示，与"一个对象多个操作"不兼容 |
| `reveal.{startMs,durationMs,protectedRegions}` | **保留**，`protectedRegions` 启用 | 时间窗正确；`protectedRegions` v1 被忽略（本文件 §5），表达层的 `HIGHLIGHT/GROUP` 恰恰依赖它 |
| `sequence` 排序 | **保留** | 与 `reveal_order` 天然对齐 |
| 五种画面动作（出现/连接/移动/转换/消失） | **降级为派生量** | 它是 `reveal_operation` 映射的**结果**，不是输入。文档要把这层关系写反过来的地方全部改掉 |
| `handPath._sweep`（区内蛇形扫） | **保留** | 手部是服务层（P1 推论），不必表达语义 |
| 描线 + 蛇形填色 = **只能加墨** | **保留为硬事实** | `REMOVE`/`HIGHLIGHT`/`REFRAME` 因此非法（本文件 §5 第 6–8 项、`expression-plan.md` §5） |
| 抬笔预算、弧长比例时长、收尾整图兜底 | **保留** | 与 IR 无耦合，是纯渲染质量件 |
| `HAND_TIP_RATIO` 校准 | **保留** | 换手必校，独立于编译器 |

## 5. 审计的头号发现：揭示粒度对不上

```
表达层的最小单位：一个操作作用在一个对象上      op(target)      —— 例：DRAW(cache) → CONNECT(req→cache) → GROUP(cache,response)
渲染层的最小单位：一个矩形区域一次性上墨        panel(region)   —— 例：panel-1 = (x,y,w,h) 整块揭示
```

一个 Beat 有 3–5 个操作，它们的 target **互相重叠**（cache 被画、被连、被框）。
但内核按质心把每条笔画归属到**唯一最小矩形**，矩形必须互不搭界（`quality-checklist.md` 板图段）。
于是同一对象的多次操作无法拆成多个 panel——它们会把彼此吞掉。

三条出路：

- **A. panel = 揭示单元（1 个单元可含 1–3 个 op），区内再分时间子窗**
  改动小：annotation 加 `ops[]`，内核在**同一 region 内按笔画子集排多个子窗**，
  依赖已列在路线图的对象级编排（`kernel-design.md` §5 第 3 项）。
  代价：区内子窗靠笔画分组正确性，分组错就时序错。
- **B. panel = op，允许重叠 + 用 `protectedRegions` 隔离**
  语义最干净（一个 op 一个 panel），但必须先实现 `protectedRegions` 真实生效，
  且分区数从"2 至 4"抬到"2 至 6+"，`quality-checklist.md` 那条要重定容。
- **C. 不做区内细分，一 Beat 一次揭示**
  零改动，但 `reveal_operation` 序列在成片里退化为"整块出现"——
  **等于把表达层的编译成果扔掉**，P1 的"视觉随认知增长"打折。

**已定论（2026-09-03，判据：用正确的方法做正确的事）→ 选 A。**
panel 重定义为「揭示单元」，前置依赖对象级编排与 `protectedRegions` 真实生效，
分区口径改为"每幕 2 至 4 个揭示单元、每单元 ≤3 个 op"。落在 §8 迁移表第 4 步，**代码未动**。
不选 B：把复杂度推给掩码代数，且立刻破坏"分区互不搭界"这条已验证有效的板面纪律；
不选 C：零改动但让 `reveal_operation` 退化成"整块出现"，等于把表达层编译成果扔掉——
那是"用错误的方法做快事"，与本项目的判据相反。

## 6. `quality-checklist.md` 逐项处置

| 现有条目 | 处置 |
|---|---|
| 前端 IR / Learner Model / 表达编译三节 | **保留**（新写的，未进代码；进代码后转自动项） |
| 「幕数 = script.json scenes 条数」 | **保留**，加一句"scenes 条数 = Scene 分组结果，不等于 Beat 数" |
| 「分区 2 至 4 个」 | **待定容**（随 §5 选项变；选 A 则改成"揭示单元 2 至 4"） |
| 「编号顺序 = 绘制顺序 = 旁白叙事顺序」 | **升级为可检**：三序一致 + reveal 绑定 span 的偏差窗（P3） |
| 「全图无文字」「角色与定妆一致」「16:9 长边 ≥1920」 | **保留**，纯 Board/主题层 |
| 成片终审四条 | **保留**，新增一条：`REMOVE` 类改写后的前后态并排不得看起来像画错（视觉可读性人工判） |
| 发布前两条 | **保留**，加一条：开源前品牌中性化（`SKILL.md` 环境事实） |

## 7. 可以静态化的检查（把人工勾选变成 validate 阻断）

按投入产出排序：

1. **Beat 数 = Merge Test 后 Transition 数**（拦"先定幕数"，P5）——纯结构检查，最先做；
2. **枚举合法性**：`cognitive_operation` / `obstacle` / `visual_operation` / `reveal_operation`
   越界即阻断，`REFRAME/HIGHLIGHT/REMOVE` 在未实现前按非法处理；
3. **IR 完整性**：`knowledge_model` 必填项、`scope.exclude` 非空、每 Beat `state_before ≠ state_after`、
   `used_by: []` 装饰元素告警（P6）；
4. **panels ↔ elements 数量与序**（现在只 warning，改阻断）；
5. **reveal ↔ span 邻接窗**（P3 领先/落后，依赖 §2 的 `narration_spans` 派生）；
6. **双通道重合度**（SHARED 之外的同命题重复）——语义判，先留人工。

## 8. 迁移顺序与破坏半径

| 步 | 动作 | 破坏半径 | 状态 |
|---|---|---|---|
| 1 | `script.json` 扩 `beats[] / knowledge_model / learner_model / expression_plan` 字段（**只加不改**） | 零 | ✅ 已实现：`whiteboard_story/ir_contract.py` |
| 2 | §7 的 1–3 项静态校验 + `sync-boards` 前置闸口（缺 IR 即阻断，不降级：文档层不再是真相源） | 只拦新片 | ✅ 已实现：`workflow.py lint` |
| 3 | 派生 `narration_spans`（自 `captions.srt` / `words.json`） | 小 | ✅ 已实现（2026-09-04）：`whiteboard_story/spans.py` + `workflow.py spans`，幂等写回 words.json；句级口径＝`make_annotations_v2.split_sentences`（只在 。？！!? 断句） |
| 4 | §5 定论 A：annotation 加 `ops[]`、`protectedRegions` 真实生效 | 中：标注器 + 内核 | ✅ 已实现（2026-09-04）：标注器按句数切跨幕 Beat 的 reveal 序列并按序分到揭示单元（每单元 ≤3 op）；内核 `_clip_strokes`/填色掩码剔除保护区像素，ops>1 的单元按连通域聚对象组切相继子窗（`SUB_WINDOW_GAP_MS`）；首期样本 ai-world-class-designer 全链验证通过 |
| 5 | 标注器按揭示单元排程；`board_subject`、`narration` 改为生成物 | 大：第一次确认之后的全链 | ⬜ 待做（揭示窗口已先按句级边界落位：带 ops 的分区窗口＝所绑句子边界之并集） |
| 6 | 内核补 `HIGHLIGHT`（加框/加深）→ 视需要再补元素级 `REMOVE` | 中 | ⬜ 待做 |

第 4 步之前，已过闸口的期次能照原样继续，这是逐层落地的安全边界。但**旧结构的
`script.json` 现在过不了 `sync-boards`**（缺 `knowledge_model` / `learner_model` 即阻断）——
挂起那期必须按新链重编译，这正是第 1、2 步要的效力（`principles` P5）。

错误码（`KM.*` / `LM.*` / `EP.*` / `ISA.*` / `P5.*` / `P6.*` / `BOARD.*`）是稳定契约，
文档与质检按码引用，不复述整句报错。

## 9. 一句话结论

审计时的判断已经兑现：中间那几段 IR 原先在 JSON 里没有位置，`script.json` 一上来就是
"幕 + 旁白 + 分区"，等于让渲染器直接读散文。**第 1–4 步已落地**（`ir_contract.py` +
`workflow.py lint` + `sync-boards` 前置闸口 + `spans.py` 句级边界 + 方案 A 的 ops/保护区），
整条链现在被机器钉住：没有 IR 就进不了现场阶段。首期样本 ai-world-class-designer 已按
新链重编译并通过全链（lint 零阻断 → spans → 板图 → 分区揭示渲染 → validate 零阻断）。

剩下的顺序是：5) 标注器按揭示单元排程、`narration`/`board_subject` 转生成物 →
6) 内核补 `HIGHLIGHT`。
