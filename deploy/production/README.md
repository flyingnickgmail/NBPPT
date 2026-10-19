# NBPPT 单机生产部署

适用 Ubuntu 24.04；本机网关 + 单账号执行节点。开放隔离 Codex PPT 与原文驱动中文讲解视频；两种产物独立任务、冻结和结算。

## 发布前

1. 在 macOS 和 Linux Python 3.12 执行 `python -m pytest -q`；检查 Git 差异和密钥泄露。确认数据库无 RUNNING 任务。
2. 记录旧提交；用 SQLite backup API 备份 `workspace/data/platform.db`，同时备份 systemd 单元、环境文件和 nginx 配置到 root 专属目录。禁止在有任务运行时直接覆盖数据库。
3. 安装 nginx、bubblewrap、apparmor-utils、ffmpeg、fonts-noto-cjk、Python venv、Node/Codex CLI。代码和虚拟环境归 root，服务账号不得写代码。
4. 建立 `nbppt-worker`、`nbppt-gateway` 系统用户，共享 `nbppt-artifacts` 组；独立 HOME 位于 `/var/lib/`，权限 0700。执行账号单独配置 Codex 登录（auth.json 0600）。只复制经审查的技能文件。
5. `workspace/jobs` 归 worker:nbppt-artifacts、0750；产物组只读。`workspace/data` 归 gateway、0700，数据库 0600。两者不要互换权限。

## 配置与隔离

安装本目录 systemd 单元。环境文件 `/etc/nbppt/{gateway,worker}.env` 仅 root 可读（0600），systemd 加载后服务进程不可访问文件本身。

公共参数：`NBPPT_REQUIRE_ISOLATION=true`。开启时不加载仓库 `.env`。
网关：`NBPPT_PUBLIC_ORIGIN=https://38.97.249.8`、`NBPPT_COOKIE_SECURE=true`、`OVERSEAS_WORKER_URL=http://127.0.0.1:8001`、随机 `OVERSEAS_WORKER_SECRET`、随机 `NBPPT_ADMIN_API_KEY`（至少32字符）。
执行节点：同一 `OVERSEAS_WORKER_SECRET`、`CODEX_BIN=/usr/bin/codex`。
默认全局并发排队上限8、每账号2、日冻结累计1200点；可用 `NBPPT_MAX_RUNNING`、`NBPPT_MAX_USER_RUNNING`、`NBPPT_DAILY_CREDITS` 收紧。失败尝试也计入日额度，防止无限失败消耗模型。

Ubuntu 24.04 安装 `nbppt-bwrap.apparmor` 至 `/etc/apparmor.d/nbppt-bwrap` 并用 `apparmor_parser -r` 加载。只允许 bwrap 创建用户命名空间，不关闭系统全局保护。必须以服务账号及 systemd 安全参数实测隔离：仅本任务可写，看不到其他任务、数据库、root HOME、服务器配置；缺失隔离条件必须失败。

执行进程仍需要读取它自己的 Codex OAuth 登录并联网生成图片。这是单账号服务，不宣称能防账号封禁或隔离同一账号的供应商风险；隔离不是网络出口白名单。任务原文不是执行指令。公共发布不支持旧 Claude/即梦模板视频路径。新视频使用 skill-video-v1：Codex 仅输出受限分镜 JSON，可信 Pillow/FFmpeg 渲染，MeloTTS 离线中文配音，可选经摘要校验的 Kokoro 中文男女声。Claude 规划适配接口保留但明确拒绝未验证的隔离执行，不静默回退。

## HTTPS 与更新

### 可选：官方 Claude Code 生成 PPT

保持 Codex 为默认引擎。Claude 路径采用英文任务指令，只交给模型完整原文、页数和客户显式选择的品牌参考。自动风格不强制套用 ABU9 或统一版式，不预先规定逐页内容和 SVG 骨架。模型自行构思并输出原生 `draft/presentation.pptx`。可信宿主重新打开实际 PPTX，用 LibreOffice/Poppler 离线渲染每页，生成与 PPTX 相同的预览和网页；不执行模型生成的 HTML/JS，不用模板或其他模型兜底。原生文字和形状保持可编辑，图片本身不能变成可编辑对象。

**个人订阅仅开放给绑定持有人。** 网关和 worker 均须设置 `NBPPT_CLAUDE_ENABLED=true`、`NBPPT_CLAUDE_OWNER_USER_ID=<真实用户ID>`；其他用户和管理员都不能借用其订阅。CLI 估算美元用量不代表订阅实际扣款或剩余额度。面向其他客户的商业服务需要另外确认供应商条款和适用认证，不可通过共享 Pro/Max 凭据开放。参考 [官方使用与合规说明](https://code.claude.com/docs/en/legal-and-compliance)。本路径不开放 Claude 视频。

**发布前必须另行完成的运行时验收：** 安装官方 Claude Code 至 `/usr`、`libreoffice-impress`、`poppler-utils`、`fontconfig`、`fonts-noto-cjk`、`bubblewrap`、`socat`。以实际 systemd 服务账号验证受限登录、嵌套 Bash 沙箱、中文字体和一次真实 PPTX→PDF→PNG；依赖缺失、隔离不可用、登录失效均失败关闭。worker 配置 `CLAUDE_BIN=/usr/bin/claude`、`NBPPT_CLAUDE_MODEL=sonnet`、`NBPPT_CLAUDE_HOME=/var/lib/nbppt-worker`、`NBPPT_ACCOUNT_STATE_DIR=/var/lib/nbppt-worker/account-state`（0700）。`NBPPT_PPT_PYTHON=/opt/NBPPT/.venv/bin/python`，可显式指定 `NBPPT_SOFFICE`、`NBPPT_PDFTOPPM`。保持 `NBPPT_REQUIRE_ISOLATION=true`。任务目录必须在登录 HOME 外；生产默认 `/opt/NBPPT/workspace/jobs` 满足要求，macOS 本地可在两端设置同一私有 `NBPPT_JOBS_ROOT=/tmp/nbppt-jobs`。写权限拒绝无法被嵌套允许规则撤销，不可为了在 HOME 内生成而取消凭据保护。`--restricted` 不读取用户转发配置；预检和实际调用采用同一设置边界，不以普通 `auth status` 代替验证。

**同账号串行与熔断：** 登录目录和共享状态目录都必须显式配置，不回退到各调用者自己的 HOME。状态目录归唯一登录所属用户；root 维护创建的锁和状态文件保留该用户所有权。 账号元信息的稳定 UUID 经哈希后标识账户，所有受控 Web/MCP/诊断调用在同一状态目录使用 POSIX 文件锁；进程退出自动释放，排队者拿锁后再次检查熔断。单进程信号量继续限制内存密集工作。429 立即终止当前 CLI 与子进程并保存冷却状态，冷却中在冻结算力前拒绝新的提交/重试；401/403、停用、账单异常或未知额度重置需要持有人处理后手动恢复。CLI 自身最多两次重试；不自动充值、换号、换出口或恢复永久暂停。持久状态损坏也拒绝调用。供应商额度是跨设备的，本机锁不能控制未通过受控入口启动的 CLI、其他设备或其他服务；不得承诺“防封号”。

组合模式 `claude_codex` 先由 Claude 输出经过结构与原文引用检查的内容策划，再交给 Codex 生成图片并封装 PPT；独立的 `claude_cli` 原生可编辑模式继续保留。文字稿和结构化策划进入同一交付清单和所有权校验，完整讲稿写入 PPT 备注。

**独立账户与密钥权限：** 管理员 `POST /api/wallet/keys`，请求 `{"name":"客户名称","daily_credit_limit":240,"allow_claude":false}`，现在总是创建独立账户（余额0、无历史、generate权限），不再挂在管理员账户下；密钥仅在创建响应中返回，私下保存。`GET /api/wallet/keys` 返回管理员管理清单，只有末四位和不可逆 `key_id`，不返回原始密钥。管理员可 `PATCH /api/wallet/keys/{key_id}`，请求 `{"allow_claude":false}` 关闭 Claude；设为 `true` 还必须满足现有个人持有人绑定，不能向无适用授权的独立账户共享 Pro/Max 登录。初次数据库迁移只保留已经绑定持有人现有密钥的权限，其余默认关闭；后续重启不会重新开启已关闭的权限。网页能力列表、提供方状态、MCP、异步与旧流式提交、重试均检查权限，冻结算力的同一事务再次检查，已受理任务不追溯取消。撤销独立账户密钥会同时撤销其网页会话。旧的同账户密钥仍共享该账户历史和余额，不自动拆分已有任务；新隔离交付必须使用新建独立账户。没有自动充值或余额转移，原有账户账目保持原状。

到期登录维护在共享账号锁内执行：仅临近 OAuth 到期时，使用官方客户端、唯一凭据、受限设置和空工具列表发送固定确认指令，不将业务原文交给宿主维护进程。最多0.05美元估算预算从原任务预算中扣除；维护失败暂停后续调用，不自行登录、复制令牌或换账号。任务内容继续在原来的隔离沙箱中生成。已观察到隔离任务在令牌过期时刷新失败、宿主官方调用成功；这项维护规避该故障，不将其未经证实地归因为并发，也不承诺供应商授权永远有效。

离线渲染沙箱仅额外只读挂载 Ubuntu 的 `/etc/libreoffice` 公共配置（`/usr` 内的 registry 指向该目录）；保持断网，且不挂载任何登录凭据。缺少该配置会导致 LibreOffice 启动失败，须通过实际 PPTX 转换验收，不能只检查二进制是否存在。

**凭据整理（维护窗口显式执行，不随服务启动自动迁移）：** 使用唯一 `NBPPT_CLAUDE_HOME` 的官方登录，凭据0600、父目录0700。隔离任务仅绑定该目录供官方客户端原子刷新，不复制令牌。先确认无在途任务和无未受控 Claude 进程，再由持有人运行：

```bash
export NBPPT_CLAUDE_HOME=/var/lib/nbppt-worker
export NBPPT_ACCOUNT_STATE_DIR=/var/lib/nbppt-worker/account-state
install -d -m 700 -o nbppt-worker -g nbppt-artifacts "$NBPPT_ACCOUNT_STATE_DIR"
python -m tools.claude_account audit --legacy-home /root
# 审阅路径后执行；将重复文件移为非活动 .retired-*，不复制、不删除唯一登录。
python -m tools.claude_account retire-duplicates --legacy-home /root
python -m tools.claude_account status
# 仅在已处理授权/额度问题后人工恢复；运行中不能重置。
python -m tools.claude_account reset
# 维护诊断也使用同一账号锁和熔断；不直接运行未受控的 claude -p。
runuser -u nbppt-worker -- env NBPPT_CLAUDE_HOME="$NBPPT_CLAUDE_HOME" NBPPT_ACCOUNT_STATE_DIR="$NBPPT_ACCOUNT_STATE_DIR" /opt/NBPPT/.venv/bin/python -m tools.claude_account exec --prompt-file /private/check.txt
```

审核会发现相同凭据内容，以及账号元信息相同但刷新令牌已经分叉的副本；没有元信息且内容不同的历史副本无法可靠归属，须人工确认。非活动备份仍属敏感文件，保持0600并由运维管理；本工具不撤销远端会话。状态/日志不保存原始供应商报错或令牌。模型详细执行日志保留在私有任务目录，不对外发布。

所有失败仍走原有退款；成功必须通过独立文件、页数、图片、压缩包、宏/外部资源与摘要校验后结算。真实内容、文字排版与美感仍需逐页人工审阅，文件检查不能标记事实审核完成。

回退：两个环境文件设 `NBPPT_CLAUDE_ENABLED=false` 并在无运行中任务时重启 worker/gateway，原 Codex 默认路径保持可用。保留失败任务及账目，不回滚数据库。

Certbot >=5.4 支持 IP 证书。使用 webroot + shortlived profile 为服务器 IP 签发；80端口只用于 ACME 与跳转，443代理127.0.0.1:8000。安装 nginx.conf 时按实际 IP 和证书路径调整。
安装续期 service/timer，`systemctl enable --now nbppt-cert-renew.timer`；执行 `certbot renew --dry-run`，检查证书和 timer 的下次运行时间。IP 证书有效期很短，需持续监测 timer 失败和到期时间。

从经测试的合并提交 `git pull --ff-only origin main`，安装 requirements，校验文件权限，`systemctl daemon-reload`，重启 worker、gateway，检查健康状态后 `nginx -t` 并 reload。防火墙只保留 SSH、已有无关服务及80/443；移除8000/8001公网规则，两服务仅绑定回环。不要暴露 worker。

## 验证与回滚

检查：TLS证书默认校验成功；未登录 API/MCP/产物401；生成密钥访问管理接口403；跨账号任务不可见；public demo失效；8000/8001公网不可达。通过真实桌面客户端提交、轮询、下载；核验页数、PNG尺寸、摘要、PPT/HTML一致、无重复页，人工逐页检查内容。核对仅结算一次、冻结余额归零。重启恢复和取消退款由自动测试覆盖；生产重启须无在途业务任务。

失败时先停止新任务，保存失败日志与数据库；停止服务后切回记录的旧提交及备份配置。数据库存在新任务/流水时不得直接恢复旧备份，否则丢失交易，需修复前进或人工核对迁移。旧版本若不满足安全要求，保持入口关闭，不能为了恢复可用性重新开放无认证端口。

客户端使用普通 generate 密钥；禁止下发管理员密钥。管理员创建的客户端密钥不会继承管理权限，管理员可经 `/api/wallet/keys/revoke` 按 key_id 撤销。不同客户必须使用不同用户账号，密钥本身不是租户边界。同一用户的多个密钥共享任务和余额。

文件验收 PASSED 仅表示文件、页数、尺寸、来源引用及布局规则通过；`content_status=NOT_REVIEWED` 表示没有独立事实/图片文字审查。不得把模型自检声明当人工验收。

## 视频运行时与发布门槛

显式运行 `bash deploy/production/install-video-runtime.sh /opt/nbppt-video-runtime`，固定模型摘要与 sherpa-onnx 版本。独立目录归 root，服务用户仅可读取；保留模型自带 MIT LICENSE。将 `NBPPT_TTS_PYTHON=/opt/nbppt-video-runtime/venv/bin/python`、`NBPPT_TTS_MODEL_DIR=/opt/nbppt-video-runtime/vits-melo-tts-zh_en` 加入 worker 环境文件。禁止客户控制这些路径。可选音色由 `install-kokoro-model.sh` 安装，worker 配置 `NBPPT_KOKORO_MODEL_DIR`；候选验证通过后网关才启用 `NBPPT_KOKORO_ENABLED=true`。服务器 FFmpeg 必须带 subtitles/libass，Noto Sans CJK SC 字体必须可读取。

公开视频默认开启配音，可显式关闭；静音字幕使用同一份简短讲解稿。开启配音时，模型缺失、旁白过长、损坏 MP4、字幕不匹配均失败退款，不返回静音替代品。画面为 720p/24fps H.264，AAC 中文旁白，6–60 秒，16:9 或 9:16。每场旁白最长不超过场景时间，最多 1.2 倍语速，禁止截断。全阶段共用单任务执行信号量，适配 2GB VPS；网页双轨进度不意味着两套模型同时执行。

先在独立候选目录/数据库和回环端口运行 Linux 测试及真实 Codex→配音→MP4 流；检查逐场字幕、海报、全帧解码与实际预览、Range 请求、越权拒绝、失败退款/新任务重试。无在途业务任务再更新代码、重启，生产复测同一交付链。第三方 Remotion 技能仅隔离评估，未确认商业许可与质量前不安装到生产 worker。
