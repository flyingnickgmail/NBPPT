# NBPPT — 三阶段智能体纯图片 PPT 与动效视频直出平台

视频现行入口、预设、音色与边界统一见 [当前视频能力](docs/VIDEO_CAPABILITIES.md)；本地测试及自动门禁见 [开发验证](docs/DEVELOPMENT_CHECKS.md)。本文及实现文档中的日期记录不替代运行时能力和验收回执。

## 当前 PPT 默认链路（2026-10 修复）

`task_type=ppt` 且 `execution_mode=auto/codex_cli` 时，完整原文直接交给
Codex，同一上下文中读取技能、编排内容、逐页调用 `image_gen`。
不再经过会超时回填四页固定文案的独立规划器。客户模板只约束品牌风格，
每页根据内容选择图表、架构、对比、泳道或路线图，不强制三列卡片和底部流程条。

- 随代码提供 `worker/skills/source-image-deck/SKILL.md`；执行机安装的
  `~/.codex/skills/client-ci-ppt-image-deck` 及客户风格参考存在时一并读取。
  模板原文件不存在时使用其配色与描述，生成代理须说明限制。
- `slide_count=0` 由 Codex 按内容决定（当前上限 60 页）；不从原文的截图页码推断页数。
- 每个任务保存原文、实际 `deck_plan.json`、逐页 `review.json` 和执行日志。
  只使用工具返回并复制到本任务目录的图片，不扫描全局“最近图片”。
- 检查原文引文、重复标题/论点、布局类型、图片数量/解码/宽屏比例/重复像素，
  用 python-pptx 封装并重新打开核对页数，再返回完成。失败不使用模板渲染兜底。
- `PASSED` 代表文件检查与生成代理自检通过，不代表独立事实核查或中文文字识别审计。
  图片中的细字、数字仍需人工复核；交付 PPTX 为图片页，文字不能逐项编辑。
- 当前算力结算沿用按页估算，不是订阅账号的实际账单。

执行环境：Python 3.11+，已登录并支持内置图片工具的 Codex CLI。
回归测试统一入口：`NBPPT_TEST_ROOT=/absolute/task/path bash tools/check.sh`。拉取请求及main推送自动执行全量Python、JavaScript及真实nginx部署链路验收；具体依赖、线上只读复核与边界见[研究报告工作台](docs/REPORT_WORKSPACE.md#验证和发布)。
MCP 接入与客户端配置见 [异步 MCP 使用说明](docs/MCP.md)。
可选 Claude 原生路径：模型自主设计原生 PPTX，宿主渲染真实文件后提供预览；管理员按密钥授权 Claude；产品账户历史与额度独立，Claude 运行账号跨进程共用账号锁、持久限流熔断及唯一凭据目录。配置、迁移与发布前门槛见 [Claude 运行说明](deploy/production/README.md#可选官方-claude-code-生成-ppt)。服务器是否已启用须核对运行提交与实际验收结果。
下文三阶段规划说明适用于旧的 Claude / 视频路径，不能作为新默认链路的验收证据。

> 当前本地安全修复：启动前必须配置私有管理员密钥和执行节点密钥；默认演示密钥已停用。
> 交付完成表示严格文件检查通过，**不表示内容终审通过**。历史产物需独立复核后迁移。
> 配置、运行边界与离线测试见 [本地权限与交付说明](docs/LOCAL_SECURITY_DELIVERY.md)。下述旧版能力介绍中的“防封号”和内容终审承诺不构成保证。

**NBPPT** 是一套面向管理咨询、架构汇报与政企方案场景的 **三阶段多智能体 PPT 直出系统**（同时支持 Web 工作台与 MCP Server 接入）。它摒弃了传统机械替换模板占位符的做法，通过 **「Claude / Codex 深度内容策划与提示词工程 $\rightarrow$ Codex (`image_gen`) 纯图片 PPT 或 Claude 技能直出 $\rightarrow$ 主 Agent 终审验收封装」** 的三阶段闭环，直接生成 `1672×941` (16:9) 咨询级高清幻灯片与 `.pptx` 源文件。

---

## 核心特性

1. **三阶段智能体协同流水线**：
   - **阶段 1 · 详细内容策划与提示词工程**（[`gateway/deepseek_compiler.py`](gateway/deepseek_compiler.py)）：优先调用 **Claude (`GLM-5` / Anthropic)** 或 **Codex (`gpt-6-astra`)**，梳理金字塔核心论点、每页结论先行标题（Action Title）、3~5 个并列模块卡片、底部流程闭环条及演讲话术，生成标准 `slide_script.md` 与高密度 `image_gen` 提示词。支持 **「不限页数（AI 按内容逻辑自动决定页数）」** 与固定页数模式。
   - **阶段 2 · 双引擎直接生成**（[`worker/worker_api.py`](worker/worker_api.py)）：
     - **🖼 Codex 直接生成（纯图片 PPT · 推荐）**：将定制好的逐页提示词直接发送给本机已登录的 `codex exec`，调用内置 `image_gen` 逐页绘制 `1672×941` 16:9 咨询风高清幻灯片原图，并实时通过 SSE 推送预览。
     - **🤖 Claude 直接生成**：将 `slide_script.md` 与结构化规格发送给 `claude -p` 直接调用技能生成 `.pptx`。
   - **阶段 3 · 主 Agent 终审验收与交差**：自动核验每页幻灯片分辨率、页数完整性，调用 `images_to_pptx.py` 封装为满版 16:9 `.pptx` 与全屏可交互 `.html` 演示稿，并输出《主 Agent 终审验收报告》。
2. **多源视觉母版与技能生态集成**（[`gateway/template_registry.py`](gateway/template_registry.py)）：
   - 支持 **GordenPPTSkill**（麦肯锡咨询风、领导爱的架构图合辑、科技蓝商务、字节范科技黑、述职报告等）、**用友高端 BG 商务蓝白母版**、**归藏 (`ppt-master`)** 与 **HTML 交互式幻灯片 (`frontend-slides`)**。
3. **防封号安全沙盒 & TCC 算力计费网关**（[`gateway/billing_tcc.py`](gateway/billing_tcc.py)）：
   - 内置单账号串行锁 `Semaphore(1)`、随机拟人间隔与固定住宅代理透传，保护海外个人订阅账号安全。
   - 完整实现 `Try-Confirm-Cancel` 三阶段算力预授权冻结、按实扣费与异常自动退费。

---

## 目录结构

```text
NBPPT/
├── gateway/                  # 国内/主控网关 (:8000)
│   ├── main.py               # FastAPI 网关、SSE 流式编排与静态资源服务
│   ├── deepseek_compiler.py  # 阶段 1：Claude / Codex 详细 PPT 内容规划与 Prompt 编译器
│   ├── template_registry.py  # 智能母版路由与开源 PPT 技能注册中心
│   ├── billing_tcc.py        # TCC 预授权算力计费与多租户钱包
│   ├── mcp_server.py         # 官方 MCP SDK 异步任务接口（供 Claude Desktop / Cursor / Codex 挂载）
│   └── static/index.html     # Web Studio 双主题（深色黑曜石 / 浅色高定纸感）工作台
├── worker/                   # 执行节点 (:8001)
│   ├── worker_api.py         # 阶段 2（Codex/Claude 直出执行）与阶段 3（主 Agent 终审验收）
│   └── agent_skills/         # 内置 PPTX、数据图表与程序化动效视频技能脚本
├── deploy/                   # 海外 VPS 个人账号安全沙盒部署脚本
├── start_platform.sh         # 一键启动脚本
└── requirements.txt          # Python 依赖清单
```

---

## 快速启动

```bash
# 1. 创建虚拟环境并安装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. （可选）拉取外部开源 PPT 母版库
mkdir -p worker/external_ppt_skills
git clone --depth 1 https://github.com/GordenSun/GordenPPTSkill.git worker/external_ppt_skills/GordenPPTSkill

# 3. 启动平台（默认监听 :8000 Web 工作台 与 :8001 执行节点）
./start_platform.sh
```

打开浏览器访问 `http://127.0.0.1:8000` 即可使用。

## 内容优先的视频制作（本地开发版）

新增录音/上传、离线转写、确认文字、Claude 内容与口播、微软自然配音测时、Claude 分镜、受审实景剪辑或横竖屏动画及严格交付检查。网页选择「视频」或「PPT＋视频」即可设置配音开关、音色和同文试听；生成沿用现有网页和 MCP `create_video(execution_mode="claude_cli")`，需当前密钥获准使用 Claude。实景素材与微软配音需显式配置，服务器尚未启用的能力不会自动开放。配置、能力边界及复现实验见 [视频制作说明](docs/VIDEO_AUTHORING.md)。本节不代表已部署到生产环境。

## 研究报告与分享图

新版主页选择“研究报告 ↗”，会自动带入已填写的原文，生成有来源的交互报告及可独立下载的分享图。报告由执行节点隔离生成，共用平台登录、权限、余额、排队和积分账本；报告/复审60积分，分享图40积分，受理冻结、成功结算、失败退款。原文排版及读取下载免费。接口、部署边界与验收见 [研究报告工作台](docs/REPORT_WORKSPACE.md)。
