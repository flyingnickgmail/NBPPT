# 研究出处与采用边界

核查日期：2026-10-18。以下是设计方法研究，旧案例不进入当前业务报告的数据。技能中的友车科技配方、节奏、字号及组合要求是我们的设计决策，并非媒体背书或它们公布的全部规范。

## 权威商业媒体与新闻图形

### FT-V · Financial Times（金融时报）的 Visual Vocabulary（视觉词汇）

[官方说明与分类](https://github.com/Financial-Times/chart-doctor/blob/main/visual-vocabulary/README.md)

要点：先识别故事里的数据关系，再考虑图种；分类是构思起点，不是自动正确的选图器。
采用：把目录入口改为读者问题；每个配方同时说明前提和误用。没有复制原海报、完整图鉴或媒体商标。该说明页版权保留，不能把它与下述模板代码的许可混为一谈。

### FT-AI · 金融时报《Inside the relentless race for AI capacity》

[原文与实际图形，2025-07-31](https://ig.ft.com/ai-data-centres/)

可核对的案例：传统/AI数据中心用同视角结构对照；CPU/GPU用逐个与并行的像素变化解释工作差异；不同机构电力需求预测保留来源区别。
采用：结构变化用注释式对照，动效用于展示差异；数量与结构用不同图形回答。实例包含真实建筑，但建筑有结构解释任务，不能推广为所有主题都画建筑。
访问证据：正文与图形说明可读；浏览器动态首屏停在加载态，未把整套动画标为已完整运行验收。未采用其当年预测作今日判断。

### EC-H · The Economist（经济学人）的幸福与经济增长案例

[官方可复核代码/图表说明](https://github.com/TheEconomist/graphic-detail-data/tree/master/data/2019-03-23_happiness-economics)
；[可读取原始说明](https://raw.githubusercontent.com/TheEconomist/graphic-detail-data/master/data/2019-03-23_happiness-economics/README.md)

要点：文章配套分析把同一国家在两段时期的收入与幸福水平配对，支持检查共同位置及变化；不能用一条均值概括两个变量的关系。
采用：将“二维关系”和“同一对象跨期轨迹”列为不同配方，并要求对象、期间和统计量可对应。正文付费访问返回402，本次不声称看过付费全文；研究依据为作者官方公开复现资料。数据仓库标示MIT，文章和图片的授权另算。

### RG · Reuters Graphics（路透图形）的编辑部指南

[Making your first chart](https://reuters-graphics.github.io/newsroom-datawrapper-guide/getting-started/making-your-first-chart/)

要点：先整理并检查数据解析，再选图、注释；标题、说明、来源和替代文字是出版内容的一部分。
采用：把单位、期间、来源、可访问描述作为图形本身的组成，而非附加装饰。该指南链接的 Dos and Don’ts 本次返回404，未据此推导额外规则。

## GitHub 借鉴对象

| ID / 项目 | 值得借鉴 | 本次边界 |
|---|---|---|
| FT-T · [ft-interactive/visual-vocabulary-templates](https://github.com/ft-interactive/visual-vocabulary-templates) | 有序点图、斜率、排名变动、箱线、宽度编码组成等数据图配方；模板之后仍需编辑打磨 | README标示MIT。本次不安装老依赖、不复制媒体样式、没有移植其渲染代码 |
| OP · [observablehq/plot](https://github.com/observablehq/plot) | 点/线/区间叠加与分面，组合表达比不断增加独立图组件更灵活 | 仓库ISC；本次为结构参考，未安装。具体扩展须先补数据协议、测试、原始许可 |
| AV · [antvis/Infographic](https://github.com/antvis/Infographic) | 内容、结构、主题、渲染分离；可编辑图形和语义描述 | [MIT](https://github.com/antvis/Infographic/blob/main/LICENSE)。默认快速示例是步骤箭头，不适合用户已排除的流程框图，不能直接套默认模板 |
| RC · [reuters-graphics/graphics-components](https://github.com/reuters-graphics/graphics-components) | 新闻图形页面的组件化组织 | 本次页面未发现明确许可入口；只研究架构，不复制代码/字体/图像，不推定公开可见即允许复用 |

推荐取舍：保留现有网页渲染与铜橙风格，把内容选择规则接入；无需先引入一个大图形框架才能提高表达。高级配方中尚未支持的数据结构明确列为储备，避免模型输出不存在的图种。

## 没有作为规范依据的入口

经济学人2017图表样式PDF在搜索索引存在，但本次直接访问返回设计系统首页；未将其细节声称为当前官方标准。HBR（哈佛商业评论）检索到相关文章，但未阅读全文，不据此写详细规范。FT另一个电力专题跳转到产品页，本次不绕过访问限制。

## 原创规则

目录标为 ORIGINAL 的定性点阵、证据分类、上下对齐的累计组合，是结合本项目数据约束整理的工作配方。配方可与公开图形惯例相似；示例不是真实经营结果。当前数据不足时，宁可保留清楚的定性解释，也不发明专业感。

### 2026-10-19 补充核查与采用
[经济学人可视化作者访谈](https://education.economist.com/blog/interviews/tips-for-visualising-data-like-the-economist)公开展示温度计式比较、气泡及单色突出主系列：采用有限色、相邻读数和明确比较对象；没有复制媒体品牌和原图。2017 PDF入口仍重定向，不冒充已读。
实际打开用户指定Kimi长城研究报告，核对共同标尺、直接数值标注、重点色、依据与说明的层次；借鉴阅读顺序，不采用其经营数字作为当前报告来源。paired_columns与动画时间参数是本项目设计，不是媒体官方标准。
