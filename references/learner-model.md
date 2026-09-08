# Learner Model（认知转换器）

> 三层分离，谁也不许串位：
> `Knowledge Model` 回答**要教什么**；`Learner Model` 回答**观众的认知要怎样改变**；
> `Cognitive Timeline` 回答**这些改变按什么顺序发生**。
> 本层是知识到认知路径之间的**转换器**，也是真正决定视频结构的那一层。
> 判据出处 `whiteboard-video-principles.md`（P1 视觉随认知增长、P3 Reveal、P5 结构由转变决定）。

## 1. 基本单位是 Transition，不是 Step

```
Learner State A  →  某种认知操作  →  Learner State B
```

直接生成 `Step 1 / Step 2 / Step 3` 的系统仍然贴着脚本——Step 是制作顺序，
Transition 是认知变化。**本层只产出 Transition 与它们之间的约束，不产出幕，也不产出台词。**

## 2. 契约

```
输入（来自 knowledge-model.md）
  model.nodes + model.relations      知识图谱（偏序，不分先后）
  learner.prior_knowledge / misconception   起点 S0 与已知障碍
  dependencies                        必须提前建立的前置概念
  learning_outcome                   终点判据（每个 Transition 的 success_condition 溯源到这里）
  scope.exclude                      禁止引入的概念（不得为过渡方便而偷加）

输出（交给 cognitive-timeline.md）
  learner_constraints{}              约束集：§6
  transitions[]                      规划结果：§4 + §7，含候选顺序与选定顺序的理由
  beat_count_range                   不可合并的 Transition 数（§7 Merge Test 之后），供 Scene 分组倒推
```

**Timeline 是这一层的规划结果，不是原始数据。** 谁在这层之外"顺手切成五幕"，
就绕过了整个编译链——这是本项目最容易被破的一条架构纪律。

## 3. 五种认知操作（第一版只这五种）

| 操作 | 认知目标 | 观众获得什么 | 常见 obstacle |
|---|---|---|---|
| `IDENTIFY` | 知道"是什么" | 能认出这类东西 | MISSING / ABSTRACTION |
| `DISTINGUISH` | 知道它与别的东西差在哪 | 不会混用两个概念 | CONFLICT / GAP |
| `RELATE` | 知道它们之间有什么关系 | 能把两个已知物连起来 | GAP |
| `EXPLAIN` | 知道为什么会这样 | 能说出机制 | MISSING / ABSTRACTION |
| `APPLY` | 能把模型用到新情况 | 能预测、能判断该不该用 | TRANSFER / OVERLOAD |

三点纪律：

1. **它们是认知目标，不是视觉动作。** 视觉侧的十种 `visual_operation` 在
   `cognitive-timeline.md` §7，两者**不是一一映射**（同一个 `RELATE` 可以画成 CONNECT，
   也可以画成 CONTRAST）。二者的映射规则属于下一层 `Narrative + Visual Compilation`（§12）。
2. 一个 Transition 主用一种操作。写"操作：RELATE + EXPLAIN + APPLY"说明这是三个 Transition。
3. 五种不够用时先怀疑分型错了，而不是加枚举。`DISTINGUISH` 与 `RELATE` 的分工最容易混：
   分清差别是前者，建立联系是后者。

## 4. Transition schema

```yaml
transition:
  id:                    # t-NN
  from_state:            # 观众此刻持有的解释模型（S_i）
  to_state:              # 变化后持有的模型（S_i+1）
  operation:             # IDENTIFY | DISTINGUISH | RELATE | EXPLAIN | APPLY
  obstacle:              # §5 六选一（可空：本来就没障碍的过渡极少，优先怀疑漏检）
  obstacle_handling:     # 怎么破这个障碍（与 §9 同口径：枚举与理由分栏，不混写）
  required_knowledge:    # 发生这次变化所需、且此刻已在场的概念（必须是已到达状态的一部分）
  evidence:              # 支撑 to_state 的材料，取自 Knowledge Model 的 evidence 条目 id
  success_condition:     # 可观察的检验（观众能说出 / 能判断 / 能预测到什么）
  load:                  # 本步引入的新变量数（进 §8 负荷规则）
```

`from_state` 与 `to_state` 必须可区分且可一句话复述；`success_condition` 必须是
**可观察行为**（"理解了"不合格），且要能追溯到 `learning_outcome` 的某一项。

## 5. 六种认知障碍（本层最重要的部分）

障碍回答的是：**观众为什么还没到？** 它决定这一步该怎么设计，而不是先设计再补理由。

| obstacle | 观众卡在哪 | 本层的处理方式 |
|---|---|---|
| `MISSING` | 缺少必要前置概念 | 在当前位置**之前**插一个前置 Transition（走 `IDENTIFY`），不要就地塞定义 |
| `CONFLICT` | 现有理解与目标模型冲突 | 先让旧模型解释失败（反例），再给新模型；顺序上必为 `DISTINGUISH/EXPLAIN` 且带反例 |
| `GAP` | 两个已知概念之间缺关系 | 只补关系不补概念（`RELATE`），最容易被误做成重复讲解两端概念 |
| `ABSTRACTION` | 概念太抽象没有锚点 | 挂具体载体物（`EXAMPLE` 类视觉操作），并把该步 `load` 压低 |
| `OVERLOAD` | 一次要处理的新信息太多 | 拆 Transition（这是 Split Test 的触发器），或把非关键项移入 `optional_details` |
| `TRANSFER` | 原例懂了但不会迁移 | 收尾必带一个 `APPLY` Transition，用**新情境**验证，不要重复原例 |

`OVERLOAD` 与 `TRANSFER` 最常被漏检：前者表现为"每一幕都对但整片听不下来"，
后者表现为"观众记住了例子却答不出新问题"——正好对应 `learning_outcome` 里
`explanation` 有而 `prediction / application` 没有的 IR。

## 6. 第一阶段求解：Learner Constraints

```yaml
learner_constraints:
  prerequisites:            # 必须提前建立的概念；标明"假定已有"还是"本片自建"
  misconceptions_to_resolve: # 需要破除的点（依 task_type 可为空）
  essential_relations:      # 必须理解的关系（来自 model.relations 的哪几条）
  optional_details:         # 与本次 claim 无关、或可留到下一期的细节（**不是"为缩短而砍"的清单**）
  load_budget:              # 单个 Transition 的新变量上限（默认 1，见 §8）——管的是单步负荷，
                            # 与总时长无关；本项目**单期不设时长上限**（principles P5）
  outcome_coverage:         # learning_outcome 各项由哪些候选 Transition 负责
```

**这一阶段不排序**。它只把"必须发生什么"和"可以不发生什么"分清楚。
`essential_relations` 与 `optional_details` 的划分是为**单步负荷与注意力**服务的：
先让细节退出关键路径，观众才看得见必讲的关系。它不是"缩短总时长"的手段——
本项目不设时长上限（`principles` P5），该讲六分钟就讲六分钟。

## 7. 第二阶段求解：Transition Planning 与最少 Beat 数

> **Beat 数量不由内容长度决定，而由不可合并的认知转变数量决定。**

先按 `essential_relations` 与 `obstacle` 生成候选 Transition，再过 **Merge Test**：

**Merge Test（四个条件全部满足才可合并）**

```
1. 后者不依赖前者作为独立的新知识；
2. 两者共享同一个解释目标；
3. 合并后不会降低理解顺序的清晰度；
4. 可以在同一个视觉状态中自然完成。
```

反过来的 **Split Test**（任一命中即必须拆）：两者 `operation` 不同、`obstacle` 不同、
后者的 `required_knowledge` 恰好是前者要建立的、或合并后 `load > load_budget`。

例：`A → B` 若观众必须先知道 A 才能理解 B，不能合并；
而 `A` 加"`A` 的第二个例子"若没引入新认知变化，就不配成为独立 Transition（Merge Test 1、2 命中）。

**Beat 数下界 = Merge Test 之后剩余的 Transition 数**。幕数（Scene）在下一层由板面分组决定，
本层不碰（`cognitive-timeline.md` §5）。这就把"切几幕"从手感变成了可复核的推导链。

## 8. Cognitive Dependency 与线性化六规则

依赖不是一条线：

```
A
├── B
├── C
└── D（同时依赖 B + C）
```

`A→B→C→D` 与 `A→C→B→D` 在知识上都成立。**Timeline 的任务不是复述知识结构，
而是为学习选出最合理的线性化**——这才是"编译"的实质。选择按六条优先级依次判定：

```
1. 前置依赖必须先出现（违反即拓扑错误，硬约束）；
2. 新概念尽量挂在已建立的概念上；
3. 关键关系在两端都建立之后再揭示（关系先于两端 = P3 领先违规）；
4. 高认知负荷的 Transition 避免连续堆叠（连续两步 load=2 就应该插过渡或拆序）；
5. 能当场验证的内容优先于纯抽象陈述；
6. 结论尽量晚于支撑它的模型——除非倒置有明确教学目的（如悬念钩子），
   此时须在卡上登记理由。
```

第 1、3、6 条是可静态检查的（对应 `cognitive-timeline.md` §10 的 Dependency 与 Reveal 两项）；
第 4、5 条偏经验，先由人工判并记录在卡上。

多条合法顺序同时成立时，**选中的那条要写明依据哪一条规则胜出**，否则下次同题重编会换一套顺序，
沉淀不下来。

## 9. 从三样东西生成 Beat

```
Knowledge Model（用哪些知识） + Learner Model（发生哪次转变） + Timeline Position（排在第几步）
        ↓
Cognitive Beat
```

正式定义（本文与 `cognitive-timeline.md` §6 同一条字段表，以本文为准）：

```yaml
beat:
  id:
  state_before:          # = transition.from_state（措辞落到观众能懂的话）
  state_after:           # = transition.to_state
  cognitive_operation:   # 五种之一
  obstacle:              # 六种之一，**只放枚举值**
  obstacle_handling:     # 本步怎么处理这个障碍（原来挂在 obstacle 括号里的理由挪到这里）
  knowledge_used:        # 引用的已有概念（nodes id）
  knowledge_added:       # 本 Beat 新引入的概念（nodes id）
  narration_goal:        # 为了发生这次变化必须说什么（不是台词，是说话的目的）
  visual_goal:           # 不画出来观众会卡在哪
  visual_before:         # 此刻画面上已有什么（= 上一 Beat 的 visual_after）
  visual_after:          # 本 Beat 结束时画面上该有什么
  visual_operation:      # 十种枚举之一（cognitive-timeline §7）
  reveal_order:          # visual_before → visual_after 之间的分区先后
  prerequisite_beats:    # 拓扑前置（含跨幕引用）
  hook: false            # P3 唯一豁免，须写理由
  success_condition:     # 继承 transition.success_condition
```

> **口径变更（2026-09-07，代码事实优先）**：本表原写「`obstacle`：六种之一（含处理理由）」，
> 但 `whiteboard_story/ir_contract.py` 的 `EP.OBSTACLE` / `LM.OBSTACLE` 要求该字段严格等于枚举值，
> 带括号说明即被 lint 阻断（首期样本 ai-world-class-designer 编译时撞见）。现拆两栏：
> `obstacle` 只放枚举、`obstacle_handling` 放处理方式。**「必须写处理方式」这条判据不变**，只是换了字段——
> 处理方式仍是本层最重要的东西（§5：障碍决定这一步怎么设计），只是不再和枚举混在一个字符串里。
> 原写法「obstacle 含处理理由」**作废**。

`visual_before / visual_after` 是把 P1"视觉随认知一起长"钉成字段：相邻 Beat 必须首尾相接
（`beat_n.visual_after ⊇ beat_n.visual_before` 且 = `beat_{n+1}.visual_before` 的可见子集），
接不上就是画着画着换题。`narration_goal` 与 `visual_goal` 谁都不是实现细节——
它们是**编译意图**，台词与板图在下面两个平行分支里各自实现它。

## 10. 方向纪律：先变化，后语言

```
Cognitive Beat → Narrative Intent（narration_goal） → Narration（台词）
```

禁止反向（先写漂亮台词再给它找知识意义）。这条方向本身就是降 AI 味的手段：
台词是"为了让变化发生而必须说的话"，不是"关于这个话题的顺口句子"。
视觉侧同理：`Beat → visual_goal → Visual Reveal Specification`。

四线并行且一一对应，这是整个编译模型的骨架：

```
认知： S0 → S1 → S2 → …
语言： L0 → L1 → L2 → …
视觉： V0 → V1 → V2 → …
时间： T0 → T1 → T2 → …
```

任意一列单独存在都不合法：有 L 无 S 是废话，有 V 无 S 是装饰，有 S 无 T 是论文提纲。

## 11. 实例

### 缓存（示范"不复制知识结构"）

Knowledge Model 的图是 `请求 → 缓存 → 数据库`，但 Learner Model 不搬这条线：

```
S0 不知道缓存为什么有用
 ↓ t1  IDENTIFY   obstacle=ABSTRACTION  重复读取是真实存在的问题（用登录态/商品详情举例）
S1 知道"同一份数据会被反复要"
 ↓ t2  RELATE     obstacle=GAP         请求可以先经过缓存这一层
S2 知道缓存挡在请求与数据库之间
 ↓ t3  EXPLAIN    obstacle=MISSING     命中时数据库不必再执行查询
S3 理解命中为什么减少数据库工作量
 ↓ t4  APPLY      obstacle=TRANSFER    什么场景值得加缓存（读多写少 / 一致性代价）
S4 能判断该不该用
```

终点覆盖了 `learning_outcome` 的 explanation 与 application 两项 → 出口闭环（§4 最后一行）。
四个 Transition 过 Merge Test：t1/t2 不合并（t2 的 `required_knowledge` 正是 t1 建立的 → Split Test 命中）。
所以这条知识**最少 4 个 Beat**，幕数是另一层的事。

### 本期挂起那期（重规划，示范容量与障碍）

```
S0 以为自己拿到的图平庸是提示词/模型不行
 ↓ t1  IDENTIFY    ABSTRACTION   同一提示 → 四个实例产出同构页面（现象落地，e1）
S1 知道"AI 给的东西都长一样"是个普遍现象，不是自己的运气问题
 ↓ t2  DISTINGUISH CONFLICT      "要求随机"仍雷同：真随机 vs 听起来随机（e2）
S2 知道随机不能靠要求，得从外面来
 ↓ t3  EXPLAIN     MISSING       逐词预测挑最多人满意的答案 → 结构性保守（e3）
S3 理解为什么会保守（机制）
 ↓ t4  APPLY       GAP           外部注入：跑代码拿随机字符串 → 定配色排版（e4）
S4 会用随机字符串这条路径
 ↓ t5  EXPLAIN     GAP           独立评审只看截图、迭代到 9/10（e5）
S5 知道为什么"另开一个 AI 挑毛病"比自己改有效
 ↓ t6  APPLY       TRANSFER      做减法：删光晕彩字空框（e6）
S6 知道最后一步是删，而不是再加一版
 ↓ t7  APPLY       —             迁移到新场景：下次自己做设计时按 t4→t5→t6 三步走
S7 能在新项目上复用整套流程
```

过 Merge Test：t1/t2 不合并（t2 的 `required_knowledge` 正是 t1 建立的现象）；
**t7 与 t6 合并**（Merge Test 四条件全中：t7 不依赖 t6 之外的新知识、共享"减法才有高级感"这一
解释目标、顺序清晰、可在同一板面上以"擦除 → 干净骨架"完成）。
所以本期的 **Beat 数下界 = 6**，而不是把 7 个转变硬画成 7 幕。

与上一版 7 幕的区别不在数量而在**每一步都有 obstacle 依据**：旧版最后那幕只是"三件套复述"，
没有认知变化，按 §7 本该并进减法那一幕。`load` 逐格检查：t2 引入真随机 / 假随机两个概念，
但都是对已画现象的解释，算 1；t3 是解释链最重的一步，其后 t4 立刻转入操作，
不构成连续高负荷（§8 规则 4 通过）。

顺序判定记录（§8）：t2 排在 t3 之前依据规则 5（"仍雷同"能当场验证，机制不能）；
结论（"要从外面注入随机"）放在现象与机制之后依据规则 6（不倒置）。

## 12. 交给下一层的问题（已定稿 → `expression-plan.md`）

本层定"发生什么转变、几个、什么顺序"；**"为什么这句话配这一笔"** 由表达层回答，四问的落点：

1. `cognitive_operation × obstacle → narration 策略` → `expression-plan.md` §3（八种语言功能）
   + §2（`attention_target` 决定重音与高亮落点）；
2. `cognitive_operation → visual_operation` 的合法映射 → `expression-plan.md` §5 的四层词汇链
   （cognitive → visual → reveal → 内核动作），跨层混用即编译错误；
3. `visual_before → visual_after` 的 delta 推导 → `expression-plan.md` §4 + §7（离散
   `reveal_operation` 绑定 `narration_span`；`cognitive-timeline.md` §6.1 只留终图与分区预算的落地映射）；
4. 什么时候不画 → `expression-plan.md` §6 通道分配三问（有空间结构才画；因果理由归语言；
   `OVERLOAD` 的处理手段之一就是改用说）。

## 13. 反模式

1. **Step 化**：直接列步骤 → 那是脚本，不是认知路径；
2. **复制知识图**：把 `model.relations` 原样拉平成序列（跳过 §6 约束求解）；
3. **按长度切 Beat**：用"这期几分钟"反推"讲几段"（违反 §7 原则）；
4. **障碍漏检**：obstacle 全填 MISSING，或干脆留空（最常见的是 OVERLOAD 与 TRANSFER）；
5. **伪 DISTINGUISH**：只是并列介绍两个东西，没建立差别；
6. **收尾缺 APPLY**：观众记住了例子却推不出新情形；
7. **顺序不记理由**：多条合法解并存时不写依据哪条规则胜出，同题重编每次换一套顺序；
8. **越层写台词**：在本层就打磨句子，把 `narration_goal` 空着。
