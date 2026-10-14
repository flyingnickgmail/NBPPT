# NBPPT — 三阶段智能体纯图片 PPT 与动效视频直出平台

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
│   ├── mcp_server.py         # 标准 FastMCP Server（供 Claude Desktop / Cursor / Codex 挂载）
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
