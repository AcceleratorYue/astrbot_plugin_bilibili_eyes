# B站之眼 · astrbot_plugin_bilibili_eyes

> GitHub：<https://github.com/AcceleratorYue/astrbot_plugin_bilibili_eyes>
> 最新 Release：<https://github.com/AcceleratorYue/astrbot_plugin_bilibili_eyes/releases/tag/v0.8.0>
> License：MIT

让主模型「看」B 站内容：**子代理（眼睛）在隔离上下文里看视频并整理客观笔记，主模型（脑子）拿笔记后用自己的判断和语气回复**。

不是把插件总结直接发出去：插件只提供感知材料，回复由主模型完成。

> ⚠️ **必须先配置 `sessdata`，否则插件会工作异常。**
> 未配置时：没有字幕、评论只有少量、UP 主页和近期投稿经常被风控、视频/主页查询也可能失败。
> 获取方法见下方「SESSDATA 怎么获取」。

## 当前版本 v0.8.0

- 新增默认关闭的 **增强模式**：低分辨率变化采样、切点/积分选帧、tiers、完整 DP 装箱、16:9 拼图；
- 增强模式默认 24 帧，按 6 帧/张拆成多张 16:9 拼图，笔记上限 6000 字；普通模式笔记上限 3000 字；
- 无官方字幕时可使用 AstrBot STT 做音频转写（0.6.x 系列）；长音频自动分块，避免超过 Provider 10MB 限制；
- 支持回看、追问、单帧截图、UP 主页、简介/字幕/评论/弹幕清洗、笔记缓存。

[完整版本记录](CHANGELOG.md) · [增强模式方案](docs/增强模式落地方案_20261102.md) · [参考项目调研](docs/调研报告_dsh-see-now_20261102.md) · [安全策略](SECURITY.md) · [许可证](LICENSE)

## 触发方式

| 方式 | 规则 |
| --- | --- |
| 自然语言 | 仅支持视频：@bot 且消息含 B 站视频链接或 B 站小程序卡片即触发；**UP 主不支持自然语言** |
| 指令 | `/看视频 <链接/BV>`、`/看主页 <UID/链接/用户名>`、`/bili状态`（检查 SESSDATA 与当前 UID） |
| 工具 | `bilibili_watch`（看视频）、`bilibili_ask`（追问）、`bilibili_frame`（截图）；UP 仅限 `/看主页` 指令 |

`/看主页` 的 UID 支持宽容输入：`2431982`、`uid:2431982`、`uid：2431982`、
`UID:2431982`、`uid 2431982`、`uid2431982` 都可以，大小写和全/半角冒号不影响。

看完视频后 30 分钟内可以直接追问（例如「置顶评论是啥」「什么时候发布的」），
插件会自动复用当时的摘要，不需要重新看一遍。需要具体画面时，主模型可调用
`bilibili_frame` 返回某一帧；追问由 `bilibili_ask` 基于会话材料回答，不会重新抓 B 站。
| 开关 | `nl_trigger_enabled=false` 时只保留指令（需重载插件） |

## 配置要点

在 AstrBot WebUI → 插件管理 → B站之眼 中配置：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `sessdata` | **必填** | B 站登录态；**不填会导致插件工作异常**：无字幕、评论少、UP 主页/近期投稿易风控、查询失败 |
| `audio_transcription_enabled` | 关 | 用 AstrBot 的 STT Provider 转录音频补字幕 |
| `audio_transcription_mode` | no_subtitle | no_subtitle=仅无字幕时启用；always=常开，有字幕也转录 |
| `audio_transcription_provider_id` | 空 | 指定 STT Provider ID；空=当前会话 STT |
| `audio_transcription_max_seconds` | 600 | 最多转录视频前 N 秒 |
| `audio_transcription_chunk_seconds` | 300 | 长音频分块大小，避免单次超过 Provider 限制 |
| `audio_transcription_max_mb` | 20 | 抽取音频的大小上限 |
| `audio_transcription_timeout` | 120 | STT 转录超时（秒） |
| `vision_provider_id` | 空 | 空 = 跟随主模型；主模型无视觉则不截帧（文本笔记）。也可指定支持图片的 provider |
| `nl_trigger_enabled` | 开 | 视频自然语言触发（UP 主只用 `/看主页`） |
| `user_daily_quota` | 20 | 每用户每日次数；0=不限制 |
| `quota_exempt_admins` | 开 | 管理员豁免每日次数 |
| `quota_exempt_users` | 空 | 豁免用户 ID 白名单（QQ 号） |
| `frame_count` | 12 | 子代理观看帧数（4~16） |
| `frame_source` | hotspot | hotspot=热点+均匀保底；uniform=纯均匀 |
| `subagent_frame_mode` | individual | individual=12 帧原图；contact_sheet_plus=按 6 帧/张拆成多张联系图 |
| `frames_per_sheet` | 6 | 普通联系图每张帧数；拆小一些，保证单帧可读 |
| `enhanced_frames_per_sheet` | 6 | 增强模式每张拼图帧数；24 帧会拆成多张 |
| `digest_max_chars` | 3000 | 普通模式笔记长度上限 |
| `enhanced_digest_max_chars` | 6000 | 增强模式笔记长度上限 |
| `enhanced_mode` | 关 | 增强模式：变化选帧 + tiers + 完整 DP 装箱 + 多张 16:9 拼图 |
| `enhanced_frame_count` | 24 | 增强模式目标帧数 |
| `enhanced_subagent_timeout` | 300 | 增强模式子代理超时 |
| `include_pinned_comment` | 开 | 把 UP 置顶评论纳入笔记 |
| `injection_guard` | 开 | 素材边界防提示注入 |
| `subagent_system_prompt` | 空 | 子代理系统提示词；留空用内置故事整理规则 |
| `subagent_output_instructions` | 空 | 子代理输出格式；留空用内置故事梗概/连续叙事结构 |
| `main_model_prompt_template` | 空 | 回传主模型的提示词模板；留空用内置模板，支持 `{digest}` 等占位符 |
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
- 笔记上限普通模式 3000 字，增强模式 6000 字；增强子代理超时 300 秒；
- 增强流程失败会自动回退普通模式。

增强模式会忽略 `subagent_frame_mode`，固定输出增强拼图；普通模式仍按原配置工作。
增强与普通笔记使用不同缓存变体，不会混用。

## SESSDATA 怎么获取

1. 用浏览器登录 [bilibili.com](https://www.bilibili.com)；
2. 按 `F12` 打开开发者工具 → **Application / 应用** → **Cookies** → `https://www.bilibili.com`；
3. 找到名为 `SESSDATA` 的 Cookie，复制它的 **Value**（形如 `xxxx%2Cxxxx`，URL 编码原样粘贴，不要带 `SESSDATA=` 前缀）；
4. 粘贴到 AstrBot 插件配置的 `sessdata` 字段并保存，重载插件。

也可以：开发者工具 → **Network** → 随便点一个 B 站请求 → 请求头 `Cookie` 里提取 `SESSDATA=` 后面的值。

注意：SESSDATA 等同于登录凭证，别发给别人；会过期，失效后重新获取。填上后字幕和完整评论可用，但仍可能偶发风控，插件会自动做游客指纹兜底。

## 工作流程

1. @ 消息含 B 站链接 → 识别 BV / 分 P / 多链接（只处理第一个）；
2. 子代理阶段：取视频信息 → 字幕（无字幕时可选 ASR 补转录）→ 热评 → 弹幕密度选热点时间 → 截 12 帧；
3. 子代理（视觉 provider）看 12 帧 + 字幕/评论，输出客观笔记（不评价、不脑补、带不确定项）；
4. 主模型收到笔记，用自己的身份和语气回复（多链接时说明只看了第一个）；
5. 笔记按 BV+分P 缓存 7 天；观看期间再次唤醒 → 发送等待提示（含已工作时间/阶段）；
6. 错误只以结构化状态交给主模型，由主模型用自己的话说明。

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

- `subagent_system_prompt`：子代理的观察规则（只看事实、不评价、不脑补）；
- `subagent_output_instructions`：子代理的输出结构（默认客观信息/主旨/时间轴/画面/观众观点/不确定项）；
- `main_model_prompt_template`：回传给主模型的模板。

模板占位符：

```text
{digest}         子代理笔记
{guard_note}     防提示注入说明（injection_guard 开启时才有）
{style_note}     内置的“随口聊两句、不必总结”风格说明
{ignored_note}   多个链接只看第一个的说明
{status_note}    失败/状态说明
{question_note}  用户的具体问题
{question}       只替换问题原文
```

自定义模板必须包含 `{digest}`；没有时插件会自动把观察内容追加到末尾。
默认风格：**使用当前对话角色原本的身份和语气；先给一两句真实反应，再讲内容。
可概括，也可只聊一个细节、画面或感受；表达简洁口语化，避免汇报腔、客服腔和逐条总结。
情绪随内容自然变化，不强行积极或深沉；不主动报时长、不编造细节。
用户没有明确要求时，不主动展开完整总结；只有问“讲了什么/总结一下”时再概括。**

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
