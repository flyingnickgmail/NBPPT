# P2 已审产品与品牌素材

本地接入已实现；实际客户素材是否可用，要逐个文件核查。本轮发现的CRM工程图片、车型海报和标志仅是候选，未自动加入可用素材库。文件名、工程中的引用、普通“已审核”文字、公共素材许可链接，都不能代替本片所需的权属和审批记录。

## 受信输入边界

沿用 `exec_pitch`（高管汇报长片模式）的账户内容包编号；HTTP（网页接口）、MCP（工具接口）和真实网页表单都不接收服务器文件路径或审批布尔值。可信操作者在网关与Worker（生成进程）配置同一只读 `NBPPT_PRODUCT_VISUAL_ROOT`。目录由操作者管理，不能交给规划器、客户上传进程或生成任务写入。

本地目录是审批记录的信任来源。系统检查记录绑定、有效期、文件摘要及媒体格式，**不声称能鉴定伪造的人工签名或自动判定版权归属**。操作者必须先核实真实授权和审批来源，再登记原件。没有批准证据就保留缺失，不使用测试工具代造。

能力接口的 `configured` 只说明目录已配置，不表示当前账户或客户已有任何获准素材；逐项可用性仍由真实内容包及审批证据决定。

目录结构：

```text
NBPPT_PRODUCT_VISUAL_ROOT/
  <sha256(user_id)>/<manifest_id>/
    manifest.json
    media/<asset_sha256>.png|jpg|mp4
    evidence/<approval_sha256>.json
    evidence/<rights_evidence_sha256>.txt
```

`manifest_id`、`approval_sha256` 是对应JSON（结构化数据）经 `gateway.exec_pitch_contract.canonical` 规范化后的SHA-256（内容摘要）；图片、视频及权属依据的摘要取文件原始字节。拒绝符号链接、越界路径、远程资源、SVG（可含脚本的矢量格式）、动画图片和不匹配的媒体格式。证据原件不向客户下载接口暴露，交付只提供范围、来源、权属名称和摘要。

## 内容包与镜头引用

内容包可以额外包含以下严格字段；这里只选择已经登记的清单，不能赋予新权限：

```json
{"product_visuals":{"manifest_id":"<64位小写摘要>","client_id":"client-a","project_id":"pitch-a","brand":"目标品牌","intended_use":"internal_review"}}
```

`client_id`、`project_id` 以及素材编号只允许以小写字母/数字开头的1–64位小写字母、数字、下划线或短横线。品牌最多60字。用途仅允许 `internal_review`（内部审阅）或 `client_pitch`（客户演示）；后者只是素材使用范围，不触发发送、发布或部署。

镜头新增 `product_asset_id`，其余P0/P1口播、音轨、原文摘录和时间轴字段不变。对应关系：

| 素材种类 | 镜头版式 | 展示方式 |
|---|---|---|
| `crm_screenshot`（产品截图） | `crm_frame` | 原比例完整图片，无重绘界面 |
| `brand_still`（品牌图片／车型静帧） | `broll_plate` | 原比例完整图片，无裁切和遮挡标签 |
| `brand_broll`（品牌辅助实景） | `broll_plate` | 原生交付画幅，只取人工批准时间窗 |
| `brand_logo`（品牌标志） | `closing` | 使用原始图片，替代平台示意图形 |

产品截图镜头缺少素材直接拒绝，不再将“已审画面待提供”当作可交付画面。P1模板调试仍可显示占位，但正式内容包不会通过这一缺口。启用 `product_visuals` 的内容包，实景衬板也必须逐镜绑定已审素材；不能回退公共素材、未审原视频或兼容剪辑器。其余无客户素材范围的旧短片、实景与P0/P1输入继续原契约。

## 清单与人工记录

`manifest.json` 严格包含：

- `version: 1`、`owner: sha256(user_id)`、`client_id`、`project_id`、`brand`。
- `allowed_uses`：上述用途的非空数组，必须覆盖本次用途。
- `media_kind`：与内容包一致的 `approved_local`（登记真实本地素材）或 `synthetic_fixture`（合成工程测试）。两者不能混用。
- `assets`：1–32项，每项严格为 `id`、`kind`、`sha256`、`extension`、`approval_sha256`、`source`。来源说明最多400字，系统不访问其中网址。

每份审批JSON严格包含以下字段，不接收任意额外数据：

| 字段 | 要求 |
|---|---|
| `version`, `record_type`, `decision` | `1`、`human_record`（人工记录）、`approved`（已批准）；测试记录类型不能用于真实素材 |
| `reviewer`, `reviewed_at`, `valid_until`, `authority_reference` | 审批人、带时区的生效/截止时间、可核查的原始审批来源；当前时间必须在有效期内 |
| `asset_sha256`, `kind`, `owner` | 绑定确切原文件、素材类别和当前账户 |
| `client_id`, `project_id`, `brand`, `intended_uses` | 绑定本片客户、项目、品牌和获准用途，不能借用其他项目审批 |
| `rights_holder`, `rights_evidence_sha256` | 权利人及独立本地权属／使用授权依据；仅口头自述“已批准”不足 |
| `brand_status`, `visible_brands`, `vehicles_visible` | 人工确认品牌、画面中出现的品牌列表、是否可见车辆；仅接受 `confirmed`（已确认）及与目标品牌一致的列表 |
| `privacy_status` | 必须 `cleared`（已完成隐私核查／处理），不擅自对真实客户资料脱敏后宣称获准 |
| `frame_window` | 静态图片为 `null`；实景是24帧时钟下 `[起始帧, 结束帧)`，不超过1440帧 |

未知、错误或混有竞品的品牌记录均拒绝。这里使用人工确认记录，未使用OCR（图片文字识别）推断车辆品牌；这也不是P4/P5的全片识别与客户规则审核。

每份清单最大128KiB、每份审批和权属依据最大64KiB；单图片最大8MB、64–4096像素且最多16777216像素；品牌实景最大32MB，必须H.264（视频编码）、24帧和与交付相同的原生画幅。选中素材合计最多128MB。镜头不可超出批准时间窗，不循环、冻结或重复使用同一段时间窗。

## 生成、复检与缺失处理

入场、打包、渲染和独立交付检查均复核记录及原文件。渲染先将原件按摘要复制到本任务目录，再转换为本地数据图片；浏览器仍离线、沙箱开启、全新配置目录。不会向页面注入模型代码、远程图片或远程字体。产品素材不覆盖口播，字幕和音轨沿用原时间轴。

`product_visuals.json` 进入原不可变交付清单及账户鉴权下载，`render_chunks.json`（分块记录）逐块记下素材编号和摘要。独立检查会核对审批范围、来源原件、任务内副本、渲染配置、分块与交付记录。缺失在冻结前发现则拒绝创建；入场后原件或证据改变，任务失败按原规则退款。最终内容状态始终保留 `NOT_REVIEWED`（待人工内容审阅）。

没有接入新的生成媒体回退。即梦等付费调用没有本阶段入口；叙述中的 `approved=true`、积分说明或“已授权”不会触发调用。本轮不新建费用授权，不代替用户购买或审批。

## 无客户素材时的工程复现

`tools/product_visual_fixture.py` 仅创建可见标明“TEST FIXTURE / NOT PRODUCT UI / NOT CLIENT ASSET”（测试图卡／非产品界面／非客户素材）的图卡、测试图形和音调；记录类型硬编码为 `test_fixture`，交付标为 `TEST_FIXTURE_ONLY`。它不创建人工批准记录，不证明真实产品或品牌可用。

准备P1已固定的本地浏览器环境后，在全新目录执行：

```sh
python tools/product_visual_acceptance.py \
  --root workspace/exec-pitch-p2-fixture-new \
  --runtime workspace/exec-pitch-p1-reference/runtime-env.json
```

脚本走真实网关、环回HTTP进程、现有钱包与生成链路，输出6秒测试片到 `video_v3/`。不使用客户图像、不联网检索、不请求配音或付费生成。测试通过只证明接线，实际客户素材验收在缺少真实审批时仍未完成。
