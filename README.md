# B站之眼 · astrbot_plugin_bilibili_eyes

> GitHub：<https://github.com/AcceleratorYue/astrbot_plugin_bilibili_eyes>
> 最新 Release：<https://github.com/AcceleratorYue/astrbot_plugin_bilibili_eyes/releases/tag/v0.13.1>
> License：MIT

让主模型「看」B 站内容：**子代理（眼睛）在隔离上下文里看视频并整理客观笔记，主模型（脑子）拿笔记后用自己的判断和语气回复**。

不是把插件总结直接发出去：插件只提供感知材料，回复由主模型完成。

> ⚠️ **必须先配置 `sessdata`，否则插件会工作异常。**
> 未配置时：没有字幕、评论只有少量、UP 主页和近期投稿经常被风控、视频/主页查询也可能失败。
> 获取方法见下方「SESSDATA 怎么获取」。

## 当前版本 v0.13.1

- 三种读取模式：普通、增强、**极致模式**；
  - 普通/增强的固定帧数与固定笔记预算保持不变；
  - 极致模式按视频时长、字幕/ASR 信息量、画面变化动态决定帧数；
  - 极致模式使用动态笔记预算，避免长视频被固定字数截断；
- 笔记拆成“核心内容 + 其他客观内容”，评论区原文不再被简单删减：
  - 普通：核心 2000 + 其他 1000；
  - 增强：核心 4500 + 其他 1500；
  - 极致：核心 1500~9000 + 其他 800~3500，按视频体量动态计算；
- 新增 `bilibili_transcript`：主模型可直接查询官方字幕/ASR 原文，不再经过子代理；
- 原文缓存独立落盘，内存材料过期/重启后仍可回查；
- 极致模式补齐像素预算布局、场景权重、候选帧质量、超预算二次压缩；
- 配置页按 10 个板块分组，旧扁平配置自动迁移；
- 新增 WebUI 设置中心：概览/登录/视频/原文/10 组配置/缓存/诊断；
- 支持 B站扫码登录、账号信息与退出回退；
- 支持回看、追问、单帧截图、UP 主页、简介/字幕/评论/弹幕清洗、笔记缓存。

[完整版本记录](CHANGELOG.md) · [极致模式设计](docs/动态截帧方案设计_20261104.md) · [原文直读设计](docs/二次查询直接取原文方案_20261104.md) · [WebUI 设计](docs/WebUI设计方案_20261104.md) · [WebUI/扫码登录方案](docs/WebUI与B站扫码登录更新方案_20261108.md) · [内嵌字幕 OCR 方案](docs/内嵌字幕OCR与ASR优先级增强方案_20261105.md) · [安全策略](SECURITY.md) · [许可证](LICENSE)

## 触发方式

| 方式 | 规则 |
| --- | --- |
| 自然语言 | 仅支持视频：@bot 且消息含 B 站视频链接或 B 站小程序卡片即触发；**UP 主不支持自然语言** |
| 指令 | `/看视频 <链接/BV>`、`/看主页 <UID/链接/用户名>`、`/bili状态`（检查 SESSDATA 与当前 UID） |
| 工具 | `bilibili_watch`（看视频）、`bilibili_ask`（追问）、`bilibili_transcript`（查原文）、`bilibili_frame`（截图）；UP 仅限 `/看主页` 指令 |

`/看主页` 的 UID 支持宽容输入：`2431982`、`uid:2431982`、`uid：2431982`、
`UID:2431982`、`uid 2431982`、`uid2431982` 都可以，大小写和全/半角冒号不影响。

看完视频后 30 分钟内可以直接追问（例如「置顶评论是啥」「什么时候发布的」），
插件会自动复用当时的摘要，不需要重新看一遍。需要具体画面时，主模型可调用
`bilibili_frame` 返回某一帧；追问由 `bilibili_ask` 基于会话材料回答，不会重新抓 B 站。
> `nl_trigger_enabled=false` 时只保留指令（需重载插件）。

## 三种模式

新增 `video_mode`，三种模式并存，普通/增强行为保持不变：

| 模式 | 配置 | 帧数 | 笔记预算 | 适合 |
| --- | --- | --- | --- | --- |
| 普通 | `normal` | 固定 12 | 2000 + 1000 | 日常快速看 |
| 增强 | `enhanced` | 固定 24 | 4500 + 1500 | 日常剧情/整活 |
| 极致 | `extreme` | 动态 4~48 | 动态核心 + 动态其他 | 长视频/信息密度差异大/不想被截断 |

- `video_mode=auto` 时，旧 `enhanced_mode` 继续生效：
  - `false` → 普通
  - `true` → 增强
- `extreme` 必须显式选择，默认不启用；
- 极致模式失败时先回退增强，再回退普通。

极致模式的动态帧预算会参考：

- 视频时长；
- 官方字幕/ASR 的信息量、覆盖度、质量；
- 画面切镜和变化密度；
- 可读性目标与最大拼图张数。

笔记预算按视频体量动态计算：核心 1500~9000 字、其他 800~3500 字，取帧/文本越多预算越高；预算会写入子代理提示词，并预留余量。

## 配置要点

在 AstrBot WebUI → 插件管理 → B站之眼 中配置。配置页按 10 个板块分组：

```text
基础与触发 / B站连接 / 画面与模式 / 增强模式 / 极致模式
音频转录 / 内容采集 / 提示词 / 缓存与性能 / 等待与反馈
```

旧版扁平配置会在插件重载时自动迁移到对应分组；分组和扁平两种读取方式都兼容。

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `sessdata` | 推荐扫码 | B站登录态；WebUI「登录」页扫码后自动管理，此项作为手动回退；不填会导致字幕/评论/UP 查询不完整 |
| `audio_transcription_enabled` | 关 | 用 AstrBot 的 STT Provider 转录音频补字幕 |
| `audio_transcription_mode` | no_subtitle | no_subtitle=仅无字幕时启用；always=常开，有字幕也转录 |
| `audio_transcription_provider_id` | 空 | 指定 STT Provider ID；空=当前会话 STT |
| `audio_transcription_max_seconds` | 600 | 最多转录视频前 N 秒 |
| `audio_transcription_chunk_seconds` | 300 | 长音频分块大小，避免单次超过 Provider 限制 |
| `audio_transcription_max_mb` | 20 | 抽取音频的大小上限 |
| `audio_transcription_timeout` | 120 | STT 转录超时（秒） |
| `subtitle_langs` | zh-Hans,zh,ai-zh,en | 主字幕语言优先级；指定主字幕 |
| `subtitle_dual_enabled` | 开 | 主字幕之外再抓一条不同语系的官方字幕 |
| `subtitle_secondary_langs` | en,en-US,en-GB | 辅字幕语言优先级；主字幕已是英语时自动改找其他语系 |
| `ocr_subtitle_enabled` | 开 | 无人工/AI 字幕时识别画面内嵌字幕，优先级高于 ASR |
| `ocr_subtitle_priority` | after_ai | after_ai=官方 AI 优先；before_ai=内嵌 OCR 优先；ASR 永远最后 |
| `ocr_subtitle_fps` | 1 | OCR 采样帧率 |
| `ocr_subtitle_min_confidence` | 0.6 | OCR 最低置信度 |
| `ocr_engine` | auto | OCR 引擎；默认 RapidOCR |
| `vision_provider_id` | 空 | 空 = 跟随主模型；主模型无视觉则不截帧（文本笔记）。也可指定支持图片的 provider |
| `nl_trigger_enabled` | 开 | 视频自然语言触发（UP 主只用 `/看主页`） |
| `user_daily_quota` | 20 | 每用户每日次数；0=不限制 |
| `quota_exempt_admins` | 开 | 管理员豁免每日次数 |
| `quota_exempt_users` | 空 | 豁免用户 ID 白名单（QQ 号） |
| `frame_count` | 12 | 子代理观看帧数（4~16） |
| `frame_source` | hotspot | hotspot=热点+均匀保底；uniform=纯均匀 |
| `subagent_frame_mode` | individual | individual=12 帧原图；contact_sheet_plus=按 6 帧/张拆成多张联系图 |
| `video_mode` | auto | auto/normal/enhanced/extreme；auto 兼容旧 `enhanced_mode` |
| `frames_per_sheet` | 6 | 普通联系图每张帧数；拆小一些，保证单帧可读 |
| `enhanced_frames_per_sheet` | 6 | 增强模式每张拼图帧数；24 帧会拆成多张 |
| `extreme_max_frames` | 48 | 极致模式动态帧数上限 |
| `extreme_max_sheets` | 8 | 极致模式最大拼图张数 |
| `extreme_max_analysis_seconds` | 3600 | 极致模式最多分析秒数 |
| `extreme_pixel_budget` | 1200000 | 每张拼图像素预算，影响画布尺寸和每张格数 |
| `extreme_readability` | scene | shot/scene/text；决定每张可放几帧 |
| `extreme_note_core_min/max` | 1500/9000 | 极致核心笔记动态范围 |
| `extreme_note_other_min/max` | 800/3500 | 极致其他内容动态范围 |
| `extreme_subagent_timeout` | 300 | 极致子代理超时 |
| `transcript_ttl_hours` | 168 | 字幕/ASR 原文缓存小时 |
| `transcript_max_entries` | 200 | 原文缓存最大条数 |
| `digest_max_chars` | 2000 | 普通模式核心笔记上限 |
| `digest_other_max_chars` | 1000 | 普通模式其他客观内容上限 |
| `enhanced_digest_max_chars` | 4500 | 增强模式核心笔记上限 |
| `enhanced_other_max_chars` | 1500 | 增强模式其他客观内容上限 |
| `enhanced_mode` | 关 | 增强模式：变化选帧 + tiers + 完整 DP 装箱 + 多张 16:9 拼图 |
| `enhanced_frame_count` | 24 | 增强模式目标帧数 |
| `enhanced_subagent_timeout` | 300 | 增强模式子代理超时 |
| `include_pinned_comment` | 开 | 把 UP 置顶评论纳入笔记 |
| `injection_guard` | 开 | 素材边界防提示注入 |
| `subagent_system_prompt` | 空 | 子代理系统提示词；留空用内置故事整理规则 |
| `subagent_output_instructions` | 空 | 子代理输出格式；留空用内置故事梗概/连续叙事结构 |
| `main_model_prompt_template` | 空 | 回传主模型的提示词模板；支持 `{digest}` / `{core_digest}` / `{other_digest}` 等，详见「提示词自定义」 |
| `ack_enabled` | 开 | 收到请求后先回一句开始提示 |
| `ack_template_video` / `ack_template_up` | 我去看看…/我去翻一下… | 开始提示文案 |
| `prepare_timeout_video` / `prepare_timeout_up` | 240 / 25 秒 | 视频 / UP 准备超时 |
| `worker_threads` | 4 | 插件独立线程池大小，抓取/截帧/UP 查询不与其他插件抢线程 |
| `archive_fallback_enabled` | 开 | 官方空间接口被风控时，用第三方 API 拉近期投稿；只发送 UID，不带 Cookie |
| `archive_fallback_api` | uapis.cn/... | 第三方投稿 API 地址，可关闭或替换 |
| `wait_notice_enabled` | 开 | 观看期间再次唤醒时发预制提示（不触发主模型） |
| `wait_notice_allow_commands` | stop/reset/new/stats 等 | 白名单核心指令：始终放行；其余指令与聊天一律提示并拦截 |
| `cache_ttl_hours` | 168 | 笔记缓存 7 天 |
| `max_duration_minutes` | 90 | 超长视频拒看 |

完整配置见 `_conf_schema.json`。

> 第三方投稿兜底只发送 UID，**不会发送 SESSDATA/Cookie**；不信任第三方可把
> `archive_fallback_enabled` 关掉，只走 B 站官方接口。

## 增强模式

`enhanced_mode` 默认关闭，普通模式、现有钩子、`frame_source` 和
`subagent_frame_mode` 都不受影响。

开启后：

- 单进程低分辨率采样视频；
- 用 HSV 变化分做切点、积分和去重选帧；
- 按帧密度计算 tiers；
- 完整 DP 装箱；
- 输出多张 **16:9 矩形拼图**（默认 1280×720，24 帧按 6 帧/张拆分）；
- 笔记预算普通模式 2000 + 1000 字，增强模式 4500 + 1500 字；增强子代理超时 300 秒；
- 增强流程失败会自动回退普通模式。

增强模式会忽略 `subagent_frame_mode`，固定输出增强拼图；普通模式仍按原配置工作。
增强与普通笔记使用不同缓存变体，不会混用。

## 极致模式

`video_mode=extreme` 时启用，默认关闭，不替代普通/增强。

流程：

1. 先取视频信息、字幕/ASR；
2. 计算文本画像（覆盖度、密度、多样性、质量）；
3. 低分辨率扫描，计算切镜/画面变化画像；
4. 按时长基础曲线 + 文本/画面修正得到动态帧数；
5. 按切点划分场景，每场景至少 1 帧，按画面变化/文本缺口加权分配；
6. 切点过少/长静态场景自动补均匀时间边界，按全时段分布选帧，避免只取开头；
7. 在每个场景时间点生成候选帧，避开切点，按非近黑 + 清晰度选择；
7. 按可读性目标和像素预算自动规划画布/每张格数，拆成多张拼图；
8. 每格记录 `from/to/frame_at/readability/dark`；
9. 按视频体量计算核心/其他笔记预算，写入子代理提示词；
10. 超预算时二次调用子代理做结构化压缩，不重新读视频。

极致模式上限：

- 最大帧数 48；
- 最大拼图张数 8；
- 可读性 `shot/scene/text`，分别影响每张格数；
- 每张像素预算 `extreme_pixel_budget`，默认 120 万；
- 超过可读性/图片上限时减少帧数并写入证据缺口。

## 回读原文

新增工具 `bilibili_transcript`，用于二次查询时**直接读取官方字幕/ASR 原文**，不经过子代理。

```text
bilibili_transcript(
    query="关键词",
    start="40",
    end="55",
    source="both",
    lang="",
    max_lines="20"
)
```

- 支持关键词、时间范围；
- `source=official/ai/ocr/asr/both`；
- `lang=zh/en/ja/ko` 过滤字幕轨，空 = 全部；
- 官方字幕和 ASR 分开标注；
- ASR 时间戳标“约”；
- 单次最多约 20 行，超限提示缩小范围；
- 原文只存文字，默认缓存 7 天；内存材料过期/重启后可回退磁盘；
- 缓存缺失时提示重新观看，不自动重抓/重新 ASR。

`bilibili_ask` 仍用于自然语言总结；问“原话/第几分钟说了什么”时用 `bilibili_transcript`。

## WebUI

在 AstrBot 插件管理页打开「B站之眼 · 设置中心」。

页面包含：

- **概览**：登录、模式、视觉模型、文本来源、缓存、FFmpeg 状态卡，最近观看和运行信息；
- **登录**：B站扫码登录、账号头像/昵称/UID/等级/大会员、退出登录；
- **视频记录**：标题、BV、模式、文本来源、时间；
- **视频详情**：核心笔记 / 其他客观内容 / 帧预算 / 原文；
- **原文检索**：官方、B站 AI、内嵌 OCR、ASR 分来源和语言检索；
- **配置**：10 个分组共 100+ 项，支持编辑、恢复默认、底部 savebar、Ctrl+S、热生效；
- **缓存**：按类型清理，有视频处理中时保护帧缓存；
- **诊断**：运行环境、路径、接口和最近记录。

WebUI 通过 AstrBot 插件页面桥接，不启动独立服务、不占端口。登录凭据由扫码页管理，配置中的手动 SESSDATA 作为回退。扫码二维码由可选依赖 `qrcode` 本地渲染。

设计稿：
- [docs/WebUI设计方案_20261104.md](docs/WebUI设计方案_20261104.md)
- [docs/WebUI与B站扫码登录更新方案_20261108.md](docs/WebUI与B站扫码登录更新方案_20261108.md)

## B站扫码登录

推荐在 WebUI「登录」页生成二维码，用哔哩哔哩手机客户端扫码。

也可以使用指令：

```text
/bili登录   管理员申请二维码，发送图片或登录链接
/bili注销   清除扫码凭据，回退到配置 SESSDATA 或游客
/bili状态   查看登录、OCR、ASR 状态
```

凭据优先级：

```text
扫码凭据 credentials.json
  > 插件配置 sessdata
  > 游客
```

凭据保存在插件 data 目录，是明文 JSON；建议使用小号，不要分享 data 目录。退出登录只清扫码凭据，不会删除手动配置的 SESSDATA。

## SESSDATA 怎么获取

1. 用浏览器登录 [bilibili.com](https://www.bilibili.com)；
2. 按 `F12` 打开开发者工具 → **Application / 应用** → **Cookies** → `https://www.bilibili.com`；
3. 找到名为 `SESSDATA` 的 Cookie，复制它的 **Value**（形如 `xxxx%2Cxxxx`，URL 编码原样粘贴，不要带 `SESSDATA=` 前缀）；
4. 粘贴到 AstrBot 插件配置的 `sessdata` 字段并保存，重载插件。

也可以：开发者工具 → **Network** → 随便点一个 B 站请求 → 请求头 `Cookie` 里提取 `SESSDATA=` 后面的值。

注意：SESSDATA 等同于登录凭证，别发给别人；会过期，失效后重新获取。填上后字幕和完整评论可用，但仍可能偶发风控，插件会自动做游客指纹兜底。

## 工作流程

1. @ 消息含 B 站链接 → 识别 BV / 分 P / 多链接（只处理第一个）；
2. 按 `video_mode` 选择普通/增强/极致；
3. 取视频信息 → 字幕（无字幕时可选 ASR 补转录）→ 热评 → 弹幕/热点；
4. 截帧：普通固定 12 帧；增强固定 24 帧多拼图；极致按文本/画面/时长动态；
5. 子代理（视觉 provider）看画面 + 字幕/评论，输出核心内容 + 其他客观内容；
6. 主模型收到笔记，用自己的身份和语气回复（多链接时说明只看了第一个）；
7. 笔记按 BV+分P 缓存；字幕/ASR 原文另存，供 `bilibili_transcript` 二次查询；
8. 观看期间再次唤醒 → 发送等待提示；错误只以结构化状态交给主模型。

## 常见问题

- **B站小程序卡片识别不到**：支持当前消息里的卡片，也支持「引用卡片 + @bot」；
  仍不行时看日志有没有 `从小程序卡片转链`，没有就把原始 JSON 发出来。
- **一直说“评论区看不到”**：确认 SESSDATA 有效；长视频笔记会折叠时间轴但保留「观众观点/置顶」；
  缓存版本升级后需要重新看一次。
- **B站 412/风控**：请求会按 1s→2s→4s 指数退避重试；同一视频并发请求会 single-flight 复用，
  不会重复抓取。
- **观看次数不够**：`quota_exempt_admins` 默认管理员豁免；也可把 QQ 号加到 `quota_exempt_users`。
- **UP 介绍带 UID 很怪**：已改为自然说名字，不主动报 UID。

## 内容清洗

子代理看到的材料会先经过一轮提纯（`eyes_clean.py`）：

- 简介去掉链接、粉丝群、商务邮箱、BGM/免责声明等噪声，保留核心描述；
- 字幕把 1~2 秒碎片按标点/停顿合并，去掉口水重复，并标出高信息段；
- 评论过滤抽奖接龙/纯表情/无意义短评，标注 UP 置顶、UP 本人、时间戳评论；
- 弹幕过滤 666/打卡/签到，提取密集区间的“高能关键词”作为观众情绪；
- 截帧避开片头片尾，多截候选帧后用 dHash 去重。

## 提示词自定义

三处可配，全部留空时使用内置默认：

- `subagent_system_prompt`：子代理的整理规则（允许有证据的连续叙事推断，评论只作为观众观点）；
- `subagent_output_instructions`：子代理的输出结构。默认要求输出
  `<video_core_notes>` 核心内容 + `<video_other_notes>` 其他客观内容两份；
- `main_model_prompt_template`：回传给主模型的模板。

### 两份笔记

- **核心内容**：故事梗概、连续叙事、关键对白/ASR、关键画面、不确定项；
- **其他客观内容**：视频客观信息、评论区原文、关键弹幕。

普通模式默认预算：核心 **2000** 字 + 其他 **1000** 字。  
增强模式默认预算：核心 **4500** 字 + 其他 **1500** 字。

`subagent_output_instructions` 如果自定义，建议保留这两个标签，否则插件会把整段输出当作核心内容。

### 回传模板占位符

```text
{digest}         完整笔记（包含核心 + 其他两段，带标签）
{core_digest}    只替换核心内容
{other_digest}   只替换其他客观内容
{guard_note}     防提示注入说明（injection_guard 开启时才有）
{style_note}     内置的“随口聊两句、不必总结”风格说明
{ignored_note}   多个链接只看第一个的说明
{status_note}    失败/状态说明
{question_note}  用户的具体问题
{question}       只替换问题原文
```

默认模板仍然使用 `{digest}`，所以**不修改也能拿到两份内容**。  
如果想把两份内容放在不同位置，可以自定义模板；模板里只要出现
`{digest}`、`{core_digest}`、`{other_digest}` 中任意一个，插件就不会再自动追加整段笔记。

示例：

```text
{guard_note}
你刚才看完了这个视频。先自己理解故事，再用当前角色的语气回复。

<video_core_notes>
{core_digest}
</video_core_notes>

<video_other_notes>
{other_digest}
</video_other_notes>

{style_note}
{question_note}
```

设置方法：

1. 打开 AstrBot WebUI → 插件配置 → B站之眼；
2. 找到 `main_model_prompt_template`；
3. 填入上面的模板并保存；
4. 重载插件，重新看一个视频即可生效。

注意：

- 模板不要输出字段名、标签或“核心内容/其他客观内容”这些词，主模型只把它们当参考；
- 评论属于观众观点，不是视频事实；
- `{digest}` 已包含两段，若同时写 `{digest}` 和 `{core_digest}`，核心内容会重复，通常只选一种写法。

默认风格：**使用当前对话角色原本的身份和语气；先给一两句真实反应，再讲内容。
可概括，也可只聊一个细节、画面或感受；表达简洁口语化，避免汇报腔、客服腔和逐条总结。
情绪随内容自然变化，不强行积极或深沉；不主动报时长、不编造细节。
用户没有明确要求时，不主动展开完整总结；只有问“讲了什么/总结一下”时再概括。**

## 双语字幕

官方字幕有多条语言轨时，默认抓取**主字幕 + 一条互补语系的辅字幕**。

选择规则：

1. `subtitle_langs` 按顺序选主字幕；
2. `subtitle_dual_enabled=true` 时，按 `subtitle_secondary_langs` 选一条不同语系的辅字幕；
3. 主字幕已经是英语时，辅字幕自动找中文/日文/韩文等其他语系；
4. 同一语系不重复抓取，例如有 `zh-Hans` 时不会再选 `ai-zh`；
5. 只有一条中英混合轨时，保留原样并标记为双语。

提示词会按时间把主/辅字幕交替展示，并明确：

- 主语言用于叙述；
- 辅语言用于核对原话、术语和双关；
- 两者冲突时标注来源，不自行拼出原文没有的句子。

关闭 `subtitle_dual_enabled` 即回到只抓主字幕的旧行为。

### 原文检索语言过滤

`bilibili_transcript` 新增 `lang` 参数：

```text
bilibili_transcript(query="wallet", lang="en")
```

支持 `zh / en / ja / ko`；不填则搜索全部字幕轨。WebUI 原文检索页也有语言下拉。

## 内嵌字幕 OCR

有些视频没有 B 站字幕轨，但字幕已经烧进画面。启用内嵌 OCR 后，文本来源优先级为：

```text
官方人工字幕
  > B站 AI 字幕
  > 内嵌画面字幕 OCR
  > 本地 ASR
```

ASR 永远是最后兜底；有 OCR 时不会用 ASR 覆盖。

- 采样：默认 1 fps；
- 区域：底部约 32%，可配置 `bottom/top`；
- 引擎：RapidOCR（`rapidocr_onnxruntime`）；
- 连续相同字幕合并，短于一帧的噪声过滤；
- OCR 字幕标记为“内嵌OCR”，提示词要求把不确定的专有名词/数字写入“不确定项”；
- OCR 覆盖率低于 15% 时回退 ASR；
- 双语硬字幕尝试拆成主/辅两轨。

前提：安装 `rapidocr_onnxruntime`（已加入 `requirements.txt`）。OCR 失败或未安装时自动回退 ASR。

完整方案见：[内嵌字幕OCR与ASR优先级增强方案_20261105.md](docs/内嵌字幕OCR与ASR优先级增强方案_20261105.md)。

## 音频转录（ASR）

开启 `audio_transcription_enabled` 后，会按模式判断是否需要转录：

1. 按 `audio_transcription_mode` 判断是否启用；
2. 从播放地址取音频流；
3. 用 ffmpeg 抽成 16kHz / 单声道 / 32kbps 的临时 mp3；
4. 调用 AstrBot 已配置的 STT Provider 转录；
5. 清洗 ASR 幻觉、复读和空句，按标点断句；
6. 写回字幕材料，继续走原有笔记流程。

模式：

- `no_subtitle`（默认）：只有官方字幕为空时才跑 ASR；
- `always`：不管有没有官方字幕都跑 ASR。  
  有官方字幕时**官方字幕保留**，ASR 作为独立补充材料进入笔记，避免用低质量转录直接覆盖官方字幕。

注意：

- 只转录视频前 `audio_transcription_max_seconds` 秒，默认 600 秒；
- ASR 没有逐句时间戳，插件会按字数做**近似时间轴**，仅用于排序和选帧；
- 视频被截断时会在笔记里标注“仅视频前段”；
- 音频会发送给所选 STT 服务商，开启前请确认隐私与费用；
- 没有可用 STT Provider、抽取失败或超时时会平滑跳过，不阻塞观看。

## 已知限制

- ASR 依赖 AstrBot 已配置的 STT Provider，未配置时自动跳过；
- 字幕依赖登录态（`need_login_subtitle`），游客多为无字幕；
- 游客最高 360P（截帧仍够辨认）；
- 不做长期记忆（只做插件本地笔记缓存）；
- 番剧/直播不支持；动态后续再说；
- 单次观看约 25~35 秒（12 帧 + 子代理），等待提示用于安抚。

## 开发测试

```bash
python tests/test_offline.py        # 离线：解析/选帧/缓存/提示词/schema
python tests/test_waiting.py        # 等待提示
python tests/test_live_pipeline.py  # 端到端：真实 B 站 + 真实视觉模型（需本机 provider 配置）
```

`phase0/` 下有 B 站接口/截帧/视觉的独立验证脚本与 `REPORT.md`。

## 致谢

本插件受益于以下项目和社区：

- [dsh-see-now](https://github.com/SAOS-3624/dsh-see-now)（Apache-2.0）：增强模式的“画面变化选帧 + tiers + DP 拼图”设计参考；本项目为 Python 独立实现，未直接复制其源码。
- [astrbot_plugin_bilibili_watch_Evolution](https://github.com/kermond369-nsis/astrbot_plugin_bilibili_watch_Evolution)：ASR / 音频处理链路的思路参考。
- [AstrBot](https://github.com/AstrBotDevs/AstrBot)：插件框架、Provider 与事件机制。
- B站公开接口、相关文档，以及所有测试和反馈过的朋友。

本项目与 B站官方无隶属关系。

## 许可证

本项目使用 **MIT License**。详见 [LICENSE](LICENSE) 与 [第三方说明](THIRD_PARTY_NOTICES.md)。

第三方依赖（AstrBot、imageio-ffmpeg、Pillow 等）保留各自许可证；本项目不包含它们的源码。
