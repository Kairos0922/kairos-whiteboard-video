# 白板动画 / 手绘揭示视频渲染引擎调研（survey-whiteboard-render-engines.md）

> 2026-09-11/12 调研。所有事实性结论均回溯到 GitHub 一手仓库（README / 源码文件 / 仓库元数据），
> 关键处标注 repo URL 与文件路径；star 数与活跃度取自 GitHub API 元数据（口径 2026-09-11）。
> 面向读者：kernel.py 的维护者会话，用途是给 `kernel-design.md` §5 参照清单供货。
> 已深挖过、本文只留定位段的项目：gnipbao/whiteboard-video-engine（现用数学底座）、
> masihsultani/whiteboard-animator（Kinoslide，见 kernel-design §5）。

## 0. 结论速览

1. **「真实语音边界驱动的绘制调度」不再完全空白，但我们的形态仍是独一份。** 词级时间戳驱动白板绘制已出现三种形态：
   (a) brandonvant/claude-skill-whiteboard-explainer 以 Whisper 词级时间戳为**唯一时间源**做编排（但时间表由 LLM 逐项目撰写、揭示是蛇形掩码而非骨架描线）；
   (b) 现用上游 gnipbao/whiteboard-video-engine 新版用豆包语音 2 词级时间戳驱动的是**全局绘制进度 0→1**（无分区/对象时间窗，`src/whiteboard_skill/tts.py` `_word_phrase_cues`）；
   (c) ChenShuo2004/cs-board 的短语级 Whisper 对齐只用于 Remotion「动态信息图」元素入场，其白板笔迹模式仍是 SRT 字幕级。
   **「词级边界 → 分区/对象揭示时间窗 → 骨架笔画级调度」的自动编译链，调研范围内没有第二个实现**——这是本仓库 P2 的差异化底线，仍然成立。
2. **出现了一个以 geeklee/srt-whiteboard-animation 为共同上游的中文「SRT 白板 skill 生态」。** cs-board（548★）与 nikola（201★）都直接 vendor 其脚本；其骨架追踪注释明写「移植自 whiteboard-video-engine preprocess.py」——与本仓库同一数学底座。这条独立演化的分支收敛到与本项目近似的三件套（分区遮罩编排 + 骨架/网格流式笔迹 + ink→color 两段式），等于外部验证了管线方向；它们的时间粒度停在字幕级，与我们的词级仍差一档。
3. **三家开源项目用不同表述执行了与 P3 同源的红线**，可以互相印证地写进质量门槛：cs-board「系统不得悄悄退回按字数、页长或平均间隔估算」且 `estimated_fallback_used 必须 false`；nikola「词时间不可靠时采用完整句字幕，不伪造逐字卡点」；brandonvant「never from character-proportional estimates (they drift seconds on long lines)」。
4. **手部跟随的全部公共做法 = 素材归一化锚点 + 固定角度 + 平滑**；没有人做透视/3D 旋转。可低成本移植的增量只有两个：nikola 的 hand-follow 缓动（单侧 lerp，0.08–1.0 钳制）与 brandonvant 的 A/B 双姿态按笔画方向切换 + 笔尖作旋转原点 + 「落笔才显手」生命周期。
5. **矢量（SVG 路径）路线没有出现适合位图板图的新方案**，其价值集中在可搬运的机制而非引擎：tegaki 的「虚线中心线掩码揭示变宽填充」（= 本内核「沿骨架刷宽复制」的矢量版，做文字逐笔描字时参照）；png2svg 的「位图原图嵌入 + 隐形引导路径」桥接；brandonvant 的 mural 相机与掩码擦除拍恰好对应本内核 REFRAME / REMOVE 两个缺口的第一份开源参照。另注意：上游 gnipbao 新版已显著超出本仓库锁定的 rev（词级节奏、文字描字、对象成组、照片抽线模型），锁定策略的机会成本在上升，建议排一次 rev 升级评估。

---

## 1. geeklee/srt-whiteboard-animation —— SRT 字幕驱动的分区揭示 + 流式笔迹（生态源头）

- 仓库：https://github.com/geeklee/srt-whiteboard-animation 。Python，MIT（LICENSE：「Copyright (c) 2026 江哥是老登啊」）。**2026-07-27 当天创建并最后推送**，3.2k★（元数据如实记录；创建即高星的成长曲线异常，star 数仅作量级参考）。
- 定位：把 SRT 字幕做成「暖米黄纸张底的流式笔迹白板手绘动画」的 Codex/OpenAI 形态 agent skill，两阶段产物：`annotation.json` 编排（sequence / startMs / subtitle / protectedRegions）+ `stream_render.py` 渲染。
- 技术路线（`SKILL.md` + `scripts/stream_render.py`）：
  - **编排层**：分区遮罩揭示。区域允许掩码 = 矩形 region − 后续区域 region − protectedRegions；「未开始区域完全隐藏」是显式不变量（SKILL.md「遮罩不变量」节）。区域内时间按 `ink:color = 2:1` 切成起笔/添彩两段；区域间串行，窗口可对齐该区域对应字幕的时长，另给 `150 px/s × 绘制距离` 的初始估算。
  - **笔迹层**：每区域 stream 连续落墨，`ink_path_mode: "grid" | "skeleton"`。骨架模式注释明写「移植自 whiteboard-video-engine preprocess.py：Zhang-Suen 细化 → 8邻接最直边追踪」（`stream_render.py:746` 附近）；笔画排序为包围盒左上角 + 负长度的字典序（`_order_skeleton_strokes`）。
  - **上色**：`contour-wipe`（轮廓感知自上而下扫描，带阻力场衰减系数 0.86 / 前沿扣减 / 18 趟横扫）或 `brush`（沿轨迹圆形刷）。
  - **判墨**：`ink_threshold = 10`（灰度 < 10 视为墨迹）+ 背景回染（与四角取样背景色差 < 28 染底）——只认「亮底暗线」。
  - **手部**：`assets/drawing-hand.png`，裁剪后笔尖锚点固定 (0,0)（`tip_anchor_x/y = 0.0`），无旋转、无缓动；60fps 输出缓解抖动。
- 可借鉴点（对照 kernel-design §5 缺口）：
  - **ink:color 2:1 窗口切分**与**允许掩码不变量**：对象级编排（第 3 项）与多边形区域（第 2 项）落地时，"region − 后续区域 − protectedRegions" 是现成的防串区公式，可对照本内核「质心落点 + 丢弃」策略补齐遮挡场景；
  - **contour-wipe 参数组**（行衰减/趟数/前沿扣减）是蛇形行距自适应（第 5 项）之外的另一条「轮廓感知扫掠」参照；
  - 25–35s/幕的分镜承载规则、「字幕驱动、逐步确认」的关卡式工作流。
- 不适用点：时间源是 SRT 字幕（≈ 句级），没有词级对齐；判墨白底硬编码（比 Kinoslide 的 gray<240 更极端）；1080 长边降采样；手部无缓动；本体是 skill 文档 + 脚本，无测试、无包管理，工程化程度低于本内核（nikola fork 后补了 schema 校验测试）。

## 2. ChenShuo2004/cs-board —— 参考音频 + 中文文案 → 白板视频的完整产品

- 仓库：https://github.com/ChenShuo2004/cs-board 。Python + Node（Remotion 4.0.515），MIT（仓库元数据 + LICENSE）。548★ / 94 fork，创建 2026-08-21、最近推送 2026-09-05——**活跃**。README 带赞助商位，是"产品化"程度最高的一家。
- 定位：「白板声画工坊」本地 AI 工作台：IndexTTS 2.5 音色克隆 + 中文文案 + 12 视觉模板 + 人物/风格参考图 → 分镜插画 → 白板动画 → 字幕音画合成 → MP4。有 webapp / 局域网队列 / 断点复用。
- 技术路线：
  - **白板笔迹模式 = vendor geeklee**：`scripts/parse_srt.py` 与 geeklee 仓库逐字节一致（本调研 diff 验证），`stream_render.py` 仅调参（30fps、长边 1440、`skeleton_min_points=24`「只让手跟随主要轮廓」、重采样间距 5.0 抗抖动）。时间窗仍来自 SRT/标注（`render_stream_whiteboard.py` 按 `reveal.startMs` 排序推进），**字幕级**。
  - **「动态信息图」模式 = 短语级 Whisper 契约**：`docs/semantic-timing-contract.md` 是全调研最完整的一份语音对齐设计文档——Whisper.cpp `medium` 以 DTW token 时间输出词组边界（16kHz 单声道 PCM）；原文切成短语后每条短语给真实起止毫秒 + 字符匹配覆盖率 + 置信度；「近音误识别只允许使用前后强锚点夹定的真实语音边界」，且「该步骤完全独立于页面规划」；元素入场帧 `start_frame = ceil(spoken_start_ms × 30 / 1000)`（向上取整保证不早于触发短语）；强制门槛含「整篇原文字符匹配覆盖率不低于 72%」「系统不得悄悄退回按字数、页长或平均间隔估算」。
  - Remotion PPT 版式语法（question/focus/comparison/evidence/layers/path/cause/overview）、关系箭头需原文证据否则强制回退 none。
- 可借鉴点：
  - **短语级对齐契约可直接移植为本项目质量门槛**：覆盖率门槛、`estimated_fallback_used 必须 false`、跨繁简/数字中文读法归一（`scripts/semantic_timeline.py` 的 OpenCC t2s + 数字→中文表）、短语边界禁插值——与 `validate.py`/`quality-checklist.md` 的现有口径互补；
  - 「先时间表后内容结构」的固定生产顺序（时间表先行、内容模型只引用短语编号）与 P2 同构，可作为表达层→内核接口顺序的第三方印证；
  - 其白板模式调参（min_points=24、间距 5.0）是「骨架碎片过滤」的同行经验值。
- 不适用点：白板笔迹模式无词级对齐（短板同 geeklee）；动态信息图是「元素入场式 PPT」不是逐笔手绘；渲染依赖 Remotion/Node 双栈；产品形态（webapp、模板、TTS 服务）超出内核层职责。

## 3. hi-nikola/hand-drawn-explainer-video-nikola —— 中文手绘讲解 skill：词级时间戳策略 + 手部缓动

- 仓库：https://github.com/hi-nikola/hand-drawn-explainer-video-nikola 。Python/JS，Apache-2.0（另有 LICENSE-MEDIA 管媒体资产）。201★，2026-09-02 创建、09-03 推送——活跃。
- 定位：「中文手绘知识讲解视频 Codex Skill」：讲一部分画一部分的逐笔故事动画（单场景/多幕/左右双语义岛）+ 程序动画（HTML/SVG/GSAP）双路线。渲染后端直接 vendor geeklee（`vendor/srt-whiteboard-animation/UPSTREAM.md` 记录快照 commit `325c5c7`），本体负责旁白、字幕、合成与验收。
- 技术路线（对语音对齐最诚实的一家）：
  - `references/voiceover.md`（配音与对齐）：「优先级：真实有效词/句时间戳 → 原稿与音频强制对齐 → 句级 ASR 校对 → 实测停顿辅助」；火山引擎 TTS 原生词时间戳要检查「非空、顺序、边界和原稿对应关系」；**「词时间不可靠时采用完整句字幕，不伪造逐字卡点」**；「静音检测……不能识别停顿前说了哪句话；只能作为辅助」。
  - `references/stroke-story-workflow.md`：`startMs/durationMs：来自真实音频`（句/字幕级写入 annotation.json）；「先用实际音频为每个区域分配落墨、补色和完成停留时间，再决定源图能承载多少细节；不能先生成一张密集图，再靠加快笔迹硬塞进旁白」；20 秒以上多事件文案优先拆 4–8s/幅的连续故事画面；`scripts/check_drawable_regions.py` 在标注后做源图可绘制性检查（区域越界/重叠/岛间留白/同一连通笔迹跨区）。
  - **手部缓动**：`--hand-follow 0.35`（vendored `render_stream_whiteboard.py:77` 钳制 0.08–1.0；实现是逐帧 `new = old + (tip-old)*follow` 的单侧 lerp，:147）；「0.35 让手部缓动追随，降低移动过快对观感的干扰。它只改变手部显示位置，不改变旁白、笔迹或场景时长」。默认骨架 + contour-wipe + 0.35 作为「正式样片」参数。
- 可借鉴点：
  - **hand-follow 缓动**一行可移植进 `draw_hand_pen.py`（注意其语义是位置平滑、不是时间轴改动）；
  - 「画幅承载判断 + 可绘制性检查」是防"串区/断笔画"的前置质检，可对照本内核 assign_element 丢弃策略做成上游检查；
  - 词级时间戳的**降级阶梯**（词→强制对齐→句级→停顿辅助，且明示哪一级在用）与 P2 的 words.json 真值口径互补，值得进 `quality-checklist.md`；
  - 「双语义岛」是版式层可用的构图语言。
- 不适用点：时间窗写入仍是人工/LLM 标注确认制（无词级自动编译）；骨架/掩码机制与 geeklee 同源（无新渲染数学）；强绑定火山引擎 TTS 与 Windows PowerShell 脚本。

## 4. brandonvant/claude-skill-whiteboard-explainer —— 词级时间戳为唯一时间源 + 蛇形掩码揭示（技术密度最高的小仓库）

- 仓库：https://github.com/brandonvant/claude-skill-whiteboard-explainer 。Claude Code skill（SKILL.md + 模板/脚本），MIT（LICENSE + 元数据）。仅 3★、2026-07-09 当天创建并推送——**不活跃、单作者**，但 `references/` 四篇文档是全调研单位篇幅信息量最大的。渲染引擎为 npm [HyperFrames](https://www.npmjs.com/package/hyperframes)（HTML→MP4）。
- 定位：自称与 VideoScribe/Doodly 同架构——「Finished, detailed illustrations revealed through an animated serpentine mask, with a photo hand holding a marker riding the mask's tip」；明确拒绝 SVG 逐笔路线（"animating SVG stroke paths (which caps quality at stick figures)"）。
- 技术路线（`references/reveal-engine.md`、`references/hand-prep.md`、`SKILL.md`）：
  - **词级时间契约**：「**Whisper word timestamps as the sole timing source** — every draw, label, camera move, and SFX cue derives from real spoken-word times — never from character-proportional estimates (they drift seconds on long lines)」；「An element finishes drawing at or just before its keyword; a label STARTS being written as its word is spoken」；每个场景块的编排注释必须写明对应词时间。QA 门：每 2 秒逐帧审计 + Whisper 校验每条 TTS 成品。
  - **揭示机制**：每元素一张隔离图 + SVG `<mask>`（黑底矩形 + 蛇形 stroke 路径），揭示 = 掩码路径的 `stroke-dashoffset` 动画；蛇形行中心内缩 sw/2、行距 ≤ stroke 宽度、`scripts/coverage-check.py` 查覆盖。mix-blend-mode 的 Chrome 合成层坑、t=0 布局竞态闪现等 10 条「调试出来的不变量」。
  - **擦除拍（REMOVE 参照）**：「black serpentine strokes appended to the SAME mask (later siblings win) with the cloth hand riding」——擦除 = 向同一掩码追加黑色蛇形笔画，因元素图像隔离可自由越界不伤邻区。
  - **相机（REFRAME 参照）**：mural 世界 + 相机 wrapper（`translate = viewportCenter − worldPoint × scale`）；「Camera: locked between moves… Never run a mask reveal while the camera travels; land the pan, then draw」。
  - **手部**：photorealistic 姿态集（draw-A/draw-B/drag/erase），**引擎按笔画方向在 A/B 姿态间切换（"the swap IS the realistic wrist motion"）**；每姿态单独标定笔尖像素并设 CSS `transform-origin` 到笔尖（旋转围绕笔尖抖动）；「Hand visible iff a stroke is in progress. Hide within ~0.05s of a stroke ending」；前臂必须出画、40–60% 画幅高；「One gesture per element：a single element's chunks draw back-to-back with no stall… slow the single gesture rather than pausing mid-draw」。
- 可借鉴点：本仓库 REFRAME/REMOVE/HIGHLIGHT 三个缺口在此首次找到开源参照（相机锁拍规则、掩码擦除、以及"元素在关键词说完前完成"的收口原则）；蛇形行距不变量直接服务第 5 项「蛇形行距自适应」；「元素完成时刻 ≤ 关键词末」可作为词级编译的目标函数约束。
- 不适用点：每元素一张隔离图的资产模型与「一张板图 + 分区标注」的产出结构完全不同（它靠图像模型出分元素图，我们没有这个资产）；时间表由 LLM 逐项目撰写而非编译生成——**它满足 P2 的"来源真实"，但满足不了"确定性可重跑"**；HyperFrames/浏览器渲染链违背本地 ffmpeg 确定性红线；仓库规模太小（3★、无 issue 生态），只能当文档读，不能当依赖。

## 5. gnipbao/whiteboard-video-engine —— 现用数学底座：新版盘点（定位段 + 必要更新）

- 仓库：https://github.com/gnipbao/whiteboard-video-engine 。Python，MIT。94★，2026-06-26 创建、**2026-09-03 推送**。本仓库 pyproject 按 rev 锁定的上游；kernel-design §1 已记录 Zhang-Suen/八邻接/切向合并等数学底座，此处不重复，只记录**锁点之后的新变化**（本调研浅克隆 main 实测）：
  - **词级时间戳驱动**：README「支持豆包语音 2 词级时间戳驱动手绘节奏，并输出独立 SRT」。实现链（`src/whiteboard_skill/providers/tts_doubao.py`：Seed-TTS 2.0 返回逐词 startTime/endTime/confidence → `src/whiteboard_skill/tts.py` `_word_phrase_cues` 把词合成 6–14 字、标点或 2.5s 切组的短语 cue → **全局绘制进度**：`_narration_paced_time`（`whiteboard.py:1607`）把墙钟时间映射到 0→1 的整体视觉进度，「nearly constant drawing speed during speech while punctuation gaps still pause」；cue 间隙画面停住）。**没有分区/对象级窗口**——对象只是按「大轮廓 → 细节」排序（README「物体完整性：连通对象优先成组，独立物体才分块」），整体进度扫过全部笔画。
  - **文字逐笔描字已在上游实现**：`whiteboard.py:534 _text_to_strokes`（文字排版→掩码→zhang_suen→trace_8connected→笔画）与 `_text_wipe_strokes`（每行一条左→右揭示路径，reveal_width=行高），外加「多行中文自动排版、手写路径和逐行擦显」。
  - **手部**：`HAND_ANCHORS` 每素材归一化锚点表（asian 0.04,0.28 / black / children / white，`whiteboard.py:30`），缩放 ∝ max(resolution)/640；固定角度（README 自述「内置固定角度手势」），另有 procedural/none。
  - **照片线稿模型**：`--lineart-provider auto|informative|anime2sketch|anime|manga`（外部 wrapper 导入上游仓库权重）。
- 对本项目的意义：上游已从"数学底座"长成"完整流水线"，其中**词级→短语 cue 的合并/校验代码**与**文字描字**都是本仓库路线图项的直接参照且与本内核同源同风格——比 cross-referencing geeklee 更顺。按 kernel-design §1 的约定，吸收 = 换 rev + 全量测试，建议单独立项评估（§7）。

## 6. masihsultani/whiteboard-animator（Kinoslide）—— 已评估（定位段）

- 仓库：https://github.com/masihsultani/whiteboard-animator 。Python，MIT，2026-09 活跃。定位：位图 → 白板动画的库 + CLI；CRAFT 文字检测逐词书写、组件排序启发式、√面积组件级时间槽、骨架分叉分解、斜向扫掠/鬃毛刷填充双模式、流式帧提交。
- 硬伤（kernel-design §5 已记录）：白底硬编码 gray<240、MAX_DIM=1280 降采样、无语音对齐、无手部跟随。本仓库已"不换底座、按项吸收"，本调研无新增发现，定位段到此为止。

## 7. dai-shi/excalidraw-animate —— 矢量路线代表（Excalidraw 场景动画）

- 仓库：https://github.com/dai-shi/excalidraw-animate 。TypeScript，MIT。2078★，2020-05 创建、**2026-09-10 推送**——长期活跃。定位：「A tool to animate Excalidraw drawings」。
- 技术路线（`src/animate.ts`）：生成自包含动画 SVG，用 SMIL 实现——描线不走 dashoffset，而是**路径形变**：把每条 path 按段拆解，逐段 `<animate attributeName="d">` 从"控制点塌缩"形态变到最终形态（`animatePath`，fill=freeze），支持 C 曲线与 L 折线（`animateFillPath`/`animatePolygon`）；笔尖 = `<image>` + `<animateMotion path=…>` 沿主段移动（`pickOnePathItem` 选最长段），无锚点标定、无旋转；元素默认各 500ms、组内 5 秒均分，未开始元素 opacity 0（`hideBeforeAnimation`）。
- 对比结论（服务 §8 矢量 vs 位图）：这是矢量路线"笔尖贴合 = 天然完美"的活例，但前提是输入本就是矢量笔画（Excalidraw 元素自带 freeDraw 路径）；填充也只能靠路径形变/透明度近似，没有"揭示即原图成形"的像素保真。对本项目：素材生态不同源，引擎本体不可引；其「未开始元素完全隐藏」的 SMIL 冻结手法与填色近似思路可作语义参考。

## 8. gkurt/tegaki（+ parsimonhi/animCJK）—— 字体 → 笔迹动画（文字逐笔描字的矢量参照）

- 仓库：https://github.com/gkurt/tegaki 。TypeScript（npm `tegaki`），MIT。3.1k★，2026-03 创建、2026-07-29 推送——活跃。定位：「Handwriting animation for any font」——任意字体转手写动画，React/Vue/Svelte/Astro/Web Components 多框架 + CLI（`npx tegaki "Hello World"` 出自绘 SVG）。
- 技术路线（`packages/renderer/src/lib/svgExport.ts`、`core/engine.ts`）：字形轮廓 → **stroke-dashoffset 关键帧逐笔描绘**（`@keyframes tk-d{si}` 控 dashoffset: L→0→L 循环，衬 pad 防 round cap 泄露）；**变宽填充用"虚线中心线掩码"揭示**（engine.ts:316「revealed through a dashed-centerline mask over its own timeline window」：粗描填充层 + 中心线 dash 动画作 mask，SMIL `calcMode=spline`）；点状笔画无路径可用，退化为透明度门控。
- 附带：parsimonhi/animCJK（https://github.com/parsimonhi/animCJK ，HTML，无 SPDX，461★，2026-05 推送）提供日/中/韩字符的笔顺 SVG 数据（逐笔 stroke 数据 + 动画），是汉字"真笔顺"数据源。
- 对比结论：tegaki 证明「变宽填充不需要矢量化整个字形，用中心线 dash 揭示即可」——这正是本内核"沿骨架刷宽复制原图像素"策略的矢量镜像，等于独立验证了刷宽复制的正确性。对本项目：当路线图第 1 项「文字逐笔描字」选择"字体轮廓→骨架→描字"实现时，tegaki 的 keyframes/掩码与 animCJK 的笔顺数据是现成参照；但板图文字按主题铁律不入图，该路线只适用于"标签逐字写入"动画（与 kernel-design §5 对 CRAFT 的判断一致：定位相反，届时才回看）。

## 9. manim / animejs / vivus —— 矢量描线原语合集（每个一句话到一段）

- **manim**（https://github.com/ManimCommunity/manim ，Python，MIT，40.8k★，活跃）：`Write/DrawBorderThenFill`（`manim/animation/creation.py:213,291`）不用 dashoffset，而是 `pointwise_become_partial(outline, 0, subalpha)` 先按参数渐进描出**轮廓点集**，后半程再插值淡入填充——与白板类工具不同，它描的是"几何点列"不是"笔画线"，贴线同样完美但要求矢量 mobject。对本项目只作语义参照（描边→填充两段式的鼻祖）。
- **animejs v4**（https://github.com/juliangarnier/anime ，TypeScript，MIT，72.8k★，活跃）：`createDrawable()` + `draw: '0 1'`（`src/svg/drawable.js`）——本质是 pathLength 归一化的 stroke-dasharray/dashoffset 区间插值，还处理了 linecap 在完全隐藏时切回 butt 的细节。工业界最通用的描线原语，公式与 GNU 文档一致。
- **vivus**（https://github.com/maxwellito/vivus ，JavaScript，MIT，15.5k★，2022-07 后停更）：无依赖的 SVG 描线库鼻祖（delayed/sync/oneByOne/场景脚本），附 Vivus Instant 把动画固化成独立 SVG。已停更，引用其机制即可。
- 结论：三者共同给出矢量描线的全部数学（pathLength + dashoffset 区间、点列部分化、描边→填充分段），且都是"能描就能贴笔尖"；缺的是位图输入与语音时间，这正是本内核的辖区。

## 10. cagops/png2svg —— 位图 → 矢量桥（VideoScribe 隐形引导路径）

- 仓库：https://github.com/cagops/png2svg 。Python + potrace，Apache-2.0。2★，2025-09 创建、2025-11 推送——小工具，但思路独特：把 PNG 转成"白板软件可用"的 SVG：**原图原封不动嵌入 SVG**，另附隐形描线引导（potrace 描近黑轮廓 → 按色相由深到浅生成填色笔画序），让 VideoScribe 的 draw 动画按"轮廓先、填色后"的顺序揭示原始位图（README：「The original PNG image is embedded unchanged in the SVG, while invisible drawing guides control the animation sequence」）。
- 对比结论：这是"位图保真 + 矢量调度"的第三条路——既不做骨架化也不丢像素，把揭示顺序外包给矢量引导线。对本项目无直接必要（内核已自建调度），但其"暗轮廓先、色相深浅序"的排序启发式与 png2svg 的 potrace 路径平滑参数可在评估"对象级编排"排序时顺带一看。价值低，保留记录即可。

---

## 其余项目（一句话带过）

- **daslearning-org/image-to-animation-offline**（Python/KivyMD，MIT，39★，2026-09-10 推送）：离线 App，灰度素描先出、彩色后填，无手部无语音对齐——位图类的功能下限参照。
- **yogendra-yatnalkar/storyboard-ai**（Python，GPL-3.0，164★）：文本→分镜→SAM3 分割矢量轮廓→逐笔动画+Veo 串接，旁白只做长度拉伸（"stretches and times the sketch paths to match the audio narration length"）非词级；GPL 传染 + 云端视频模型，不可引。
- **NadirWeb-App/Inkplainer-OS**（TypeScript/浏览器，Apache-2.0，27★，2026-09-03 推送）：浏览器端 Doodly 替代品，4 种轮廓检测 / 3 种上色 / 6 种揭示，层级 Slicer（Grid/Rectangle/Freehand 切区），手部「glides continuously… with a switch to revert to snap-to-position」——浏览器侧的区域切分与手部平滑是本文第 4 节的旁证。
- **Rsverma/OpenDoodler**（C#，AGPL-3.0，65★）：桌面 SVG 逐笔编排，AGPL 不可引。
- **subroy13/handanim**（Python，MIT，48★，2026-06-20 推送）：程序化图元（线/椭圆/多边形）+ 排线/scribble 填充 + 自定义字体手写动画，SVG/MP4 导出——"白板版 manim"，无图像输入管线，做 HIGHLIGHT 类程序化图形时可参考其排线填充。
- **Alexander-Kz/video-layer-skill**（Python，MIT，5★）与 **nutllwhy/whiteboard-book-video-skill**（Python，MIT，59★）与 **Boring-Stuff-Club/the-scribble-thing-skill**（MIT，17★）：同一"旁白 MP3/书稿 → 白板讲解"的 skill 流派，未见超出前述四家的机制。
- **lazypay/Archscribe**（Python，MIT，346★）/ **excalimate**（TypeScript，MIT，67★）/ **muthuishere/diagram-motion**（Go）：Excalidraw 建筑图/关键帧动画支线，输入是矢量场景，与位图板图管线不同源。
- **Whiteboard.fi**（商业，whiteboard.fi）：经核实是 Kahoot! 旗下教师课堂协作白板（"an online whiteboard service specially designed for teachers and classrooms"），**不是**白板动画视频工具，从调研对象中排除。

---

## 8. SVG 矢量路径描线 vs 位图骨架描线：对比与引入条件

| 维度 | SVG 矢量路径类（vivus/animejs/tegaki/manim/excalidraw-animate） | 位图骨架类（本内核/geeklee 系/Kinoslide/gnipbao） |
|---|---|---|
| 笔尖贴合 | 完美：笔尖=数学路径上的点（dashoffset 区间或 getPointAtLength） | 强：笔尖走骨架点列；粗色块/渐变边缘依赖细化质量 |
| 填色 | 需另做（tegaki：中心线掩码揭示；manim：描边后淡入；excalidraw-animate：路径形变近似） | 天然保留：沿骨架刷宽复制原像素，"揭示即原图成形" |
| 输入 | 必须矢量（手绘 SVG / 字体 / Excalidraw 场景 / 程序图元） | 任意位图（文生图直出） |
| 与 AI 生图位图管线的衔接成本 | 高：要么自动矢量化（potrace 类会碎化+抖动+丢色，png2svg 只适合单色轮廓），要么改用分元素矢量资产（brandonvant 模式） | 零：1920×1080 板图直接进管线 |
| 像素保真 | 无（渲染的是路径重绘，不是原图） | 有（终态=原图本身） |
| 文字 | 强（字体即矢量，tegaki/animCJK 有笔顺数据） | 弱（位图文字需 CRAFT 类检测或字形骨架化） |

**对本项目何时值得引入矢量路线**（按 kernel-design §1"板图是位图"前提细化）：
1. 出现**矢量原生资产**的子系统时——最可能的是"标签逐字写入"动画（字体轮廓 + tegaki 式中心线掩码）或表达层的程序化图形（handanim/animCJK 类）；此时矢量只做**局部图层**，终版仍合成回位图画布，不换整体管线。
2. 出现 **Excalidraw 形态的 IR/板图来源**（用户/上游直接给矢量草图）时——可直接复用 manim/animejs 的描线原语，成本≈零；这属于 ir-alignment 的远期选项，不是近期。
3. **不会**因为"笔尖更贴合"而引入：本内核刷宽复制已把贴合误差限制在骨架提取误差内，矢量化的收益（dashoffset 数学）小于成本（位图矢量化质量）。

## 9. 真实语音边界驱动绘制调度：现状图与空白结论

时间粒度光谱（粗 → 细）：

| 粒度 | 项目 | 时间源与用法 | 证据 |
|---|---|---|---|
| 字幕级（SRT） | geeklee、cs-board 白板模式、nikola | SRT 跨度 → sceneDurationMs；区域 startMs/durationMs 人工/预览台定窗、可对齐字幕时长 | geeklee SKILL.md「时长来源…来自该幕字幕的时间跨度」 |
| 旁白长度拉伸 | storyboard-ai | 音频长度拉伸静态线稿动画 | 其 README 第 46 行 |
| 短语级 | gnipbao 新版（全局进度）；cs-board 信息图（元素 Cue） | 词级时间戳合并为短语 cue；前者驱动全局 0→1 进度，后者驱动 Remotion 元素入场帧 | gnipbao `tts.py`/`whiteboard.py:1607`；cs-board `semantic-timing-contract.md` |
| 词级（编排态） | brandonvant | Whisper 词表为唯一时间源，元素在关键词前完成、标签随词书写；但时间表由 LLM 逐项目撰写 | 其 SKILL.md/reveal-engine.md（原文见 §4） |
| 词级（编译态：词→分区/对象时间窗→笔画调度） | **仅本仓库** | words.json → 认知时间线 → 分区揭示窗 → 弧长归一化笔画任务表 | kernel-design §2/§3 |

**结论**：调研范围内，词级语音边界已进入白板视频制作，但要么停留在"全局进度 pacing"（gnipbao），要么停留在"LLM 手写编排 + 每元素隔离图"（brandonvant），要么作用于"元素入场而非笔迹"（cs-board）。**把词级边界自动编译成分区/对象揭示窗、再落到骨架笔画任务表的完整确定性管线，仍是空白**——差异化结论维持，且值得注意的是三家开源护栏（禁止字符比例估算/estimated fallback）证明该红线正在成为共识，应尽快固化进本项目质量门槛与文档表述。

## 10. 手部/笔尖跟随 sprite：方案汇总

| 项目 | 锚点标定 | 方向/旋转 | 平滑 | 生命周期/姿态 |
|---|---|---|---|---|
| gnipbao（新 main） | 每素材归一化锚点表 `HAND_ANCHORS`（asian 0.04,0.28 等），缩放 ∝ max(res)/640 | 固定角度（自述「内置固定角度手势」） | 无（逐帧贴点） | 内置 4 素材 + procedural/none；`_paste_hand_cursor` alpha 合成 |
| geeklee | 裁剪后笔尖 (0,0) 归一化 | 无 | 60fps 缓解抖动 | 单素材 drawing-hand.png |
| nikola（vendored） | 同 geeklee + hand-size 控制 + bare_tip | 无 | **hand-follow 单侧 lerp（0.08–1.0，推荐 0.35）** | 只改显示位置不改时序 |
| brandonvant | 每姿态像素级 NIB 标定 + CSS transform-origin=笔尖 | **A/B 姿态按笔画方向切换（= 手腕写实感）**；围绕笔尖正弦抖动 | 读 getPointAtLength 的纯函数更新（seek-safe） | draw-A/draw-B/drag/erase 四姿态；「落笔才显手、笔停 0.05s 内消失」；前臂出画、40–60% 画幅高 |
| excalidraw-animate | 无（图片中心随 animateMotion） | 无 | 无 | SMIL animateMotion |
| Inkplainer-OS | 未核实（浏览器实现） | 未核实 | 连续滑行 ↔ 吸附两档可切 | 逐层配置 |

无人做透视/3D 旋转；「固定角度 + 锚点 + （可选）缓动」就是当前全部公共知识。对本内核，手部体系（HAND_TIP_RATIO）已存在，边际改进见 §11 建议。

## 11. 商业产品公开可确认特征

只记录厂商公开页面/帮助中心可验证的表述（2026-09-11 访问）：

- **VideoScribe（Sparkol）**：自定义 SVG 是一等公民——官方帮助中心「Creating your own SVG images」教用户制作**带绘制动画的 SVG**；动画模式含 'Hand draw'、'Pen draw'、'Draw'（即无手 draw）、'Drag-in'（带手拖入）与 'Move-in'（help.videoscribe.co/knowledge/how-to-recreating-legacy-projects-in-the-latest-version-of-videoscribe）；官网宣称 AI 配音与音频编辑；图片库 11,000+ 并可导入自有图片（help.videoscribe.co/knowledge/import-images-legacy）。公开页未披露揭示算法细节与语音对齐粒度。
- **Doodly**：上传图片后用「patent-pending "Doodly Smart Draw technology"」**点选式自定绘制路径**（doodly.com 原句：create point-and-click custom draw paths）；板面支持 whiteboard/blackboard/glassboard/green screen；「Record your own custom voiceover audio directly within Doodly, and easily sync it to your Doodle sketch」；导出 MP4 480p–1080p、24–60fps。无公开的自动音画对齐粒度信息（页面对 per-scene timing 无描述）。
- **Animaker**：官网产品线含 "Whiteboard Video Maker"；宣称 Neural TTS（"180+ languages"）、"AI Subtitles & Voices"（1,800+ 人声、130+ 语言字幕）与 lip sync（animaker.com 首页 FAQ/产品区原句）。白板揭示算法细节未公开。
- **Whiteboard.fi**：经核实为课堂协作白板（Kahoot! 旗下），非动画视频工具，排除。

对照结论：商业产品公开层均未宣称"词级语音边界驱动绘制"；Doodly 的 Smart Draw（人工点选 draw path）与本内核的自动骨架提取是同题异解。这一差距与 §9 的开源结论互洽。

---

## 12. 对本项目的建议（供 kernel-design.md §5 参照清单增补）

### 建议吸收（精华，按优先级）

1. **gnipbao 新版 rev 升级评估（最高优先级）**：新版在同一代码风格内新增了 (a) `_text_to_strokes`/`_text_wipe_strokes` 文字描字（路线图第 1 项首选参照，同源成本最低）；(b) 连通对象成组 + 大轮廓→细节排序（第 3 项对象级编排参照，与 Kinoslide 组件排序互补）；(c) 豆包词级→短语 cue→全局进度的 pacing 实现（作 P2 编译层的对照组实现）。按 §1 约定走"换 rev + 全量测试"，一次 rev 同时吃进三项。
2. **词级/短语级对齐护栏 → quality-checklist.md**：从 cs-board（覆盖率 ≥72%、`estimated_fallback_used 必须 false`、近音边界须被前后强锚点夹定且标 `boundary_source`、OpenCC/数字归一）与 nikola（词→对齐→句级→停顿的降级阶梯、不伪造逐字卡点）各取一份，合并成本项目 validate 对 words.json 的校验口径。
3. **brandonvant 的时序约束词表 → 表达层/内核接口**：「元素完成时刻 ≤ 其关键词末」「标签起始 = 词起始」「一个元素一个连续手势、宁慢不停顿」「相机移动期间禁止揭示」——这些可直接编译成 HIGHLIGHT/REFRAME 原语与时间窗的合法性检查。
4. **REFRAME/REMOVE 的机制参照**：mural 世界 + 相机平移缩放、相机锁拍规则（REFRAME）；同掩码追加黑色蛇形笔画实现擦除、元素图像隔离使擦除可越界（REMOVE）。实现前按 §5 规则先解禁表达层，不偷跑。
5. **蛇形行距/覆盖不变量 → 第 5 项蛇形行距自适应**：brandonvant 的"行中心内缩 sw/2、行距 ≤ stroke 宽度、coverage-check" + geeklee contour-wipe 的阻力场参数组，两组合起来够设计 FILL_ROW_STEP 自适应。
6. **hand-follow 缓动 → draw_hand_pen.py**：nikola 的单侧 lerp（默认 1.0 保持现状，可配 0.35）+ brandonvant 的"A/B 姿态按方向切换、笔尖为旋转原点、落笔才显手"是低风险增量；换手素材必须重校锚点的既有教训不变。
7. **允许掩码不变量 → 第 2/3 项**：geeklee 的 region − 后续区域 − protectedRegions（含 maskPaddingPx）与 nikola 的 check_drawable_regions 前置检查，用于补齐遮挡场景与"贴边元素丢失"的权衡面。
8. **文字描字数据源（远期）**：animCJK 汉字笔顺 SVG + tegaki 中心线掩码揭示，仅在版式层启动"标签逐字写入"时回看。

### 明确不引（糟粕）

- **SRT 字幕级时间窗作为最终时间源**（geeklee/cs-board 白板模式）：粒度低于 words.json，引入即违反 P2；只吸收其编排不变量与 UI 思路。
- **geeklee 系灰度阈值判墨**（`ink_threshold=10`、Kinoslide `gray<240`）：都是亮底暗线假设，与底色自适应判墨冲突；背景回染（match_bg）可单独记住。
- **brandonvant 的每元素隔离图 + LLM 手写时间表 + HyperFrames**：资产模型与"一张板图 + 确定性编译"冲突；HTML→MP4 渲染链违背本地确定性红线；仓库规模与持久性不足。只读其文档，不依赖其代码。
- **GPL/AGPL 项目代码**（storyboard-ai、OpenDoodler）：许可传染，仅作机制旁证（SAM3 分割做对象级编排的思路可远观）。
- **矢量引擎整体引入**：见 §8 条件表——近期无条件触发；只按局部图层/远期 IR 两种触发条件个案评估。
- **云视频模型串接**（storyboard-ai 的 Veo 等）：违背本地确定性红线。
