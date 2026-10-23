# NB PPT 研究报告与分享图

新版主页“开始创作 → 研究报告 ↗”会将已输入的原文完整保存为当前账户草稿，再进入 `/reports`。内容、引文校验、选图、暖纸/铜橙排版及分享图制作复用 `tools/report_studio` 和 `business-visual-storytelling` 技能。

## 执行与积分

材料 → 网关核对登录、权限与请求编号 → 现有账本冻结积分 → 执行节点排队生成 → 网关独立核对原文、报告、网页、图片及交付摘要 → 结算并提供下载。PPT、视频、报告与分享图使用相同账户余额、日尝试额度及排队限制，各任务独立结算。

| 操作 | 冻结与成功扣分 | 失败 |
|---|---:|---|
| 生成研究报告 | 60积分 | 全额退回 |
| 继续复审报告 | 60积分 | 全额退回 |
| 生成分享图 | 40积分 | 全额退回，原报告保留 |
| 原文排版、导入、读取与下载 | 免费 | 不调用模型 |

这是明确的按次服务积分，不是供应商实际账单。报告的 `overseas_cost_usd` 保留 NULL，表示实际费用未知；PPT和视频原有估算及结算规则保持不变。失败尝试仍计入现有每日尝试额度。

浏览器对生成、复审和分享图请求发送 `X-Request-ID`；响应丢失时复用编号，确认受理后查询原任务，避免重复冻结。API/MCP客户端重发也必须复用编号；同编号对应不同材料时拒绝。失败后主动重新生成使用新编号。关闭页面不取消已受理任务；网关关闭或重启按现有账本恢复规则退款，不自动重跑模型。

## 运行与隔离

- 启动既有 `gateway.main:app` 与 `worker.worker_api:app`；网关使用 `OVERSEAS_WORKER_URL` 和 `OVERSEAS_WORKER_SECRET` 连接执行节点，模型不在网关启动。
- 按现有部署共享 `NBPPT_JOBS_ROOT`（默认 `workspace/jobs`），执行节点写入，网关仅需读取。两个物理主机需要挂载同一任务输出目录；仅改变URL不足以传输产物。
- 生产保持 `NBPPT_REQUIRE_ISOLATION=true`。报告模型进程复用 bubblewrap，使用非root执行账号，只挂载本次任务、必要图片及专用模型登录；不暴露网关数据库、其他任务或服务器配置。条件不满足即失败，不能回退到未隔离调用。
- 受保护的草稿和报告历史默认位于 `workspace/data/reports/`，可用 `NBPPT_REPORTS_ROOT` 显式指定。默认路径兼容现有网关 systemd 写入权限。任务输出目录0750、发布文件0640，供共享产物组读取；代码与环境文件维持原有权限。
- 报告、分享图和PPT共用执行节点的模型并发控制，等待时发送心跳。模型调用取消会清理进程组；缺失图片或校验失败不得以演示内容、其他任务图片或旧结果替代。

## 登录、版本与下载

共用 NB PPT 的 HttpOnly 会话或 Bearer请求头，不建立另一套登录。`admin`、`generate` 可创建或生成；`read` 只能查看和下载本账户已有结果。其他账户访问任务、原文、网页和图片均返回404，撤销密钥同时影响会话。

每次生成产生新版本，分享图绑定原报告版本，不修改原报告正文。保存结构和摘要校验；下载网页不包含平台配置或身份凭据，可离线阅读。“分享”表示下载网页或PNG后由使用者分享，不自动公开发布。原PPT/视频历史仍通过原接口读取，报告历史在“我的报告”中读取。

## 接口

| 路径 | 用途 |
|---|---|
| `POST /api/reports/draft` | 保存主页草稿，201返回编辑地址 |
| `POST /api/reports/generate` | 远程生成；`mode=local`仅免费原文排版 |
| `POST /api/reports/continue` | 创建复审新版本 |
| `POST /api/reports/overview` | 创建分享图新版本 |
| `GET /api/reports/health` | 运行配置、当前权限、服务积分及余额 |
| `GET /api/reports/jobs` | 当前账户报告与任务 |
| `GET /api/reports/jobs/{id}` | 状态、积分冻结/扣除和预览地址 |
| `GET /api/reports/jobs/{id}/result` | 完整结构化报告 |
| `GET /api/reports/jobs/{id}/input` | 恢复原文，供失败后重试 |
| `GET /api/reports/jobs/{id}/download` | 下载离线网页 |
| `POST /api/reports/preview` | 校验、保存导入或编辑快照 |
| `GET /api/reports/preview/{id}` | 受保护的交互预览 |
| `GET /api/reports/preview/{id}/overview.png` | 下载绑定该版本的分享图 |
| `POST /api/reports/export` | 校验并导出独立网页 |

生成接口202返回 `{id,status_url}`，通过状态接口轮询。`/mcp` 提供 `generate_research_report`、`get_research_report`、`generate_report_share_image`、`continue_research_report`；写工具支持 `request_id`。这些工具走相同权限、任务与积分检查。

## 验证和发布

```bash
python -m pytest -q
node --test tests/test_studio.cjs
node tools/report_studio/tests/overview_generate.cjs
```

测试覆盖真实路由、任务归属、工作节点交付、积分冻结/结算/退款、重复提交、取消、额度不足、原文和图片版本绑定、篡改拒绝及下载字节；测试中的模型输出被替换，不能据此声称真实内容或美术质量通过。发布还须完成Linux隔离环境检查、从主页真实生成、图面检查和下载复核。发布前记录提交、备份数据库和服务配置、确认无运行中任务；回滚代码与服务，不回滚已发生的账目。详见 `deploy/production/README.md`。

分享图的同一选题两次出图仍未通过时，通用引擎最多回到全文重选一次问题与表达，全部引文、数字及实际图面检查保持生效；供应商错误和超时不会触发该质量重选。重新提交同一报告时，只可复用当前账户、当前报告之前的图片复核缺陷，不跨账户使用反馈，不把缺陷反馈作为新业务事实。
