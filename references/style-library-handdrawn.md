# 手绘风格库（主题包 style-block.txt 的素材库）

> 用途：新建主题或打磨画风时，从这里取基础风格块，配合主题目录的
> probe 校准协议（固定构图+固定 seed，只变量=风格块措辞）收敛。
> 来源：外部创作者手绘动画风格方法论，按脱敏铁律提炼，已去除识别信息。

## 五种基础质感

### ① 纯手绘动画感（治愈日常 / 怀旧叙事）
```
hand-drawn animation, traditional 2D animation,
organic linework, natural imperfections,
painted background, subtle texture,
soft natural lighting, medium shot, warm nostalgic mood
```
核心：organic linework + natural imperfections。禁止追加 clean lineart /
ultra detailed / highly polished，会把质感拉回「精致 AI 插画」。

### ② 水彩（唯美情绪 / 春夏场景 / 恋爱向）
```
watercolor anime, soft watercolor washes, paper texture,
delicate brushwork, subtle color bleeding,
soft diffused lighting, pastel colors, dreamy mood
```
关键：paper texture 必须有，否则只是淡色滤镜；配 soft watercolor washes +
subtle color bleeding 才有水分晕开感。避免高对比与硬边光影。

### ③ 绘本（童话 / 儿童向 / 温暖奇幻）
```
storybook illustration, hand-drawn anime, watercolor texture,
simple organic shapes, painted background, subtle paper texture,
warm soft lighting, wide shot, whimsical fantasy environment
```
关键：simple organic shapes 主动砍掉无效细节；用 wide shot 让人物与环境
一起讲故事（小女孩+蘑菇屋 > 单人怼脸）。

### ④ 铅笔素描（独白 / 回忆 / 情绪向）
```
pencil sketch anime, graphite linework, rough sketch texture,
visible pencil strokes, subtle shading, unfinished drawing feel,
soft natural lighting, close-up shot, minimal background
```
关键：留白即情绪。visible pencil strokes + minimal background 让背景退下去；
特写可换 side profile / over-the-shoulder 表现「望向窗外、低头沉默」类瞬间。
灰度与不完整边缘本身就是表达，不需要鲜艳颜色。

### ⑤ 彩铅（居家日常 / 校园 / 秋冬治愈）——当前主题 color-pencil 即此系
```
colored pencil illustration, anime character, paper texture,
soft colored pencil strokes, layered pencil shading, subtle grain,
warm ambient lighting, medium close-up, cozy indoor setting
```
关键：soft colored pencil strokes + layered pencil shading；拒绝高饱和，
用米白/浅棕/暖黄/雾蓝/豆沙粉系。场景词可换 sunlit bedroom / rainy day cafe /
classroom by the window / cozy desk with books。

## 反模式词表（手绘系通用，出现即「精致的假手绘」）

混入即失效：`clean lineart` / `perfect linework` / `sharp outlines` /
`ultra polished` / `hyper detailed`

保留优先：`organic linework` / `natural imperfections` / `visible pencil strokes` /
`rough sketch texture` / `paper texture` / `subtle grain`

## 使用规则

1. 新主题 = 复制本库对应风格块到 `themes/<id>/style-block.txt`，再走 probe 校准；
2. 白板叙事的板图还要叠加叙事约束：一幕一概念、元素 3～4 个、区与区留白
   （抬笔通道）、同一功能色始终代表同一概念（表达设计卡色表）；
3. 白板/黑板模板对底色有硬约束（纸面暖白 / 板面深绿），风格块不得覆盖底色描述。
