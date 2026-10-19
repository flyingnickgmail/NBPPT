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

保持 Codex 为默认引擎。安装官方 Claude Code 至 `/usr`、`librsvg2-bin` 及 `fonts-noto-cjk`，为 `nbppt-worker` 配置独立官方 OAuth 登录：`/var/lib/nbppt-worker/.claude/.credentials.json`（0600），最小账号元信息位于 `.claude.json`；不要复制个人 hooks、plugins 或 MCP 配置。以 worker 身份和实际 systemd 限制验证登录、SVG 渲染和中文字体后，再在两个环境文件中设置 `NBPPT_CLAUDE_ENABLED=true`，worker 另加 `CLAUDE_BIN=/usr/bin/claude`、`NBPPT_CLAUDE_MODEL=sonnet`。保持 `NBPPT_REQUIRE_ISOLATION=true`。

页面、REST 和 MCP `create_presentation` 可选择 `execution_mode=claude_cli`。Claude 使用英文任务指令读取原文、规划并绘制独立 SVG 页面，调用可信渲染器生成 PNG，再逐页自检；PPTX/HTML 仍由现有严格文件检查与封装器处理。未启用、登录失效、预算耗尽或缺文件会失败退款，不切回其他引擎。当前 PPTX 为整页图片，文字不可直接编辑；模型自检不等于独立内容审核。CLI 的美元用量为估算，不代表 Pro 订阅实际扣款。该开关不开放 Claude 视频路径。

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
