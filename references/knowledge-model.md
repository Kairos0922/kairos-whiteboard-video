# Knowledge Model（编译器前端语义 IR）

> 本层的任务**不是"理解文章"**，而是把任意知识输入压缩成一个适合教学编译的结构化模型。
> 它必须先回答一句话：**我要让观众最终建立什么模型？**
> 上游是原始知识（一句话 / 文章 / 现象 / 问题 / 观点 / 机制 / 争议），下游是 `cognitive-timeline.md`。
> 判据出处 `whiteboard-video-principles.md`（P3 时序、P4 忠于来源）。

## 1. 前端全链与本层位置

```
RAW KNOWLEDGE      自然语言对象，不可直接编译
      ↓ 本文
Knowledge Model    教什么、观众是谁、建什么模型、学到什么程度、不解释什么
      ↓ 本文 §8 产出视图
Knowledge Graph    model.nodes + model.relations（偏序结构，不分先后）
      ↓ learner-model.md（内含两阶段：约束求解 → Transition 规划 + Merge Test）
Learner Constraints 从当前状态到目标状态，最小要发生哪些认知操作
      ↓
Cognitive Timeline S0 → … → Sn，逐 Beat 的状态转移
```

比 `Knowledge → Cognitive Timeline` 多两级，好处是可检查：知识没读错时图谱对得上模型，
编译不越权时序列对得上图谱。**没有这两级，"拆成几个 Beat"就完全靠临场发挥。**

## 2. 三条设计取向

1. **不从"知识点"开始。** "飞机为什么能飞"编译成 `升力 / 伯努利 / 机翼 / 气压` 是**知识目录**，
   不是模型。目录没有方向也没有终点，生成不了认知路径。
2. **Claim ≠ Model。** `target_claim` 是观众最终该**说出来**的话（结论）；
   `model.core` 是观众脑中该**形成**的结构（解释机制）。视频真正教的是后者——
   只有 claim 的片子等于播报结论：观众复述得出那句话，却推不出任何一个新情形。
3. **不强制找"误解"。** 本工具是白板知识科普，不是概念纠错工具。四类教学任务并存（§6），
   没有明显误解就填 `misconception: none`。硬造一个稻草人错误认知，比没有更糟。

## 3. Schema

```yaml
knowledge_model:
  subject:                # 讨论对象，一句话
  target_claim:           # 【必填】观众最终应接受的命题，可被反驳
  task_type:              # 【必填】A 纠正误解 | B 建立新概念 | C 解释机制 | D 建立概念间关系
  learner:
    prior_knowledge:      # 【必填】观众进片时已有什么（决定后面每一步能不能说）
    misconception:        # 选填：观众可能的错误理解；无则 none
  model:
    core:                 # 【必填】最终要形成的内部解释结构（带方向的链条）
    nodes: []             # 【必填】链条里的概念 / 部件
    relations: []         # 【必填】节点关系，每条带类型：causes / depends-on / part-of /
                          #        contrasts-with / enables / balances
  learning_outcome:       # 【至少一项】学会之后能做什么
    recognition:          # 能识别（什么算 API）
    explanation:          # 能解释（为什么缓存能提高响应速度）
    prediction:           # 能预测（命中率提高会发生什么）
    application:          # 能应用（给真实场景选策略）
  evidence:               # 【必填，逐条】防止模型自己补知识
    - claim:
      source:             # URL / 章节 / 实验 / 文档段落；无来源不得进片
      confidence: source-backed fact | model inference | teaching simplification
  dependencies: []        # 理解 core 前必须已建立的前置概念（含本片内自己建的）
  scope:
    include: []           # 本视频解释什么
    exclude: []           # 明确不解释什么（防范围膨胀，也是取舍的证据）
  source_coverage:        # 取材范围与截断说明（付费墙、摘要未覆盖处）
```

字段按三层分组，这就是这层的骨架：

```
Layer 1  Content   evidence / supporting facts   我知道什么事实？
Layer 2  Model     model.core / nodes / relations  事实之间是什么关系？
Layer 3  Outcome   learning_outcome               观众学完能做什么？

FACTS  →  RELATIONS  →  CAPABILITY
```

`dependencies` 与 `scope` 是横向约束，不属于三层，但决定这层编译得动还是动不了。

**别名对照**（历史文档与卡片里仍在用旧名）：`learning_outcome.explanation` ≡ 复述验收句 / `rest_line`；
`scope.exclude` ≡ 旧称 `can_omit`；`learner.prior_knowledge + misconception` ≡ 旧称「认知差」。
新文档一律用 schema 名，卡片与下游可沿用旧名但不得另立定义。

## 4. 填写规则（八处最常写错的地方）

| 字段 | 合格写法 | 不合格写法 |
|---|---|---|
| `subject` | "飞机为什么能飞" | "空气动力学简介"（这是学科不是对象） |
| `target_claim` | 一句可反驳的话 | "了解飞行原理"（判不出立没立住） |
| `learner.prior_knowledge` | 可指认的常识，逐条列 | "大家应该都知道"（凭猜） |
| `misconception` | 有样本来源（评论区高频疑问、来源作者明写的常见错误），或 `none` | 为凑"纠错结构"现编 |
| `model.core` | 带方向的链条 | 四个并列名词（无箭头 = 无模型） |
| `model.relations` | 每条带关系类型 | "有关系"（类型决定下一层怎么线性化） |
| `learning_outcome` | 至少一项，动词开头、可观察 | 四项硬填满（凑数等于没写） |
| `scope.exclude` | 点名砍掉哪几块 + 理由 | 空（默认能讲都讲 → 片长失控） |

**`scope.exclude` 先写。** 长文输入时，写不出省略清单说明还没读懂材料，禁止进下一层。
这是防"复述原文退化成章节化播报"的唯一硬闸。

## 5. Evidence 三档置信度（防"编一个解释"）

模型为了让故事顺畅，天生倾向补出听起来合理的因果。所以每条支撑材料显式分档：

| 档 | 含义 | 进片要求 |
|---|---|---|
| `source-backed fact` | 来源明写或有数据支撑 | 正常讲述 |
| `model inference` | 从来源推出来的推断，来源未言明 | 旁白须带"按这个逻辑"类标记，且不得当唯一支柱 |
| `teaching simplification` | 为可画可懂做的简化（如省略黏性、三维涡系） | **必须登记**，且不得与来源事实混讲成"就是这样" |

`source_coverage` 与 `confidence` 共同落实 principles P4「忠于来源」：来源未覆盖的内容
（付费墙之后、摘要之外）一律不进片；简化不等于错，但**未登记的简化就是幻觉**。

## 6. 四类教学任务（`task_type`）

```
TYPE A  纠正误解        必填 misconception；结构：前信念 → 反例 → 新模型
TYPE B  建立新概念      misconception 常为 none；结构：旧锚点 → 差异 → 新概念 → 识别练习
TYPE C  解释机制        核心是 model.core 链条；结构：现象 → 剖视 → 因果链 → 预测
TYPE D  建立概念间关系  核心是 relations；结构：两个已知物 → 对照 → 关系 → 用它推新例
```

`task_type` 决定两件事：① `misconception` 填不填；② 下游用哪种骨架与哪几种
`visual_operation`（A 偏 `COUNTEREXAMPLE`，B 偏 `CONTRAST + EXAMPLE`，C 偏 `DECOMPOSE + CAUSE`，
D 偏 `CONTRAST + CONNECT`）。新增类型必须同时给出这两问的答案，不能只加个名字。

输入形态与常见 `task_type` 的对照（形态决定抓取方式，不决定任务类型）：

| 输入形态 | 常见 task_type | 抓取重点 |
|---|---|---|
| 一个现象 | C | `model.core` 链条是否闭合 |
| 一个概念 | B | `prior_knowledge` 里能借的锚点物 |
| 一套机制 | C | `nodes` / `relations` 完整性 |
| 一句观点 | A 或 B | `evidence` 撑不撑得住，撑不住降级为个人经验 |
| 一个事实 | B 或 C | 它挂进哪个已有模型（否则不值得做） |
| 一个问题 | C | 问题的锋利度：为什么现在问 |
| 一个争议 | D | 双方最强论据各自成块，不替观众下结论 |
| 一篇文章 / 长文 | 先判型 | 先写 `scope.exclude` 降维，再填其余 |

## 7. 出口判据（可以进 Learner Constraints 的条件）

- [ ] 必填齐全：`subject / target_claim / task_type / learner.prior_knowledge / model.core /
      model.nodes / model.relations / evidence / dependencies / scope`
- [ ] `model.relations` 把 `nodes` 连成连通图（有孤立节点 = 模型没成形，或该节点进 `exclude`）
- [ ] `learning_outcome` 至少一项，且是可观察行为而不是"理解了"
- [ ] 每条 `evidence` 有 `source` 与 `confidence`；所有 `teaching simplification` 已登记
- [ ] `scope.exclude` 非空并写明理由
- [ ] `target_claim` 与 `model.core` 不互相复述（同义 = 只有结论没有机制）
- [ ] `source_coverage` 与实际取材一致，截断处标明
- [ ] **claim 单一性**：全片只承载一个 `target_claim` 与一条连贯的解释模型链。
      出现第二个独立主张（"另外顺便讲讲 X"）→ 拆成一期，而不是塞进同一期。
- [ ] 负荷合理性：单个必懂项所需的新概念数在单步可承受范围内（超了就拆 Transition 或补前置，
      见 `learner-model.md` §6–§7）。**时长不设上限**：秒数只用于节奏判断，
      不得当作砍 `must_understand` 或强行合并 Beat 的理由。

## 8. 交给下一层的东西

```
model.nodes + model.relations   →  Knowledge Graph（偏序，不分先后）
learner + dependencies          →  起点与前置门槛
learning_outcome                →  终点判据（每条 Beat 是否必要，靠它反推）
scope.exclude                   →  禁止出现在旁白与板图里的内容
evidence                        →  Beat 的 claim / evidence 字段的唯一来源
```

本层**不做**：不排教学顺序、不拆 Beat、不写台词、不选画面。
一句话——Knowledge Model 描述"我要教什么"，Cognitive Beat 描述"观众怎样一步步学会"。

## 9. 下一层：Learner Model（已定稿 → `learner-model.md`）

知识图谱不能直接拉平：`A causes B` 与 `A depends-on C` 不等于 `A → B → C`。
中间的转换器就是 Learner Model，本文交出 §8 那五样东西后由它接手：

```
learner_constraints{}   约束求解：前置 / 待破误解 / 必讲关系 / 可省细节 / 负荷预算
transitions[]           转变规划：五种 cognitive_operation × 六种 obstacle，success_condition 可观察
beat_count_range        过完 Merge Test 的不可合并转变数 → Beat 数下界
```

原先留在这里的四个开放问题，定稿答案：

1. **粒度归属**：拆成两层。本层与 Learner Model 的约束求解阶段只说"必须发生什么"，
   顺序与揭示归 `cognitive-timeline.md`；本文不排顺序。
2. **候选与选择权责**：Learner Model 允许存在多条合法线性化，但**选中一条必须在卡上写明
   依据六条优先级中的哪一条胜出**（`learner-model.md` §8）——否则同题重编每次换一套顺序，沉淀不下来。
3. **容量口径**：本层不做拆片判断，也**不因时长砍内容**（时长无上限，优质优先）。唯一的拆期
   理由是 §7 的 claim 单一性——出现了第二个独立主张。单步过载由 Learner Model 的
   `load_budget` 与 Split Test 处理（`learner-model.md` §6–§7）。
4. **多任务混合**：`task_type` 允许多值，但必须显式标主骨架与副骨架各出几个 Beat
   （`learner-model.md` §11 的 A+C 例子即示范写法）。

## 10. 两个实例

### 飞机（TYPE C，示范 claim 与 model 的分工）

```yaml
subject: 飞机为什么能飞
target_claim: 飞机能飞，是机翼与空气相互作用产生了足以支撑重量的升力
task_type: C
learner:
  prior_knowledge: [东西松手会往下掉, 风扇吹风会让人往后退, 船能浮在水面]
  misconception: none        # 若观众确实相信"发动机把飞机往上顶"，则改判 TYPE A 并填此条
model:
  core: 机翼使气流偏折 → 气流与机翼间产生空气动力 → 向上的升力分量 → 与重量平衡
  nodes: [机翼形状, 气流, 动量改变, 升力, 重量]
  relations: [机翼形状 causes 气流偏折, 气流偏折 causes 空气动力, 升力 balances 重量]
learning_outcome:
  explanation: 说出升力来自机翼与空气的相互作用，而不是发动机朝下推
  prediction: 速度过低或迎角过大时升力不足，会失速
evidence:
  - {claim: 机翼使气流偏折并产生反作用力, source: 空气动力学教材环量章节, confidence: source-backed fact}
  - {claim: "上下表面路程差导致压强差"这一常见讲法不严谨, source: 同上, confidence: source-backed fact}
  - {claim: 只讲二维剖面、省略黏性与三维涡系, source: —, confidence: teaching simplification}
dependencies: [力与平衡, 流速与压强的定性关系]
scope:
  include: [升力从哪里来, 为什么需要速度, 迎角与失速]
  exclude: [伯努利与环量的数学推导, 推力与阻力的关系, 翼型设计史]
```

### 本期挂起那期（TYPE A+C 混合）

```yaml
subject: 为什么 AI 做的设计都长一样，怎么让它出好设计
target_claim: AI 设计平庸不是模型能力问题，而是其选择机制偏向最多人满意的安全答案；随机性必须由人从模型外部注入
task_type: A + C（A 为主骨架，C 出两到三个 Beat）
learner:
  prior_knowledge: [用过任意 AI 生成页面或图, 知道提示词是什么, 不要求会编程]
  misconception: 我拿到的图平庸是因为我提示词写得不好，或者我用的是弱模型
model:
  core: 逐词预测挑最多人满意的答案 → 输出结构性保守 → 同提示产出雷同
        → 真随机须从模型外部注入 → 随机字符串定方向 → 独立只看截图的评审迭代 → 人为做减法
  nodes: [下一词预测, 最安全答案, 假随机, 随机字符串, 独立评审, 减法]
  relations: [下一词预测 causes 最安全答案, 最安全答案 causes 假随机, 随机字符串 enables 真多样,
              独立评审 improves 质量, 减法 enables 高级感]
learning_outcome:
  explanation: 说清"为什么要求它随机仍然雷同"
  application: 下次让 AI 做设计时，先跑代码拿随机字符、再设独立评审、最后主动删
evidence:
  - {claim: 同提示给四个实例产出同构页面（紫渐变、左文右图）, source: Technique 1, confidence: source-backed fact}
  - {claim: 要求"完全随机"仍同色系同结构, source: Technique 1, confidence: source-backed fact}
  - {claim: LLM 逐步预测最多人满意的答案＝设计-by-committee, source: 开篇, confidence: source-backed fact}
  - {claim: 随机字符串种子法（String Seed of Thought, Sakana AI）, source: Technique 1, confidence: source-backed fact}
  - {claim: 评审角色占不到 10% 输出 token，直接让大模型重做贵一倍, source: Technique 3, confidence: source-backed fact}
  - {claim: 三阶段流程受双钻设计流程启发, source: 作者自述, confidence: model inference}
dependencies: [知道提示词是什么, 知道"生成随机字符串"是跑代码而不是许愿]
scope:
  include: [为什么平庸, 注入随机, 独立评审, 做减法]
  exclude: [图像生成接 API 的三种接法（纯工具配置）, 视频生成抠像与关键帧插值（同上）,
            AI 找点子三步法（属另一条主张，单独成期）, 作者在苹果的前史（一句字幕足够）]
source_coverage: 部分——正文止于 Technique 6；技巧 7 及以后在付费墙外，一律不进片
```

按新口径复核：`nodes` 6 + 必讲 `relations` 5 → 候选转变约 7 个，Merge Test 后 **Beat 下界 6**
（`learner-model.md` §11）。**6 个 Beat 不构成拆期理由**——时长不设上限，优质优先。
这期只有一个 `target_claim` 与一条连贯链，所以它是一期，不是两期。
上一期真正的病根是两条：没跑 Merge Test 就把 7 个转变硬摊成 7 幕；以及 scene-01 / 06 各写了
5 个 `elements`，**超出每幕 2 至 4 分区的硬约束**（`quality-checklist.md`「板图」段）。

## 11. 反模式清单

1. **知识目录化**：`model.core` 写成并列名词，没有方向；
2. **只有结论没有机制**：`target_claim` 与 `model.core` 互相复述；
3. **为凑故事编解释**：`confidence` 全填 `source-backed fact`，或干脆不填；
4. **scope 膨胀**：`scope.exclude` 为空；
5. **硬造误解**：判成 TYPE A 却没有样本支撑的 `misconception`；
6. **outcome 假满**：四项齐填但都是"理解了 X"；
7. **越层**：在本层就排顺序、写台词、想画面（那是 §9 与下游的事）。
