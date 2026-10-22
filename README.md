# 哔哩哔哩眼睛 · astrbot_plugin_bilibili_eyes

让主模型「看」B 站内容：**子代理（眼睛）在隔离上下文里看视频并整理客观笔记，主模型（脑子）拿笔记后用自己的判断和语气回复**。

不是把插件总结直接发出去：插件只提供感知材料，回复由主模型完成。

> ⚠️ **必须先配置 `sessdata`，否则插件会工作异常。**
> 未配置时：没有字幕、评论只有少量、UP 主页和近期投稿经常被风控、视频/主页查询也可能失败。
> 获取方法见下方「SESSDATA 怎么获取」。

## 状态

- ✅ Phase 1（v0.2.9）：触发、视频信息、字幕、评论、弹幕密度选帧、12 帧视觉子代理、笔记缓存、等待提示、主模型工具、UP 主页
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
- ⏳ Phase 2：按需追问（`bilibili_ask` / `bilibili_frame`）、联系图附图
- ⏳ Phase 3：工程化与更多测试

## 触发方式

| 方式 | 规则 |
| --- | --- |
| 自然语言 | 仅支持视频：@bot 且消息含 B 站视频链接即触发；**UP 主不支持自然语言** |
| 指令 | `/看视频 <链接/BV>`、`/看主页 <UID/链接/用户名>`、`/bili状态`（检查 SESSDATA 与当前 UID） |
| 工具 | 主模型可调用 `bilibili_watch`（视频）；UP 仅限 `/看主页` 指令 |

`/看主页` 的 UID 支持宽容输入：`2431982`、`uid:2431982`、`uid：2431982`、
`UID:2431982`、`uid 2431982`、`uid2431982` 都可以，大小写和全/半角冒号不影响。

看完视频后 30 分钟内可以直接追问（例如「置顶评论是啥」「什么时候发布的」），
插件会自动复用当时的摘要，不需要重新看一遍。
| 开关 | `nl_trigger_enabled=false` 时只保留指令（需重载插件） |

## 配置要点

在 AstrBot WebUI → 插件管理 → 哔哩哔哩眼睛 中配置：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `sessdata` | **必填** | B 站登录态；**不填会导致插件工作异常**：无字幕、评论少、UP 主页/近期投稿易风控、查询失败 |
| `vision_provider_id` | 空 | 空 = 跟随主模型；主模型无视觉则不截帧（文本笔记）。也可指定支持图片的 provider |
| `nl_trigger_enabled` | 开 | 视频自然语言触发（UP 主只用 `/看主页`） |
| `frame_count` | 12 | 子代理观看帧数（4~16） |
| `frame_source` | hotspot | hotspot=热点+均匀保底；uniform=纯均匀 |
| `subagent_frame_mode` | individual | 预留；当前只支持 individual（联系图待实现） |
| `include_pinned_comment` | 开 | 把 UP 置顶评论纳入笔记 |
| `injection_guard` | 开 | 素材边界防提示注入 |
| `digest_max_chars` | 1500 | 笔记上限 |
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
