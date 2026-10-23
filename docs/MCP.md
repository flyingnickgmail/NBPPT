# NBPPT 异步 MCP

完整原文和客户风格 → MCP 提交独立任务 → Codex 按技能规划和生成 → 文件验收、结算 → 客户端下载 PPTX/HTML/PNG 或中文配音 MP4/海报/VTT。
客户模板约束品牌风格，不固定每页布局；文件通过不表示内容事实或图片中文字已通过独立终审。

## 接口

使用官方 `mcp==2.3.0` SDK 的 Streamable HTTP，入口 `/mcp`，支持传统客户端 initialize/initialized/tools 协议。每次请求必须携带 `Authorization: Bearer <私有密钥>`；公开演示密钥已停用。公网必须通过 HTTPS；本机可使用仅监听回环地址的 HTTP。

| 工具 | 作用 |
| --- | --- |
| `list_templates` | 列出品牌风格参考，不暴露主机文件路径 |
| `create_presentation` | `source` 完整原文、`request_id` 幂等编号、`template_id`、`slide_count`、可选 `execution_mode=auto/codex_cli/claude_cli/claude_codex`；Claude 须由服务端启用并绑定持有人，默认仍为 Codex；立即返回任务编号 |
| `create_video` | `source`、`request_id`、`template_id`、`duration_seconds`（6–60）、`aspect_ratio`（16:9或9:16）；中文讲解MP4、旁白和字幕 |
| `retry_job` | 对自己失败且已退款的 PPT/视频，以新的 `request_id` 重试；不会重做组合任务中另一项 |
| `get_job_status` | 查询当前用户的进度与结算，运行中建议间隔30秒 |
| `get_job_artifacts` | 完成后重新检查摘要，返回文件列表、下载路径 |
| `generate_research_report` | `content`原文、`title`、`request_id`；远程报告60积分，`mode=local`免费原文排版 |
| `get_research_report` | 省略编号列出报告；传报告编号查询状态及预览，完成后用返回的`billing_job_id`调用`get_job_artifacts`下载 |
| `generate_report_share_image` | 报告编号与`request_id`；分享图40积分，创建新版本，失败退款 |
| `continue_research_report` | 报告编号与`request_id`；复审60积分，创建新版本，失败退款 |

页数为0时自动决定，明确页数范围1–60。原文最多10万字。编号8–80位英文字母、数字、下划线或短横线。同一用户、同一编号、相同参数只创建一次、冻结一次；不同参数复用编号报错。失败后同编号仍返回原失败记录，只有明确再次生成时使用新编号。

状态中的 `credits_frozen` 保留最初预冻结金额，供历史记录和旧客户端使用；当前仍占用的金额看 `credits_held`，已退金额看 `credits_refunded`，实际结算看 `credits_charged`。失败退款后的当前占用为0，原预冻结字段不会被清零。

提交接口断开不取消生成。服务正常停止或重启时，中断任务失败并退款；不自动重放生成，不宣称跨重启续跑。后台任务由单个网关进程管理，SQLite 数据库锁拒绝第二个网关启动。Web 的旧流式入口仍在断开时取消，两者行为不同。

旧三个同步 MCP 工具已由上表替代，客户端需刷新工具列表。这是接口变更，不提供旧工具名称兼容。

## ZCode / 其他桌面客户端

更新连接配置、密钥或工具参数后，在新会话核对工具定义。ZCode 历史会话可能缓存旧连接和旧参数，即使设置页已刷新也未必更新；本次实测旧适配器不包含 `execution_mode`，会丢弃所选引擎。验收必须回读 `get_job_status` 的 `request.execution_mode` 与实际进度消息，确认指定的 Claude 未变为默认 Codex。Claude 个人登录仅向绑定持有人开放，使用该持有人的普通生成密钥，不下发管理员密钥。

本地适配器使用 stdio（标准输入输出）连接，代理到认证 HTTP MCP。密钥放在权限0600的独立配置文件中，不放在提示词或下载网址里。适配器会认证下载并验证每个文件的 SHA256 摘要，然后返回本机绝对路径。

私有配置文件示例（不要提交真实密钥）：

```json
{
  "url": "http://127.0.0.1:18780/mcp",
  "api_key": "替换为独立普通用户的私有密钥",
  "download_dir": "/absolute/path/nbppt-deliveries"
}
```

```bash
chmod 600 /absolute/path/nbppt-client.json
python /absolute/path/NBPPT/clients/nbppt_mcp.py --config /absolute/path/nbppt-client.json
```

在客户端配置上述 Python 绝对路径、脚本绝对路径和 `--config` 参数；适配器拒绝公网明文 HTTP，密钥不会进入工具返回值。使用独立普通账户，勿将管理员凭据配置给生成客户端。服务账户管理当前仍需要管理员运维，尚无自助开户界面。

本地服务启动（先按照 `.env.example` 配置独立 worker 密钥与地址）：

```bash
python -m uvicorn gateway.main:app --host 127.0.0.1 --port 18780
python -m uvicorn worker.worker_api:app --host 127.0.0.1 --port 18781
```

两者需要共享 `workspace/jobs` 文件系统。网关 `.env` 中 `OVERSEAS_WORKER_URL` 对应18781。仅本机浏览器测试时设置 `NBPPT_COOKIE_SECURE=false`，公网必须保持 true 并配置准确 HTTPS `NBPPT_PUBLIC_ORIGIN`。本次本地进程不是开机自启服务；停止后客户端无法提交/查询，已有下载文件仍可打开。

## 验证与边界

`execution_mode=claude_codex` 使用 Claude 撰写中文核心主张、全篇逻辑、逐页论证、画面文字、讲稿及衔接；验证原文引文、连续页码和内容完整后，再交给 Codex 按 source-image-deck 技能逐页生成图片。客户模板只约束视觉风格。Codex 可设计版式，不能改写或省略策划内容。

组合模式使用一个任务和一次冻结，任一步失败都不交付、不结算；重试保留原文、风格和组合模式，重新执行两阶段。进度依次显示 `outlining`（内容策划）、`illustrating`（绘图）和 `checking`（文件检查）。成功交付图片版 PPTX、网页演示、图片及 `content_outline.md` / `content_plan.json`；文字策划也写入 PPT 备注。文字稿通过同一所有权与摘要检查才能下载，客户端适配器会同时保存它们。

Claude 仍只允许绑定的个人持有人使用，复用唯一凭据、跨进程账号队列与限流熔断；临近令牌到期时，在同一账号锁内由官方客户端执行固定、无工具且最多0.05美元估算预算的登录维护请求，不接触任务原文，维护成本计入原任务预算与用量。刷新失败会暂停调用，须人工处理后恢复；不向其他用户开放个人订阅，也不会失败后静默换引擎。文字结构检查和逐字交接不证明论证深度或生成图片中的中文正确，仍需内容与视觉验收。图片版 PPT 的可见文字不可单独编辑；原生可编辑版本继续使用 `claude_cli`。

测试覆盖正式 SDK 握手和工具调用、提交后断开、并发重试仅一次冻结、越权读取、失败退款、交付文件损坏、下载摘要和路径边界。真实试跑需另外检查全部页面内容与布局。

- 生产执行器必须启用非 root Linux/bubblewrap 隔离，只暴露本任务及指定技能；不能把未启用隔离的本地调试运行方式用于公网。
- 当前账单按页面或视频时长估算，非模型供应商实际计费。已有单机队列上限、用户并发和日冻结额度，不支持多实例调度。
- 下载 HTML 已嵌入图片，网页服务增加隔离策略；历史无 manifest 的产物不会自动公开，需独立验证迁移。
- 这份代码与本地验收不表示线上部署完成；公网 HTTPS、权限切换、旧链接迁移需作为明确发布工作验证。

## 2026-10-16 本机验收记录

已通过 Computer Use 操作 ZCode 的 `nbppt-local` 连接，实际调用四个工具。第一次任务在 CLI 配置解析阶段失败，费用全退；修正 MCP 名称参数的字面引号后，第二次 `ppt_063884cae8` 完成5页生成和下载。五种版式为概览、数据对比、角色泳道、时间线、验收清单；逐页目视检查了测试样本12/7/5和计划/未知边界。7份下载文件摘要全部匹配，重新打开 PPTX 为5页。成功任务结算60平台算力点，失败任务0点，冻结余额归零；这不是外部模型实际账单。

macOS：70项通过。Linux/Python3.12：69项通过，1项真实视频检查因容器未安装ffprobe而跳过。本轮仅本机接入，线上服务未部署、未重启。


生产发布与隔离配置见 [deploy/production/README.md](../deploy/production/README.md)。公网仅允许 HTTPS；普通生成密钥不能访问管理接口，支持撤销。

视频体系、技能许可与试验记录见 [VIDEO_PRODUCTION.md](VIDEO_PRODUCTION.md)。`create_video` 固定要求中文配音，未配置时失败退款。Claude 规划接口保留但未开放生产；不得向客户声称已由 Claude 生成。
