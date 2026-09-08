# 开发者添加主题

完成判据：`themes/registry.json` 出现该 id，且 `theme.json` 的 `style_block.frozen=true`。

## 步骤

1. 建目录 `themes/<id>/`，放入 `style-block.txt`（可从 `references/style-library-handdrawn.md` 取一块再改）和 `probe.json`（固定构图的 subject，只变量=风格块）。
2. 参考图只用于人工拆解与改风格块措辞，不复制到主题包，也不作为生图输入（宿主模型是否吃参考图由当次宿主决定，默认不喂）。
3. 写 `theme.json` 骨架：id、name、renderer_mode（paper/chalk）、resolution `[1920,1080]`。声音不放主题里，用引擎 `engine/defaults/voice.json`。
4. 跑 `workflow.py probe --theme themes/<id>` 打出探针 prompt。报批 1 张。宿主模型生成临时探针，16:9、长边 ≥1920；目检结束即删除，不写入主题包。
5. 对照风格规范目检：细线、低饱和、纸白/板绿、留白、无文字、二维。不命中就改 style-block，重跑探针（每次重跑都是新决策，先报批）。
6. 角色定妆、手笔：脚本需要什么再补 `characters/` 与 `hands/`。手素材分两档
   （**2026-09-07 改**：原「手素材必须按本主题配色画」作废，该规则只保留给插画手；
   写实手为用户拍板的新方向）：
   - **插画/Q 版手**：肤色、袖口、笔身取自 `theme.json` palette / style-block
     （如 chalk 主题=暖桃肤、柔紫袖口、象牙粉笔+象牙描线），配色漂移的手在成片里就是第二个画风。
   - **写实手**：自然肤色摄影质感、素臂（无袖口/手表/首饰），与板底色对比清晰；
     不适用主题配色。三指执笔书写姿、粉笔尖朝左下、小臂出右下。
   共同生产链：宿主文生图纯 magenta 底、笔尖朝左下 → `make_hand_asset.py`
   抠图去底（水印清除、裁边、定锚、板底色预览自检）→ 笔尖锚点写同目录
   `<name>.tip.json`（见 SKILL.md「坑」）。中性马克笔手可用 `draw_hand_pen.py`
   程序化生成，但只配 paper 主题。
7. 用同一主题跑通一期短片（至少 2 幕）确认渲染器 paper/chalk 判墨、手部锚点。换手素材必须重校笔尖锚点（`<name>.tip.json` sidecar 优先，缺省才退 `HAND_TIP_RATIO`；见 kernel-design.md）。
8. 项目维护者冻结风格块后写入 registry.json。未冻结的主题禁止用于正式发布期。
