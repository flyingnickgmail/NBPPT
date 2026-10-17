# 中文汇报／产品讲解视频制作体系

## 输入到交付

完整原文 + 客户品牌模板 + 6–60 秒 + 横/竖画幅 → 隔离 Codex 读取 `source-motion-video` 技能，仅写严格分镜 JSON → 网关和 worker 分别核验原文引用、数字、重复内容、时长与版式 → 可信 Pillow/FFmpeg 渲染 → 离线 MeloTTS 中文配音 → 按旁白时长生成 VTT → H.264/AAC MP4、海报和字幕验收 → 原子发布后结算。

PPT 和视频分别有 job_id。网页“PPT＋视频”创建两个独立任务，不用一个大任务掩盖部分失败；每项单独冻结、完成、退款和重试。已完成的另一项保留。组合冻结总额为 60＋80 点，重试只冻结失败项。接口不接受 legacy composite 一体生成作为新版流程。

范围是**动态图文讲解**，不冒充电影级文生视频、真人数字人或产品录屏。模板提供配色，场景根据内容选标题、对比或流程；横竖版分别排版，不以一张模板复制全片。无原文证据的收益、数字和产品画面不得补造。引用存在不等于事实审核，交付 `content_status=NOT_REVIEWED`，仍需人核对论断、专有名词读音。

## 生产组件和扩展点

- `gateway/video_contract.py`：纯数据契约，两侧复核；`gateway/mcp_server.py`：异步任务、权限、独立结算与重试。
- `worker/video_generation.py`：隔离规划、单任务资源限额、可信渲染与配音调用；`worker/video_renderer.py`：受控版式、像素容量与 MP4 编码。
- `worker/video_speech.py`：固定离线模型，最长 1.2 倍语速；旁白装不下就失败，不截断，也不交付静音替代品。
- `gateway/delivery.py`：全帧解码、时长、720p/24fps、AAC、海报尺寸、逐场字幕匹配及不可变文件摘要；没有文件不能完成/结算。
- MCP（模型工具协议）新增 `create_video`、`retry_job`，沿用自己任务的 `get_job_status`、`get_job_artifacts` 与相同鉴权下载。
- **Claude 接口保留**：内部 `planner_provider=claude_cli` 与 Codex 使用同一分镜 schema。当前因其独立登录隔离未验收，明确拒绝，不假称可用、不静默转用 Codex。未来接入只替换规划器；后续渲染、配音、文件验收、计费仍共享。公网 capability 如实返回 `claude_cli: false`。

运行时安装/环境变量及候选发布步骤见 [生产部署](../deploy/production/README.md)。生产不执行客户提供的渲染代码、第三方安装脚本或文件路径；模型和渲染代码只读归 root。2GB VPS 上视频全阶段与现有账号信号量串行，双轨进度不表示模型并发。

## 技能筛选与实际试用（2026-10-18）

这是有版本和实验记录的首批筛选，不声称覆盖中文世界全部技能。安装范围是本机独立试验目录 `~/.codex/visualizations/nbppt-video-trials/`，没有把第三方脚本放进线上执行链。

| 技能包 | 固定提交 | 实验与纳入方式 |
| --- | --- | --- |
| [EVZheng remotion-video](https://github.com/EVZheng-Lab/remotion-video) | `a43aef13af8d04b905c387ce16444c6fc3396589` | 已安装依赖，剥离实验入口中的第三方 demo，引擎渲染 12 秒中文标题＋分步动画；先检查单帧再渲染。适合字幕时间轴到画面，**不自带配音**。未纳入生产。 |
| [hollandcut](https://github.com/heloraai/hollandcut) | `10848b345efc1741baec63d07cdef9363d1e5ba8` | 已安装，合成测试素材跑过转写、剪辑、校对、分层、字幕、lite/pro 画面试验。输入是自制素材，不代表真人实拍验收。中文转写多处错词；其 QA 报重复帧仍继续交付，不能直接继承验收结论。 |
| [Remotion 官方技能](https://github.com/remotion-dev/skills) | `1441a11e95db35443bd76bb318386c0d3ca00053` | 已安装技能包，采用 remotion-render 的单帧／成片验证方法辅助上述试验；它是开发指导，不是另一种生成模型，不能把相同引擎试验计成独立模型效果。 |
| [lianyun-video-skill](https://github.com/larry-xue/lianyun-video-skill) | `6ef6aab6fdecb6f9a49899c2449ab9193e471783` | CC BY-NC 4.0，排除商用安装；不含 TTS、字幕、音画对齐。未运行。 |
| [jc-remotion-skills](https://github.com/jincheng2026/jc-remotion-skills) | `a20c4ced9c4885240df4e9fce1a58b59acbd09a3` | CC BY-NC 4.0，排除商用安装；需另获授权再评估。未运行。 |

两款中文候选虽然自身 MIT，但都依赖 Remotion 的适用许可；EVZheng 还含第三方模板来源问题。当前仅做非商用评估，未把这些依赖上线。生产采用自有受限渲染器，未购买或默认接受付费服务。Remotion 许可依据：[官方许可](https://github.com/remotion-dev/remotion/blob/main/packages/core/LICENSE.md)。

## 从试用纳入的制作规则

1. 一场讲一个意思，流程/对比使用对应版式；品牌色一致不等于布局重复。
2. 先校验分镜和文字容量，再编码；时间轴由场景和旁白的实际时长闭合。
3. 生成型视频用已校对的旁白稿制作字幕。ASR（语音转写）只辅助检查，不反向覆盖原文。
4. 字幕、音频、文件验证必须由本平台控制，第三方“完成”或自检日志不代表可交付。
5. 接入新的画面或配音供应商时，必须有明确输入输出、原文约束、权限隔离、成本、取消、错误及真实样片，不能只安装 SKILL.md 就列为生产能力。

实验文件：`evz-trial/video.mp4`；`holland-delivery/`；MeloTTS 单独样音 `melo-test.wav`。语音模型官方来源：[sherpa-onnx 中英文模型](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html)，模型包包含 MyShell.ai MIT LICENSE，安装脚本锁定摘要。

## 本轮实测记录

- macOS 全套 128 项 Python 测试通过；Linux 126 项完整测试及随后新增的 2 项竖屏回归通过，前端 12 项交互测试通过；包括真实离线配音、10 场景编码、横竖版容量、权限、无产物拒绝结算及中断清理。
- Linux 隔离候选服务真实提交“2 页 PPT＋30 秒视频”：PPT `ppt_60b51ddfa2` 成功；视频首轮编码失败退款，修复后网页重试 `video_30e19670e0` 成功。PPT 仅结算一次 48 点，视频成功一次 56 点，失败不扣费，冻结余额归零。
- 实验暴露并修复：FFmpeg 自动线程超过受限运行环境；终态先于资源释放导致重试排队。现在限制解码和滤镜线程，并先清理再发送终态；回归测试要求收到错误时即可重新取得执行锁。竖屏标题改按宽度约束字号，三项标签纵向排列，保留完整文字。
- 浏览器真实播放 1280×720、30 秒带 AAC 配音视频，拖动到约 23 秒仍可解码；MP4 Range 返回 206，未登录返回 401，其他用户访问任务、清单与视频均返回 404。下载通过逐文件 SHA-256 核验。
- 以上为工程及合成内容验收；不是独立事实审核、专业配音质量评价或商业效果证明。
- 最终竖屏真实重试 `video_f31104c75f` 成功：720×1280、15 秒、中文配音，浏览器播放和鉴权下载通过。两个失败分镜的全部场景另行重渲染通过，新增标题与三标签回归覆盖。
