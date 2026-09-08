# 白板叙事引擎设计方案（engine-design）

> 状态：已定稿（2026-08-26 项目维护者三项拍板记录见 §10）。技术把关：技术负责人；产品拍板：项目维护者。
> 综合：项目维护者提供的 8 步生产流程教程 + GitHub 同类项目调研 + 现有代码基线。
> 一句话总纲：**一切时间从真实语音边界推导，一切画面按讲解顺序揭示，三次确认（质量门）之间机器不自由发挥。**

## 0. 现状基线

> **已作废删除（2026-09-03）**：此处原有一张 2026-08-26 的"教程 8 步覆盖度约 55%"快照表与
> 资产现状段。`ir-alignment.md` §3 审计判定整表废弃——`voice` 三件套、`words.json` 词级窗口、
> 结构化 `script.json`、validate 均已实现，快照只会误导开工。判断现状一律以本文 §12 / §13 与
> `cognitive-timeline.md` §12 映射表为准。

## 1. 总体架构：认知层之上，五层实现

2026-09-03 补：引擎之上还有**第 0 层=认知与表达层**（`whiteboard-video-principles.md` 判据 +
`knowledge-model.md` 语义 IR + `learner-model.md` 转变规划 + `expression-plan.md` 表达编译 +
`cognitive-timeline.md` 时序化）。
引擎不吃"知识"，只吃这条链投影出的确定性产物
（`express-card.md` → `script.json` → `words.json` → `layout.json`）；
认知决策（哪些必懂、几个 Beat、怎么分组、先画什么）全部发生在第 0 层，代码层不替观众决定。

```
┌─ 适配层 providers/（可替换的外部能力）
│    voice.py        语音生成（voice：TTS+词级时间 / attach-audio：已有音频接入）
│    prompt_builder.py  只产 prompt；PNG 由宿主模型生成后 import
├─ 资产层 themes/（跨期复用轴=主题包：风格+角色+手素材一体，核心程序不认识任何固定 IP 名）
│    themes/<theme-id>/style-block.txt + theme.json + characters/ + hands/（含笔尖锚点）
│    templates/<tpl>/（纸面规格、清场动作定义）
├─ 管线层 workflow.py + state.json（确定性操作唯一入口，八阶段状态机+两次确认）
├─ 内核层 kernel.py（笔画→运动→帧→单幕无声 MP4；已 v1，扩展点见 §5）
└─ 合成层 assemble.py（场景拼接 + 逐字卡拉OK字幕 + 音频混缩 + validate 闸门 → final.mp4）
```

项目目录契约维持上轮拍板的「临时项目自携」：

```
projects/<project-id>/
├── project.json        用户想做什么（主题、模板、系列引用、适配层选择）
├── state.json          机器做到哪一步（phases + 确认记录 + 文件指纹）
├── input/              express-card、script.json、narration.mp3、captions.srt、words.json
├── build/              image-prompts / raw-boards / boards / annotations / review / scenes / work(缓存)
└── deliverables/       final.mp4
```

三层职责不可穿透：input 存已确认内容，build 全部可重生，deliverables 只放终版。
**返工范围沿依赖链走**（§8 重跑矩阵），state.json 是系统判断「哪些还能用」的唯一依据。

## 2. 全引擎的时间轴心：words.json（本次设计第一优先）

教程最值钱的一条：**所有派生时间都从真实语音边界计算**。现状的标注时长是
「版式 10% + 各区均分」，旁白讲哪里画面动哪里全靠巧合，这正是「视觉顺序=讲解顺序」
（principles P3 / `script-design.md` §1 第 4 条）目前没闭环的根因。

设计：

1. voice 适配层调 edge-tts（本机免费），产出三件套：
   `narration.mp3` + `captions.srt`（句级）+ `words.json`（词级 start_ms/end_ms）；
   已有配音走 attach-audio：音频 + SRT 必填，words.json 可选（缺省降级句级）；
   （2026-08-28 声源选型复评：edge-tts 留任主线，本地 TTS 调研与品牌声音试点见
   `life/personal/decisions/2026-08-28-whiteboard-voice-tts-selection.md`；声音身份入主题
   voice 块，validate 增声音身份漂移警告。）
2. script.json 的每幕带旁白原文；标注器在 words.json 里**按台词文本匹配**定位
   每幕的词级时间窗（起点=本幕首词，终点=末词+150ms 缓冲）；
3. 幕内元素窗口：版式层吃片头，其余按「元素对应台词短语」的词级区间分配；
   台词里找不到对应短语的元素退回均分并打 warning；
4. 口播改动 → 重新生成三件套 → 所有派生时间自动重算，字幕与手绘永不各守旧秒数；
   （口径：卡上的 `est_ms` 只用于立项判断时长预算与步数，**不作为手填秒数进入下游**。）
5. 确认指纹：script_audio 确认时记录三件套的 sha256，render 前复核，变了就阻断
   （教程的「确认后又改了口播，旧图不被误用」落地为代码）。

## 3. 八阶段管线（教程口径 → 我们的实现物）

| # | 阶段 | 输入 | 动作 | 产物 / 确认点 | 现状 |
|---|---|---|---|---|---|
| 1 | 建项目（绑主题） | 主题、模板选择 | init（校验主题包完整性） | project.json、state.json | 增强 |
| 2 | Timeline 投影 | 已过审的表达设计卡（Beat 序列 + 终图） | 由 Beat 卡合并拼接成幕，不做二次创作 | input/script.json（scenes+elements；`beats[]` 字段待建，现阶段 Beat 只存在于卡上） | 新增结构化 |
| 3 | 声音与时间 | script 或已有音频 | voice / attach-audio | 三件套；**第一次确认**（口播+试听+分幕预览） | 新增 |
| 4 | 整幕板图 | 已确认脚本 | prompts 词表 + 宿主模型逐张（批准制）+ import | input/prompts、build/boards | 生图在宿主 |
| 5 | 审核分区 | boards + 安全区 | 统一底色、越界整体缩放、分区标注、编号预览 | annotations、review/index.html；**第二次确认** | 增强（自动缩放+预览页） |
| 6 | 笔画编排 | boards + annotations | 前景提取→骨架→追踪→合并→区域归属→任务表 | build/work/<scene>/strokes.json（缓存） | 已有，加缓存 |
| 7 | 幕渲染 | 笔画+模板+时间 | 描线、填色、标题描字、清场动作 | build/scenes/scene-XX.mp4 | 增强（文字+清场） |
| 8 | 合成验收 | 场景片+三件套 | concat + 卡拉OK字幕 + 混音 + validate | final.mp4；validate 报告 | 增强（validate+卡拉OK） |

两次确认位置与教程一致：脚本+配音（第一次）、图片+绘制顺序（第二次）。
表达设计卡（我们独有）卡在阶段 2 之前，是第 0 步。

## 4. 主题包层设计（项目维护者已拍板：资产跟主题走）

跨期复用轴只有一条：**主题**。主题包从「风格块」升级为完整视觉身份：

```
themes/<theme-id>/
├── theme.json          主题元数据 + 角色表 + 手素材表（含笔尖锚点坐标）
├── style-block.txt     风格词块（生图 STYLE_BLOCK，定稿冻结）
├── style-spec.md       风格规范与生成链路约定
├── probe*.png          探针校准图（固定构图+固定 seed，只变量=风格块）
├── characters/         角色定妆图（跟主题走：如 小孩/机器人/小本本）
└── hands/              手部素材（跟主题走：纸面白板笔 / 黑板白粉笔各一套）
```

- 项目 project.json 声明 `theme` 绑定（沿用现有 state theme 机制）；init 校验主题包
  完整性（角色、手素材、锚点齐全才放行）；
- 换主题 = 换整套视觉身份（画风、角色、笔），脚本与时间链完全不动；
- 渲染核心只接受路径与锚点参数，不认识任何固定 IP 名；
- **素材归属两分**（消歧，别与 SKILL 步骤 3 打架）：跨期复用的角色定妆与手素材跟主题走，
  存 `themes/<id>/characters|hands/`；本期专有一次性道具与本片独有角色落 `projects/<ep>/assets/`。
  同名时主题包是源、当期是实际使用件，渲染只吃当期路径（`build_video.py` 的 `--hand` 与
  `assets/hand-pen.png` 优先，回落引擎默认）。

## 5. 内核层扩展（kernel.py v1 → v2）

v1 已定决策不翻案（底色自适应判墨、质心归属最小矩形、描线拷原像素、蛇形填色、
抬笔预算制、收尾整图兜底；详见 kernel-design.md）。v2 按价值排序扩展：

| 扩展点 | 设计 | 依赖 |
|---|---|---|
| 文字描字 | 标题用本地字体轮廓转笔画（借鉴上游 _text_to_strokes），先描边后填色；图片模型不承担正式中文 | macOS 中文字体扫描 |
| 清场动作 | 非末幕结尾：纸面翻页 / 黑板板擦（模板定义动作+时长，吃场景尾部时间）；末幕保留完整结论 | 模板层 |
| 词级窗口 | annotation 的元素 reveal 区间由 words.json 推导（§2），内核不改只吃新标注 | 语音层 |
| 多边形区域 | annotation region 支持 polygon 点列；内核掩码代数从矩形扩到任意多边形（教程集合规则：本区∩前景−后续−保护区） | 标注器 |
| 保护区 | protectedRegions 字段 v2 起真实生效（v1 忽略） | 同上 |
| 对象级编排 | 同区内按对象分组（近邻聚类）再排序，运动更接近真人作画 | v1 任务表改造 |
| 行距自适应 | 色块密度高的区自动加密蛇形行距 | 纯内核 |

## 6. 合成层设计（实现物：`assemble.py`，早期文档称 compose.py）

1. 字幕：ASS 逐字卡拉OK（当前字高亮、未读普通色），直接吃 words.json；
   只有句级 SRT 时整句显示，**不伪造不存在的词级边界**；
2. 音画对齐：各幕 mp4 时长已与词级窗口对齐，concat 后旁白按幕起点偏移混入
   （adelay + amix），替代现「单文件 -shortest」的粗对齐；
3. 输出口径不变：H.264 + AAC、30fps、1920×1080、faststart。

## 7. 验收层设计（validate，交付前闸门）

只拦「无法交付」的问题，其余降为 warning 由人决定：

- 阻断：视频轨缺失/时长异常、配置了旁白却无音轨、板图损坏或尺寸不对、
  元素越出安全区、确认后文件指纹变化（脚本/配音/板图任一）、annotations 缺幕；
- 警告：构图过密（路径总长超阈值）、元素窗口过挤（MIN_STROKE_MS 触发率高）、
  字幕带与内容重叠风险（现有底部亮度检查收编）；
- 产出：validate 报告落 build/review/，终审时项目维护者连报告一起看。

## 8. 重跑矩阵（依赖驱动返工，机器据此最小化重做）

| 改了什么 | 重新生成 | 可保留 |
|---|---|---|
| 口播含义/时长 | 三件套→标注→受影响幕渲染 | 角色图、手素材、模板、其他幕 |
| 某幕板图 | 该幕标注+渲染 | 脚本、配音、其他幕 |
| 某元素窗口（改标注） | 该幕渲染 | 板图 |
| 手素材/模板 | 受影响幕渲染 | 全部上游 |
| 字幕样式 | compose | 全部场景片 |
| 主题风格块 | 板图起全链 | 脚本、表达设计卡 |

实现抓手：state.json phases + 确认指纹 + build/work 笔画缓存（按输入文件哈希失效）。

## 9. 分期实施（从小可用版本起步，每期独立可验收）

> 消歧：本节 **P1–P4 是实施分期编号**，与 `whiteboard-video-principles.md` 的 **P1–P4 原理编号**
> 无关。引用时一律写全称（"principles P3" / "分期 P2"）。

- **P1 时间链闭环**（1~2 个会话）：voice 适配层三件套 → 词级窗口标注器 →
  ASS 卡拉OK生成 → validate 最小集（文件+指纹）。验收：任选一篇旧公众号文章
  改成 6 幕脚本，出一条「画面动作与旁白逐词对齐」的 60s 成片；
- **P2 主题包与素材**：theme.json 扩展角色/手素材/锚点字段、手素材重生成与笔尖锚点
  校准小工具、init 主题包完整性校验。验收：连续两期用同一主题，角色一致性肉眼无漂移；
  切换另一主题出片，视觉身份整体切换且脚本零改动；
- **P3 质感**：文字描字、清场动作（翻页/板擦）、多边形区域+保护区、对象级编排。
  验收：黑板主题出一期（板擦清场+亮色笔迹），对比 paper 主题成片；
- **P4 工厂化**：work 缓存与断点续跑、640×360 快速预览档、validate 完整清单、
  每期成本口径记录。验收：中途 kill 渲染后 status 能准确指出续跑点。

## 10. 拍板记录（2026-08-26，项目维护者）

1. **资产复用轴 = 主题**：角色、手素材都跟主题走，不设独立系列层（§4 按此定稿）；
2. **P1 = 时间链闭环**：voice 三件套 + 词级窗口 + 卡拉OK字幕 + validate 最小集先行；
3. **首跑选题走完整流程**：P1 验收片用内容中心选题流程新开的选题，不用旧文改编；
   顺带验证「选题 → 表达设计卡 → 成片」全链。

开工注意：voice 适配层需 `uv add edge-tts`（联网装包 + 生成时访问微软 TTS 服务，
属引擎设计内已声明的依赖）；实现会话建议新开，保持上下文干净。

## 11. 2026-09-02 通道迁移（项目维护者拍板）

1. 板图改由当前宿主的文生图模型生成，删除本地 flux / mflux / t2i 入口。
2. 本地扩散通道主题包整包清退。声音身份迁到 `engine/defaults/voice.json`。
3. 用户路径改为：知识 → 脚本 → 按脚本定素材 → 场景图（张数跟幕走）→ 成片。
4. 开发者加主题：参考图或描述 → 探针 → 冻结后才入 registry。

## 12. 认知层接入待办（2026-09-03 定规范，未动代码）

规范层已落（`whiteboard-video-principles.md` / `knowledge-model.md` / `learner-model.md` /
`expression-plan.md` / `cognitive-timeline.md` / `script-design.md`）。
**字段级保留 / 移动 / 废弃 / 新增与迁移顺序以 `ir-alignment.md` 为准**（§2–§6 逐字段，§8 破坏半径），
本节只留待办条目：

1. **`script.json` 承载语义 IR 与 Beat 层** ✅ **已实现**（`whiteboard_story/ir_contract.py` 校验其形状）：顶层 `knowledge_model{}`（`target_claim / task_type /
   learner / model{core,nodes,relations} / learning_outcome / evidence[{claim,source,confidence}] /
   dependencies / scope{include,exclude} / source_coverage`）
   与 `scenes[].beats[]`（`id / state_before / state_after / cognitive_operation / obstacle /
   knowledge_used / knowledge_added / evidence_refs / narration_goal / visual_goal /
   visual_before / visual_after / visual_operation / reveal_order / prerequisite_beats /
   success_condition / hook`）；
   `narration` 由 Beat 拼接生成而非手抄；beat 可带 `scene_slice` 表示跨幕分片。
   **缺 IR 即阻断，不降级**：表达设计卡是给人看的，不是真相源（`principles` P5）；
2. **入口校验** ✅ **已实现**（`workflow.py lint`，并由 `sync-boards` 前置调用）：检查 `knowledge_model` 必填项非空、
   `scope.exclude` 非空、每条 `evidence` 带 `confidence`、`model.relations` 将 `nodes` 连成连通图，
   以及每个 Beat 的 state_before/after 非空且不相等（QA 第 1 项），缺失即阻断；
3. **标注器按 Beat 分组排程**：panels 归属到 Beat，Beat 边界即揭示边界；支持一 Beat 跨幕
   （各分片在自己的幕里各占分区，`state_after` 落在最后一片）；当前只到 panel 级，
   Beat 结构丢失，是"画面与认知不同步"的根因；
4. **Beat 六项 QA 落 validate**（`cognitive-timeline.md` §10），先做最易静默失败的两项：
   - *Reveal*：分区开画时刻 vs 其锚点 `start_ms`（`hook` 白名单豁免），非零即阻断；
   - *Dependency*：`dependencies` 拓扑序校验，引用未建立概念的 Beat 前置即阻断；
   其余四项（Narrative 完成度、Visual 是否承担认知、Timing 是否够）先出 warning；
5. **分区数与 Beat 数对齐**：每幕分区 2 至 4 个（quality-checklist），且 ≥ 本幕需独立揭示的
   视觉操作数——写卡时就按分区预算倒推分组，而不是画完图再塞。
6. **Learner Model 落 JSON（拦"先定幕数"）**：`script.json` 增 `learner_constraints{}` 与
   `transitions[]`（`from_state / to_state / cognitive_operation / obstacle / success_condition / load`），
   并对 `cognitive_operation`（五种）与 `obstacle`（六种）做枚举校验；
   **`scenes[].beats[]` 的数量必须等于 Merge Test 后的 Transition 数**，不等即阻断——
   这样"先拍五幕再往里填内容"在代码层就过不去（`principles` P5）。
7. **`script.json` 降级为编译产物（不是系统最早期的知识表示）**：新增
   `expression_plans[]`（`expression_goal{narration_goal… attention_target}` /
   `narrative{function, spans[]}` / `visual{objective, objects[], relations[], state_before, state_after}` /
   `reveal[]{op, target, bound_span, at_ms}` / `channel_allocation{verbal[], visual[], shared[]}` /
   `elements[]{id, semantic_role, cognitive_function, introduced_at, used_by[]}`）。
   现有 `narration` / `board_subject` / `elements[].phrase` **保留但改为生成物**：
   `narration` = 各 Beat `narrative.spans` 拼接；`board_subject` = 该幕 `visual.state_after`
   与元素清单的文本化；`elements[].phrase` = `shared` 通道项的词级锚。
   新增校验：`REFRAME` 出现即阻断（内核无视口能力）、`used_by: []` 且无 `cognitive_function`
8. **揭示粒度对齐（本层唯一的破坏性改动，需先拍板）**：`kernel.parse_annotation` 的最小揭示
   单位是 panel（一个矩形整块上墨），而 `expression-plan.md` 的产物是"操作作用在对象上"
   （`DRAW(cache) → CONNECT(req→cache) → GROUP(cache,response)`，target 互相重叠）。
   矩形必须互不搭界（质心归属，`kernel.py` `assign_element`），所以同一对象的多次操作**无法**
   拆成多个 panel。推荐方案：panel 重定义为「揭示单元」（1 单元含 1–3 个 op，区内按对象分子窗），
   前置依赖是 §5 第 3 项对象级编排与 `protectedRegions` 真实生效；分区口径相应改为
   "每幕 2 至 4 个揭示单元"。三选项与影响面见 `ir-alignment.md` §5。

## 13. layout.json 字段契约（代码事实，2026-09-03 补）

实现物：`whiteboard_story/apply_layout.load_scene_layout` 与 `make_annotations_v2._panels`。
像素基准 **1920×1080**（W/H 常量），坐标原点左上。

顶层两种写法等价：`{"scene-01": {...}}` 或 `{"scenes": {"scene-01": {...}}}`。每幕两个键：

| 键 | 字段 | 说明 |
|---|---|---|
| `panels[]` | `x, y, w, h` | 分区矩形，像素；数组顺序 = 揭示顺序 |
| | `color` | 取 `blue/red/orange/green/purple`（预览描边色，缺省 blue），与功能色表无关 |
| `texts[]` | `text, cx, cy, size` | 版式层叠加的编号与标签文字；`size` 缺省 80 |
| | `font` | `"cn"` 走中文字体（STHeiti），否则走数字字体（Arial Bold） |

三条隐含规则（写在文档里以免踩坑）：

1. `panels` 数量必须等于该幕 `script.json` 的 `elements` 数量，且按序号一一对应
   （`elements[i].id = "panel-(i+1)"`）；不等或短语没命中 → 该区退回均分并打 warning；
2. 分区落在安全区内：整图内缩 `INSET = 30` 画虚线安全框，实际绘制区再内缩 14px；
   底部约 1/5 留给字幕带，不压内容（`quality-checklist.md`「板图」段）；
3. `texts` 是唯一的合法文字来源——板图内不得有可读文字，编号与标签一律在此叠加。

