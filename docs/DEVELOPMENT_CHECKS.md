# 开发验证与产品入口验收

## 一次运行全部门禁

准备 Python 3.11+、Node 22+、含 libass 的 FFmpeg/ffprobe 及中文字体。现有 Python 依赖安装 `requirements-dev.txt`，微软适配器测试另装 `requirements-microsoft-voice.txt`。浏览器测试依赖固定在 `tests/browser/package-lock.json`，使用 `npm ci --prefix tests/browser --ignore-scripts` 和 `tests/browser/node_modules/.bin/playwright install chromium` 准备专用浏览器。不要复用日常登录的浏览器资料目录。

在已登记的本任务目录下保存测试和临时文件；例：

```sh
python -B tools/quality_gate.py --output "$HOME/Workspace/codex/2026-10-25-nbppt-workbench-gates"
```

每次生成独立 `run-…/`，包含阶段日志、JUnit 结果、源码清单及摘要和 `gate.json`。pytest 临时根、导入用数据库和浏览器产物均在本次目录内。缺依赖、未知原因的跳过、失败阶段、运行期间源码变动或错误的页面证据均以非零退出码阻断；本命令不会安装软件或启动生产服务。

后端和前端使用现有测试命令。仅白名单中的可选 MeloTTS/Kokoro 或已固定 HTML 运行时测试可以跳过，原因保存在回执中；真实静音媒体、失败退款、重试、下载测试必须执行。

`pytest.ini` 明确收集 `tests` 和 `tools/report_studio/tests`，避免把工作区中的旧备份误当成正式测试；报告工作台的前端检查也包含在统一门禁中。

门禁为长片测试单独锁定测试浏览器版本、二进制摘要和中文字体摘要；不修改生产配置。Claude 测试夹具使用自己的虚拟登录目录，既不读取本机凭据，也不放宽生产目录隔离规则。

## 真实工作台测试的边界

`tools/workbench_acceptance.mjs` 启动 `tools/workbench_fixture.py`，在随机环回端口访问真实 `/` 页面，通过正式登录、创建、轮询、重试及产物接口操作独立测试账户。没有模拟浏览器页面、fetch 响应或播放成功状态。只有规划步骤使用固定测试数据，第一次规划故意失败；后续由真实 Worker、FFmpeg、字幕、交付校验和钱包完成。

浏览器验证两种行为：静态音色试听实际播放；选择女声后关闭配音，生成确实为静音。它不请求在线语音服务，不能代替音色质量或联网可用性验收。模型、素材搜索和生产账户均不参与此门禁。

`workbench/receipt.json` 绑定源码摘要、根页面、失败/重试任务、请求参数、下载字节摘要及隔离断言；`workbench.png` 为实际页面截图。可分享的回执不含测试登录密钥，数据库及下载影片留在私有本地任务目录，不作为公开 CI 附件。

## 自动执行与审阅责任

`.github/workflows/checks.yml` 是唯一自动测试入口，在拉取请求、main 推送及手动运行时，通过 `tools/check.sh --deployment` 调用同一门禁；它保留已有独立低权限CI账号、进程预算与真实TCP/TLS/nginx报告交付验收，同时增加能力文档和真实浏览器工作台。没有并行的第二套质量工作流。工作流修改尚未推送时，本地 `gate.json` 才是本轮已运行证据；不能用之前main的CI成功替代本轮候选。

提交前检查差异是否含全部新增依赖、技能和资源。审阅者核对真实产品入口、来源与能力边界，人工判断内容、故事和视觉效果；自动文件通过不能改写成人工认可。当前能力唯一总览是 [VIDEO_CAPABILITIES.md](VIDEO_CAPABILITIES.md)，历史文档只指向该页。

Ubuntu CI 为本次固定浏览器的精确绝对路径加载允许用户命名空间的 AppArmor 规则；不关闭系统范围的限制，也不使用 `--no-sandbox`。生产启用 HTML 长片前须单独验证同类浏览器沙箱能力，CI 规则不会自动修改服务器。

Linux 的 Chromium IPC 套接字路径最多108字节，深层任务目录无法容纳其随机后缀。管理员须配置 `NBPPT_HTML_SOCKET_ROOT` 为不超过40字节、渲染账号所有的0700规范目录；CI使用 `/home/nbppt-ci/html-sockets`，生产可使用 `/var/lib/nbppt-worker/html-sockets`。每次调用创建独立IPC目录，只清理自己已空的目录，剩余文件保留；浏览器资料、缓存、日志和媒体仍留在本任务目录，不回退到 `/tmp` 或公共目录。缺配置、公共目录和符号链接均在浏览器启动前拒绝。

最终黑帧扫描显式解码为 RGB 像素，再检查主画面亮度，避免灰度转换保留有限视频范围时把黑色亮度16误当成正常画面；有限/全范围的黑帧和冻结负例都须拒绝。最长600秒的扫描像素缓冲约224MB，仍须在生产资源上限内验收。
