# astrbot_plugin_bilibili_eyes · SPEC v1.0

> 状态：已与作者确认（2026-10-22）。本文件是实施依据；改需求先改本文件再改代码。

## 1. 定位

B 站内容「感知器官」插件：**子代理（眼睛）在隔离上下文里观看并整理 → 主模型（脑子）只拿有界笔记，用自己的判断与语气回应**。

- 子代理：`context.llm_generate`（隔离上下文），输入关键帧图片 + 字幕/简介/评论，输出客观、有界的观影笔记。
- 主模型：通过 function tool 拿到笔记文本，理解后自行组织回复；默认不接收图片。
- 不是 L1：插件不生成"总结消息"直接发送；所有播报都由主模型完成。
- 不做：ASR（只留接口桩）、长期记忆、番剧/直播、动态（后续）。

## 2. 触发方式

| 方式 | 规则 |
| --- | --- |
| 自然语言-视频 | 被 @ 的消息含 B 站视频链接（BV/av/短链/完整链接/小程序卡片）→ 必定触发 |
| 自然语言-UP | ~~被 @ 的消息含空间链接/UP 关键词 → 触发 UP 查询~~ **v0.2.1 已移除，UP 只允许 `/看主页`** |
| 指令 | `/看视频 <链接/BV>`、`/看主页 <UID/链接/用户名>` |
| 总开关 | `nl_trigger_enabled`：false 时不做自动检测、不注册工具，只能指令触发（重载生效） |

- 同一消息既有视频链接又有 UP 意图 → 视频优先。
- 多条链接 → 只处理第一个；笔记携带 `ignored_links`，主模型需用自己的话说明「只看了第一个」。
- 默认只看 P1；链接带 `p=` 看指定分 P。

## 3. 功能清单

| 编号 | 功能 |
| --- | --- |
| F1 | 链接识别与分 P 解析 |
| F2 | 视频信息（标题/UP/时长/发布时间/简介/分P） |
| F3 | 字幕（CC + AI 字幕；无字幕照看并标注；音频接口留桩） |
| F4 | 评论（热评 12 + 二级 3 + 置顶，过滤广告/抽奖） |
| F5 | UP 主页（昵称/签名/等级/粉丝/近期投稿；UID/链接/用户名） |
| F6 | 热点选帧（弹幕密度 XML + `view_points` + 字幕高信息段 + 均匀保底，共 12 帧） |
| F7 | 截帧（480P，ffmpeg）与联系图（按需附图用） |
| F8 | 子代理观影笔记（客观、≤1500 字、带证据/不确定项、无价值判断） |
| F9 | 主模型工具：`bilibili_watch`（`bilibili_up` 已于 v0.2.1 移除，UP 仅指令） |
| F10 | 多链接说明、UP 用户名歧义处理 |
| F11 | 笔记缓存（BV+P+材料版本，TTL 7 天，LRU 500） |
| F12 | 原始材料仅会话内临时保留 30 分钟（供追问） |
| F13 | 等待提示（预制消息，含已工作时间/阶段，不触发主模型） |
| F14 | 限流（每 BV single-flight、全局并发 2、请求间隔/退避、用户日配额） |
| F15 | 错误状态（结构化 status 交由主模型表达） |
| F16 | 防提示注入（素材边界标签） |
| F17 | 静默时段插件兼容（不绕过其拦截） |

## 4. 子代理输入与输出

输入：

- 12 张关键帧（`subagent_frame_mode=individual`，或 `contact_sheet_plus`）；
- 字幕：带时间戳的段落（无字幕则省略并标注）；
- 简介、UP 基本信息；
- 评论：热评原文 + 二级回复（标注为观众观点）；
- 多链接提示（只处理第一个）。

输出（Markdown，≤ `digest_max_chars`）：

1. 客观信息（标题/UP/时长/发布时间）
2. 一句话主旨（只陈述内容，不评价）
3. 时间轴关键节点（时间 + 发生了什么 + 证据：字幕原句/画面可见）
4. 关键画面观察（具体可见元素，不脑补）
5. 观众观点（热评/争议，标注「评论观点」）
6. 不确定项（未看清/无字幕/无法确认）
7. 元信息：`bvid`、`p`、`ignored_links`

硬性要求：不做价值判断、不评价好坏、不推测动机；不确定必须标注。

## 5. 配置项

### 5.1 触发与指令

| 配置 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `enabled` | bool | true | 总开关 |
| `nl_trigger_enabled` | bool | true | 视频自然语言触发；false 时仅指令（UP 只有指令） |
| `command_enabled` | bool | true | 指令入口（指令名固定为 看视频 / 看主页） |
| `group_whitelist` | list | `[]` | 仅这些群生效 |
| `group_blacklist` | list | `[]` | 排除这些群 |
| `cooldown_seconds` | int | 60 | 同群冷却 |
| `user_daily_quota` | int | 20 | 每用户每日次数 |

### 5.2 视觉与子代理

| 配置 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `vision_provider_id` | string | 空 | 空=跟随主模型；无视觉能力则不抽帧 |
| `frame_count` | int | 12 | 子代理观看帧数（4~16） |
| `frame_source` | string | `hotspot` | hotspot=热点+均匀保底；uniform=纯均匀 |
| `frame_height` | int | 480 | 截帧高度 |
| `subagent_frame_mode` | string | `individual` | 预留；当前只支持 individual（联系图待实现） |
| `digest_max_chars` | int | 1500 | 笔记上限 |
| `subagent_timeout` | int | 180 | 子代理超时 |
| `subagent_retries` | int | 1 | 失败重试 |
| `audio_transcription_enabled` | bool | false | 音频转录（仅桩） |
| `audio_transcription_provider_id` | string | 空 | 预留 |

### 5.3 内容

| 配置 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `include_subtitle` | bool | true | 字幕 |
| `subtitle_langs` | string | `zh-Hans,zh,ai-zh,en` | 语言优先级 |
| `include_description` | bool | true | 简介 |
| `include_comments` | bool | true | 评论 |
| `comment_limit` | int | 12 | 热评数 |
| `comment_reply_limit` | int | 3 | 二级回复数 |
| `include_pinned_comment` | bool | true | 置顶 |
| `comment_filter_ads` | bool | true | 过滤广告/抽奖 |
| `max_duration_minutes` | int | 90 | 超长拒看 |
| `max_parts` | int | 1 | 多 P 只看指定 P |
| `up_search_limit` | int | 5 | 用户名搜索候选数 |
| `up_exact_match_only` | bool | true | 仅精确匹配命中 |

### 5.4 缓存与限流

| 配置 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `cache_enabled` | bool | true | 只缓存笔记 |
| `cache_ttl_hours` | int | 168 | 7 天 |
| `cache_max_entries` | int | 500 | LRU |
| `concurrency_limit` | int | 2 | 全局并发 |
| `request_interval` | float | 0.8 | B站请求间隔 |
| `request_timeout` | int | 20 | 单请求超时 |

### 5.5 等待提示

| 配置 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `wait_notice_enabled` | bool | true | 等待提示 |
| `wait_notice_template` | text | `还在看呢…已经看了 {elapsed}（{stage}），别催啦` | 支持 `{elapsed}`/`{stage}`/`{title}`/`{bv}` |
| `wait_notice_cooldown_seconds` | int | 15 | 同会话冷却 |
| `wait_notice_stop_event` | bool | true | 发完拦下本次消息 |

### 5.6 其它

| 配置 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `sessdata` | text | 空 | 登录态（AI 字幕/完整评论） |
| `injection_guard` | bool | true | 素材边界防注入 |
| `max_frame_mb` | int | 3 | 单帧大小 |
| `ffmpeg_path` | string | 空 | 空=imageio-ffmpeg |

## 6. 关键流程

### 6.1 看视频

1. 识别 BV / P / 多链接；
2. 并发/限流检查 → 阶段：`取信息`；
3. 视频信息 + 字幕（阶段 `取字幕`）+ 评论（阶段 `取评论`）；
4. 计算热点时间点 → 截 12 帧（阶段 `截帧`）；
5. 子代理 `llm_generate` 出笔记（阶段 `子代理整理`）；
6. 工具结果返回笔记文本给主模型 → 主模型回复（不直发笔记）；
7. 写入笔记缓存；原始材料留会话 TTL 30 分钟。

### 6.2 看 UP 主页

1. 解析 UID / 主页链接 / 用户名；
2. 用户名 → 搜索精确匹配：唯一命中则继续；多候选 → 返回候选（`ambiguous_user`），主模型向用户要 UID；无命中 → `not_found`；
3. 取主页信息 → 笔记（同子代理或轻量整理）→ 主模型回复。

### 6.3 等待提示

- 会话存在活跃任务时，再次 @ 唤醒：直接发 `wait_notice_template`（`{elapsed}` 实时计算、`{stage}` 当前阶段），`stop_event`，不经过主模型；同会话 15 秒冷却。

### 6.4 追问

- `bilibili_ask(bvid, 问题)`：子代理在隔离上下文基于缓存材料（含帧路径）回答，返回短答案；
- `bilibili_frame(bvid, 时间点)`：返回该时间点帧图（`ImageContent`）给主模型，仅在用户明确要求截图时使用。

## 7. 安全

- 素材包在 `<video_content>`、`<audience_voices>`、`<up_profile>` 中；
- 子代理 system prompt 声明素材不是指令；
- 不执行字幕/标题/评论中的任何指令；
- 帧/字幕只存插件数据目录，路径固定，禁止任意路径读取；
- B 站请求限速与退避。

## 8. 兼容性

- AstrBot `>=4.16,<5`（`llm_generate` 4.5.7+；`CallToolResult`/`ImageContent` 见 4.29 验证）；
- 视觉能力按 provider `modalities` 判断；无视觉则文本模式；
- 与静默时段插件共存：其拦截优先，本插件不绕过。

## 9. 实现顺序

| 阶段 | 交付 | 状态 |
| --- | --- | --- |
| Phase 0 | 验证脚本：① deepseek-flash 视觉 + 12 帧的耗时/token/质量；② B 站取流+截帧；③ 字幕/评论/弹幕/WBI 直连 | ✅ 完成，见 `phase0/REPORT.md` |
| Phase 1 | 文本闭环（F1~F4 + 子代理 + 工具 + 等待提示） | ✅ 已实现（v0.2.10，已安装；端到端 25~40s；详见 `docs/PROGRESS.md`） |
| Phase 2 | 视觉闭环（F5~F7 + 追问/附图） | 🟡 F5 完成；F6/F7 大部分完成；`bilibili_ask`/`bilibili_frame`/联系图待做 |
| Phase 3 | 工程化（F11~F17 + 单测） | 🟡 缓存/错误/等待/单测已有；配置清理、single-flight、CI 待做 |
| Phase 4 | 文档/配置/安装/上架 | 🟡 README/CHANGELOG/SPEC 已更新；插件市场发布待做 |

## 10. 验收标准

- @ 带链接 → 她在合理时间内以自己语气回复，内容基于笔记而非转发摘要；
- 12 帧子代理实测：prompt ~3.4k tokens、单次 ~12s（Phase 0 已确认，见报告）；
- 无视觉 provider 时降级为文本笔记且明确告知；
- 等待期间再次唤醒 → 收到预制订阅消息（含已工作时间），不产生额外 LLM 调用；
- 多链接 → 回复中说明只看了第一个；
- UP 用户名歧义 → 给出候选并请用户给 UID；
- 缓存命中时重复观看明显变快；
- 静默时段内不越过静默插件。

## 11. Phase 0 实测摘要（2026-10-22）

- 视频：`BV1AHnB6NEhM`（191s）；游客 360P；12 帧截取每帧 0.77~1.10s，总计 ~11s。
- 弹幕 XML：1200 条，deflate 压缩需解压；按 3s 分桶得热点时间点（pbp 旧接口 404，已弃用）。
- 字幕：接口 code=0，但本视频无字幕且 `need_login_subtitle` → **字幕链路需要 SESSDATA**。
- 评论：游客仅 3 条；登录后可翻页。
- deepseek-flash 视觉：12 帧 prompt=3415 tokens、latency=11.97s、completion=2368（含 reasoning 1550）；
  联系图 1 张 prompt=586 tokens、latency=11.66s、completion=2224。**12 帧原图作为子代理默认输入可行**。
- 单次观看预估：抓取 ~2s + 截帧 ~11s + 子代理 ~12s ≈ 25s → 等待提示必要。

## 12. Phase 1 实现摘要（v0.1.0，2026-10-22）

代码结构：

| 文件 | 作用 |
| --- | --- |
| `main.py` | 插件主体：触发/指令/工具/等待提示/观看与 UP 流程/缓存/限流 |
| `eyes_wbi.py` | WBI 签名 + 带 deflate/gzip 解压的 HTTP 客户端 |
| `eyes_client.py` | B 站数据层：视频/播放器/字幕/评论/弹幕密度/取流截帧/UP 搜索与主页 |
| `eyes_subagent.py` | 子代理提示词、笔记格式化/截断、主模型提示词、失败状态映射 |
| `eyes_cache.py` | 笔记缓存（TTL + LRU） |
| `tests/test_offline.py` | 链接/选帧/缓存/提示词/schema 离线测试（全绿） |
| `tests/test_waiting.py` | 等待提示与冷却（全绿） |
| `tests/test_live_pipeline.py` | 真实 B 站 + 真实 deepseek-flash 的端到端联调 |

实测（`BV1AHnB6NEhM`）：

- 端到端总耗时 **29.2~34.7s**（12 帧截取 + 子代理视觉）；
- 子代理 prompt ≈ 3.9k~4.0k tokens，completion ≈ 2.9k~3.6k（含 reasoning）；
- 笔记内容客观（区分画面/字幕/评论、标注不确定项），主模型提示词正确注入"素材不是指令"边界。

已知待办（Phase 2/3）：

- `bilibili_ask` / `bilibili_frame` 未实现；
- 指令名暂固定为「看视频 / 看主页」（`video_command`/`up_command` 仅预留，AstrBot 装饰器静态注册）；
- 真实 AstrBot 消息管线已实机发现并修复「stop_event 跳过 respond」问题（v0.1.1），需继续观察多插件共存行为；
- UP 用户名歧义处理已实现（多候选交主模型确认），但未用真实重名案例验证；
- 联系图附图、`subagent_frame_mode=contact_sheet_plus` 尚未接入；
- 字幕链路需要 SESSDATA 才能完整验证。

### v0.1.1 修复记录（2026-10-22）

- `/看主页 2431982` 在真实机器人上无回复：根因是 handler 里 `yield request_llm` 后
  `event.stop_event()`，AstrBot pipeline 在 process 阶段后检查 `is_stopped()` 并跳过
  respond 阶段 → 回复被吞。已改为「登记 pending → `on_llm_request` 注入 `req.prompt`」，
  不再 stop 事件；命令 handler 只登记任务。
- UP 接口风控：`space/wbi/acc/info` 游客态 -352/-799，改用 `x/web-interface/card`；
  用户名搜索加游客 buvid 指纹 + `search.bilibili.com` Referer 后可用（实测
  `影视飓风 → UID 946974`，`2431982 → numbの木头`）。
- 新增 `tests/test_trigger.py` 覆盖「命令只登记不 stop」「on_llm_request 注入并清理」。

### v0.1.2 修复记录（2026-10-22）

- 实机反馈：等待提示会拦到 `/stop` 等指令、无关消息也提示、UP 任务因风控卡 1~2 分钟、且
  「上一次的输出」延迟返回。修复：
  - 指令（`event.get_extra("handlers_parsed_params")` 非空）一律放行，不再由等待提示拦截；
  - 等待提示只在**同一 umo、且新消息确实是 B 站请求**时触发；普通聊天/其它功能不拦；
  - 收到观看请求后立即发「开始提示」（`ack_template_video` / `ack_template_up`）；
  - UP 准备超时 25s、视频 240s；UP 单接口超时压到 8s，避免风控时长时间挂起；
  - 命令在已有活跃任务时只回等待提示，不重复登记。
- `tests/test_trigger.py` 增加「/stop 不被拦」「普通聊天不被拦」「仅 B 站请求提示」用例。

### v0.1.3 拦截策略修正（2026-10-22）

- 不能放行所有指令：只有系统核心指令白名单放行（`wait_notice_allow_commands`，默认
  `stop/reset/new/help/stats/sid/name/provider/dashboard_update/set/unset`），保证
  `/stop`、`/reset`、`/new`、`/stats` 始终可用。
- 观看任务进行中，除白名单外的一切唤醒请求（其它指令、第三方插件指令、普通聊天、
  其它 B 站请求）都发等待提示并 `stop_event`，避免并发；同会话提示冷却默认 15s，
  冷却内只拦截不重复提示。
- 这样既不吞掉核心控制指令，也不会让并发请求和子代理任务打架。

### v0.1.4 新增（2026-10-22）

- 新增 `/bili状态`（别名 `/bili_status`）：调用 `x/web-interface/nav` 检查 SESSDATA，
  有效时显示 UID/昵称，失效时提示重新获取，未配置时提示游客模式与获取方式。
- `tests/test_trigger.py` 增加未配置/有效/失效三种情况。

### v0.1.5 热重载修复（2026-10-22）

- 现象：`/bili状态` 报 `'BiliClient' object has no attribute 'check_login'`。
- 原因：AstrBot 重载插件只重新 import `main`，`eyes_client` 等子模块仍在
  `sys.modules`，指令调到了旧的 `BiliClient`。
- 修复：插件加载时先清掉 `eyes_wbi/eyes_client/eyes_subagent/eyes_cache` 的模块缓存；
  `/bili状态` 增加 nav 直连兜底，旧模块残留的进程也能工作。
- 验证：模拟 `importlib.reload(main)`，重载后 `BiliClient.check_login` 存在。

### v0.1.6 纯指令不再触发 LLM（2026-10-22）

- 实机现象：`/bili状态` 的回复要等 `/stop` 之后才出现，`/stop` 报告取消了 2 个运行中的任务。
- 原因：AstrBot ProcessStage 在插件 handler 结束后，若事件没有发送记录且 `call_llm=False`，
  会再跑一次默认 LLM。纯指令回复只 yield `plain_result`，于是每条指令都额外开了一个 LLM 任务；
  任务排队/被取消后，指令结果才被发出。
- 修复：纯指令回复 yield 前调用 `event.should_call_llm(True)` 阻止默认 LLM；
  `/看视频`、`/看主页` 的有效请求仍保留 LLM 链路（用于注入笔记后的回复）。
- 测试：`/bili状态` 断言 `call_llm=True`，命令结果即时返回。

### v0.1.7 状态指令耗时排查（2026-10-22）

- 实测 bot 同机 `nav` 请求 0.2~0.3 秒（SESSDATA 有效、UID 503563858），B 站网络不是瓶颈；
  日志显示 `/bili状态` 从 21:22:28 到 21:23:48 才发送（80 秒），时间耗在 AstrBot
  事件/回复排队上，而不是 nav。
- 改为 `event.send` 直接发送（绕过回复管线与默认 LLM），处理完立即发出并 `stop_event`。
- 增加耗时日志：`bili状态 开始` / `nav 用时` / `完成`，下一步可区分「handler 开始晚」
  还是「发送被排队」。

### v0.1.8 状态耗时根因（2026-10-22）

- 实机日志：`开始 21:35:17.103` → `nav 用时 80.47s` → `完成 80.97s`。
- 同一 SESSDATA 在同机直接调 nav 仅 0.2~0.3s，说明慢在 `asyncio.to_thread` 的
  默认线程池排队（被其它插件/任务占用时，coroutine 几十秒才拿到线程），不是 B 站。
- 修复：`/bili状态` 改为同步调用 `check_login()`，不经过默认线程池；nav 超时 10s→5s。
- 预期：状态命令 `完成 <1s`。

### v0.1.9 独立线程池（2026-10-22）

- 新增 `worker_threads`（默认 4），插件持有自己的 `ThreadPoolExecutor`；
  所有 `asyncio.to_thread(...)` 替换为 `self._run(...)`（`loop.run_in_executor`）。
- 覆盖：视频信息、播放器、字幕、评论、弹幕、取流、截帧、UP 主页/搜索。
- `terminate` 关闭线程池；测试断言源码不再出现 `asyncio.to_thread(`。
- `/bili状态` 仍用同步 nav（0.2s 级，不占线程池），保证诊断指令不被排队。

### v0.2.0 IPv4 强制（2026-10-22）

- 根因：`api.bilibili.com` 的 DNS 先返回 **8 个 IPv6**；本机无 IPv6 出口时，
  urllib 逐个等待 socket 超时：`timeout=10` → 80s，`timeout=5` → 40s。
- 修复：`eyes_wbi` 新增 `_IPv4HTTPSConnection`，只解析并连接 IPv4，直接
  `http.client` 收发，绕开 urllib 的 IPv6 超时过程。
- 实测：nav 0.25~0.36s；视频/UP/搜索正常，`space/wbi/arc/search` 也能拿到近期投稿。
- 端到端 `test_live_pipeline.py` 34.0s（12 帧 + 视觉子代理）。

### v0.2.1 UP 仅指令 + 强制名字（2026-10-22）

- 自然语言 UP 触发会把「这个 up 主叫啥名字」里的「叫啥名字」当成 UP 名，
  搜到无关 UID（2345625）并回复错误内容；该功能整体移除。
- UP 查询只保留 `/看主页 <UID/链接/用户名>`；`bilibili_up` LLM 工具同步移除，
  `up_nl_keywords` 配置删除。
- `/看主页` 注入提示硬性要求：回复必须原样说出 UP 主名字和 UID，不能只说「这个 UP」。

### v0.2.2 全角引号（2026-10-22）

- 主模型最终回复引用笔记时出现半角 `"`：来源是子代理笔记/字幕/评论里的半角引号。
- 子代理系统提示新增规则：所有引用使用全角引号“”，字幕/评论原文里的半角双引号也要转全角。
- 新增 `normalize_quotes()` 后处理，应用于子代理输出、字幕/评论/简介、UP 主页信息，
  以及注入主模型前的笔记（兼容旧缓存）。
- 测试覆盖成对半角引号转换与提示词断言。

### v0.2.3 UP 名字强兜底（已回退 2026-10-22）

- 原方案：`on_llm_response` 钩子补 `UP 主：<name>（UID）`。
- **已回退**：该问题实际是未重载 0.2.1 的旧行为；强行补名字不自然。
  代码回到 v0.2.2，只保留注入提示里的「必须说出 UP 名字」要求；
  该钩子可作为以后可选的兜底开关。

### v0.2.4 UP 近期投稿恢复（2026-10-22）

- IPv4 强制后 `space/wbi/arc/search` 已能拿到近期投稿（实测 5 条）。
- `build_up_digest` 始终输出「近期投稿」段；无数据时说明可能是游客/风控，建议配置 SESSDATA。
- `/看主页` 注入提示允许自然挑 1~2 条投稿聊，不机械罗列。
- README 顶部与配置表明确：**`sessdata` 必填，否则插件工作异常**。

### v0.2.5 UID 输入宽容（2026-10-22）

- `normalize_up_query()` 支持：`2431982`、`uid:2431982`、`uid：2431982`、
  `UID:2431982`、`uid 2431982`、`uid2431982`（含冒号前后空格），大小写不敏感。
- 命令参数与 `_resolve_up` 内部统一归一化为纯数字。
- 测试覆盖上述格式的解析与 `/看主页` pending 登记。

### v0.2.6 近期投稿抗风控（2026-10-22）

- 现象：SESSDATA 有效，但 `/看主页 22425829` 回复没有近期投稿（`arc/search` 随机 412）。
- 参考 `yt-dlp` / `bilibili-API-collect` / 开源 AstrBot B 站插件：
  - WBI key 缓存 1800s → **30s**（nav key 会轮换）；
  - `dm_img_*` 改为每次随机生成，空间接口加 `Referer`/`Origin`；
  - 保留 3 次重试。
- 官方接口彻底失败时，使用可配置的第三方 API 兜底近期投稿：
  `archive_fallback_enabled`、`archive_fallback_api`；只发送 UID，不带 Cookie。
- 实测 UID 22425829 也能拿到 5 条近期投稿。

### v0.2.7 P0 收尾（2026-10-22）

- F2：视频信息补发布时间，笔记显示 `发布时间：YYYY-MM-DD HH:MM`。
- F4：`include_pinned_comment` 接入，B 站 `top_replies` 置顶评论进入笔记并标「UP置顶」。
- 配置漂移清理：
  - `frame_source` 接入（hotspot / uniform）；
  - 新增 `injection_guard` 并接入提示词边界；
  - 移除未使用的 `video_command`、`up_command`、`multi_link_policy`、`max_parts`、
    `raw_material_keep`、`log_level`；
  - `subagent_frame_mode` 标为预留，仅支持 individual。
- P0-3：UP 主页日志记录近期投稿来源（official/fallback/none）与数量。
- P0-4：未配置 SESSDATA 时，开始提示每会话提醒一次。

### v0.2.8 主模型不暴露来源（2026-10-23）

- 现象：主模型回复「笔记里写的是 2026 年 7 月 29 日 22:10 发布的」，用户不希望暴露内部笔记。
- 调整主模型提示：
  - 改为「你刚才已经看完了这个视频，下面是你观看后的观察内容」；
  - 要求像刚看完视频的人直接回答，不解释信息来源、不提内部工具/子代理/资料；
  - 标签 `<video_notes>` → `<video_observation>`，避免“笔记”暗示。
- `bilibili_watch` 工具返回与描述、UP 主页/候选/未找到提示同步去掉来源词。
- 等待提示阶段 `整理笔记` → `整理内容`，避免等待提示暴露结构。
- 测试断言主模型提示中不再出现「笔记」。

### v0.2.9 追问上下文（2026-10-23）

- 现象：看完视频后追问「置顶评论是啥」，主模型回复「评论区我看不到」，因为追问轮没有再次注入摘要。
- 新增会话追问注入：30 分钟内，消息命中「刚才/视频/评论/置顶/发布时间/投稿/UP 主页」等
  关键词时，把当时摘要再次注入主模型；无关消息不注入。
- 子代理摘要规则新增：UP 置顶评论必须保留原文（≤200 字），不能只概括。
- `NoteCache` 增加版本键（v2），旧摘要自动失效，确保新规则生效。
- 未实现完整 `bilibili_ask` 工具（仍属 P1），当前是轻量追问上下文方案。

### v0.2.10 视频播放数据（2026-10-23）

- `x/web-interface/view` 的 `stat` 字段解析：播放量、弹幕、评论、点赞、投币、收藏、转发。
- 子代理输入和笔记「客观信息」增加播放数据行；兜底摘要也带上。
- 播放数据使用万为单位显示（如 346.0万），避免大数字难读。
- 笔记缓存版本升到 v3，旧摘要自动失效。
