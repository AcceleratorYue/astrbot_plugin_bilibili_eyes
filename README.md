# B站之眼 · astrbot_plugin_bilibili_eyes

> GitHub：<https://github.com/AcceleratorYue/astrbot_plugin_bilibili_eyes>
> 最新 Release：<https://github.com/AcceleratorYue/astrbot_plugin_bilibili_eyes/releases/tag/v0.5.3>

让主模型「看」B 站内容：**子代理（眼睛）在隔离上下文里看视频并整理客观笔记，主模型（脑子）拿笔记后用自己的判断和语气回复**。

不是把插件总结直接发出去：插件只提供感知材料，回复由主模型完成。

> ⚠️ **必须先配置 `sessdata`，否则插件会工作异常。**
> 未配置时：没有字幕、评论只有少量、UP 主页和近期投稿经常被风控、视频/主页查询也可能失败。
> 获取方法见下方「SESSDATA 怎么获取」。

## 状态

- ✅ Phase 1（v0.5.3）：触发、视频信息、字幕、评论、弹幕密度选帧、12 帧视觉子代理、笔记缓存、等待提示、主模型工具、UP 主页
- 🩹 v0.1.1：修复 `/看主页` 无回复（stop_event 跳过 respond）；修复 UP 接口风控（card + buvid 搜索）
- 🩹 v0.1.2：开始提示（先回一句话）；UP 25s / 视频 240s 超时保护
- 🩹 v0.1.3：等待期只放行系统核心指令（stop/reset/new/stats 等白名单），其余指令与聊天一律提示并拦截，冷却 15s 防刷屏
- 🩺 v0.1.4：新增 `/bili状态`，检查 SESSDATA 是否有效并显示 UID/昵称
- 🔧 v0.1.5：修复热重载后仍使用旧 `eyes_client` 导致 `/bili状态` 报 `no attribute 'check_login'`
- ⚡ v0.1.6：纯指令回复不再额外触发 LLM，`/bili状态` 等立即返回，不再排队到 `/stop` 之后
- 🩺 v0.1.7：`/bili状态` 改为直接发送并记录耗时；实测 nav 0.2~0.3s
- ⏱️ v0.1.8：`/bili状态` 改为同步 nav，绕开默认线程池排队
- 🧵 v0.1.9：抓取/截帧/UP 查询全部改用插件独立线程池 `worker_threads`
- 🌐 v0.2.0：B 站 API 强制 IPv4，修复无 IPv6 出口时 urllib 逐个 IPv6 超时导致的 40~80 秒延迟
- 🎯 v0.2.1：UP 主只允许 `/看主页` 指令，移除自然语言触发与 `bilibili_up` 工具；回复强制带 UP 名字
- ✍️ v0.2.2：子代理笔记统一使用全角引号“”，避免主模型引用时残留半角引号
- 🗂️ v0.2.4：恢复 UP 主页「近期投稿」；README 明确标注 SESSDATA 必填
- 🔎 v0.2.5：`/看主页` 支持 `uid:xxx`、`UID：xxx`、`uid xxx`、`uidxxx` 等宽容输入
- 🛡️ v0.2.6：近期投稿抗 412（WBI 30s、随机 dm 参数、空间 Referer）+ 第三方兜底（只发 UID）
- 🧹 v0.2.7：P0 收尾（配置清理、发布时间/置顶评论、UP 来源日志、SESSDATA 提醒）
- 🗣️ v0.2.8：主模型不再暴露「笔记/子代理」来源，像刚看完视频一样直接回答
- 💬 v0.2.9：30 分钟内追问自动带上当时的摘要（含置顶评论原文），不用重新看
- 📊 v0.2.10：补播放量/弹幕/评论/点赞/投币/收藏/转发数据
- ✅ Phase 2（v0.3.0）：会话材料缓存 30 分钟、`bilibili_ask` 追问、`bilibili_frame` 截图、联系图模式
- 🧷 v0.3.1：长视频笔记按段落截断，优先保留评论区/置顶/不确定项
- 🔁 v0.3.2：UP 介绍更自然、每日额度管理员/白名单豁免、插件名改为「B站之眼」
- 🃏 v0.3.3：B站小程序卡片自动转链（@bot + 卡片、`/看视频` + 卡片）
- 🧷 v0.3.4：支持「引用卡片 + @bot」（卡片在 Reply.chain 里）
- ⚙️ v0.4.0：P2 工程化（single-flight、412 指数退避、HTTP mock、发布检查表）
- 🎞️ v0.4.1：字幕高信息段选帧、联系图时间标注、音频接口桩
- 🚀 v0.4.2：补齐插件市场元数据（repo/tags/平台），准备发布
- 🧼 v0.5.0：简介/字幕/评论/弹幕清洗 + 帧去重，减少垃圾上下文
- 🤝 v0.5.1：新增 `get_last_video` 桥接接口，供 B站之手读取上次视频
- 🎛️ v0.5.2：子代理/回传提示词可自定义；默认回复不再强制总结
- 🚫 v0.5.3：默认提示词禁用「这段我看了」等总结式开头
- ⏳ Phase 3：工程化与更多测试

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
| `vision_provider_id` | 空 | 空 = 跟随主模型；主模型无视觉则不截帧（文本笔记）。也可指定支持图片的 provider |
| `nl_trigger_enabled` | 开 | 视频自然语言触发（UP 主只用 `/看主页`） |
| `user_daily_quota` | 20 | 每用户每日次数；0=不限制 |
| `quota_exempt_admins` | 开 | 管理员豁免每日次数 |
| `quota_exempt_users` | 空 | 豁免用户 ID 白名单（QQ 号） |
| `frame_count` | 12 | 子代理观看帧数（4~16） |
| `frame_source` | hotspot | hotspot=热点+均匀保底；uniform=纯均匀 |
| `subagent_frame_mode` | individual | individual=12 帧原图；contact_sheet_plus=1 张联系图（省 token） |
| `include_pinned_comment` | 开 | 把 UP 置顶评论纳入笔记 |
| `injection_guard` | 开 | 素材边界防提示注入 |
| `digest_max_chars` | 1500 | 笔记上限 |
| `subagent_system_prompt` | 空 | 子代理系统提示词；留空用内置观察器规则 |
| `subagent_output_instructions` | 空 | 子代理输出格式；留空用内置六段式结构 |
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

## SESSDATA 怎么获取

1. 用浏览器登录 [bilibili.com](https://www.bilibili.com)；
2. 按 `F12` 打开开发者工具 → **Application / 应用** → **Cookies** → `https://www.bilibili.com`；
3. 找到名为 `SESSDATA` 的 Cookie，复制它的 **Value**（形如 `xxxx%2Cxxxx`，URL 编码原样粘贴，不要带 `SESSDATA=` 前缀）；
4. 粘贴到 AstrBot 插件配置的 `sessdata` 字段并保存，重载插件。

也可以：开发者工具 → **Network** → 随便点一个 B 站请求 → 请求头 `Cookie` 里提取 `SESSDATA=` 后面的值。

注意：SESSDATA 等同于登录凭证，别发给别人；会过期，失效后重新获取。填上后字幕和完整评论可用，但仍可能偶发风控，插件会自动做游客指纹兜底。

## 工作流程

1. @ 消息含 B 站链接 → 识别 BV / 分 P / 多链接（只处理第一个）；
2. 子代理阶段：取视频信息 → 字幕（无字幕降级）→ 热评 → 弹幕密度选热点时间 → 截 12 帧；
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
默认风格已经改为：**可以选择总结，也可以只聊一个细节或感受；
不强制总结，也不必复述整个视频；除非用户明确问“讲了什么/总结一下”，
否则不必给出完整总结。**

## 已知限制

- 不做 ASR（音频转录只留配置与函数桩）；
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
