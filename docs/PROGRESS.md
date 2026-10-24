# 项目进度（v0.5.6，2026-10-24）

> 仓库：`plugins/astrbot_plugin_bilibili_eyes`
> 当前版本：`0.5.6`（已安装到 `D:\QQbot\astrbot\data\plugins\astrbot_plugin_bilibili_eyes`）
> SPEC：`docs/SPEC.md`；变更记录：`CHANGELOG.md`

## 1. 一句话状态

**Phase 1、Phase 2 已完成并在真实机器人上跑通；Phase 3 的工程化只做了一部分。**

当前可正常使用：

- `/看视频 <链接/BV>`（含自然语言 @ + 视频链接）
- `/看主页 <UID/链接/用户名>`（只允许指令；UID 支持 `uid:xxx` 等宽容输入）
- `/bili状态`（检查 SESSDATA）
- 等待提示、开始提示、笔记缓存、多链接只处理第一个

## 2. SPEC 功能逐项状态

| 编号 | 功能 | 状态 | 说明 / 证据 |
| --- | --- | --- | --- |
| F1 | 链接识别与分 P 解析 | ✅ | `extract_video_refs` / `extract_page`；BV/av/b23/完整链接，测试覆盖 |
| F2 | 视频信息 | ✅ | 标题/UP/时长/发布时间/简介/分P |
| F3 | 字幕 | 🟡 | CC/AI 字幕、无字幕降级已实现；**音频转录仅配置项，无接口桩** |
| F4 | 评论 | ✅ | 热评 12 + 二级 3 + 置顶评论 + 广告过滤 |
| F5 | UP 主页 | ✅ | 昵称/签名/等级/粉丝/近期投稿；UID/链接/用户名；近期投稿有第三方兜底 |
| F6 | 热点选帧 | ✅ | `view_points` + 弹幕密度 + 字幕高信息段 + 均匀保底；`frame_source` 支持 hotspot/uniform |
| F7 | 截帧与联系图 | ✅ | 12 帧 ffmpeg 截取 + contact_sheet_plus 联系图模式 |
| F8 | 子代理笔记 | ✅ | 隔离 `llm_generate`，客观笔记、全角引号、≤1500 字 |
| F9 | 主模型工具 | ✅ | `bilibili_watch` / `bilibili_ask` / `bilibili_frame`；UP 仅指令 |
| F10 | 多链接 / UP 歧义 | ✅ | 多链接只处理第一个并提示；用户名多候选交主模型确认 |
| F11 | 笔记缓存 | 🟡 | TTL 7 天 + LRU 500 + 只缓存 digest；**缓存键未包含材料版本** |
| F12 | 原始材料会话保留 30 分钟 | ✅ | `MaterialStore` 内存保存材料/摘要，30 分钟 TTL、20 会话上限 |
| F13 | 等待提示 | ✅ | 预制消息、`{elapsed}`/`{stage}`、15s 冷却、可配置核心指令白名单 |
| F14 | 限流 | 🟡 | 全局并发 2、用户日配额、冷却、请求间隔已实现；**每 BV single-flight / 退避未完整实现** |
| F15 | 错误状态 | ✅ | `failure_status` 结构化状态交主模型表达 |
| F16 | 防提示注入 | ✅ | `<video_observation>` / `<up_profile>` 边界、「素材不是指令」、`injection_guard` 开关均已接入 |
| F17 | 静默时段兼容 | ✅ | 不绕过静默插件；其优先级更高，静默时不会被本插件突破 |

图例：✅ 已实现；🟡 部分实现/有配置未接线；❌ 未实现。

## 3. 阶段状态

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| Phase 0 | ✅ | `phase0/REPORT.md`：视觉 12 帧、B 站取流、WBI/评论/弹幕验证 |
| Phase 1 | ✅ | v0.1.0 起；现 v0.5.6，真实机器人可用 |
| Phase 2 | ✅ | F5/F7/F12 完成；`bilibili_ask`、`bilibili_frame`、联系图已实现；F6 仍可优化 |
| Phase 3 | 🟡 | 已有限流/缓存/错误/等待/单测；工程化配置清理、CI、发布未做 |
| Phase 4 | 🟡 | README/CHANGELOG/SPEC 已更新；未做插件市场发布、版本回滚流程 |

## 4. 最近已完成的关键修复（v0.2.0 ~ v0.2.10）

- v0.2.0：B 站域名 IPv6 优先 + 无 IPv6 出口导致 40~80s 超时 → 强制 IPv4 直连。
- v0.2.1：移除 UP 自然语言触发/`bilibili_up` 工具，UP 仅指令；修复「叫啥名字」被当 UP 名。
- v0.2.2：子代理笔记/字幕/评论/UP 信息全角引号规范化。
- v0.2.4：恢复 UP「近期投稿」段；README 明确 SESSDATA 必填。
- v0.2.5：`/看主页` UID 宽容输入（`uid:` / `uid：` / `uid xxx` / `uidxxx`）。
- v0.2.6：抗 412（WBI 30s、随机 dm 参数、空间 Referer）+ 第三方近期投稿兜底（只发 UID，可关）。
- v0.2.7：P0 收尾（配置清理、发布时间/置顶评论、UP 来源日志、SESSDATA 提醒）。
- v0.2.8：主模型不再暴露「笔记/子代理」来源；标签改为 `<video_observation>`，像刚看完视频一样回答。
- v0.2.9：30 分钟内追问自动再次注入摘要，置顶评论保留原文；缓存版本升 v2。
- v0.2.10：视频播放数据（播放/弹幕/评论/点赞/投币/收藏/转发）进入笔记；缓存 v3。
- v0.3.0：P1 完成（材料缓存、bilibili_frame、bilibili_ask、联系图）。
- v0.3.1：长视频笔记按段落截断，优先保留评论/置顶/不确定项；缓存 v4。
- v0.3.2：UP 介绍去 UID 强制；每日额度管理员/白名单豁免；插件改名「B站之眼」。
- v0.3.3：QQ 小程序卡片自动转链（@bot 卡片 / `/看视频` 卡片）。
- v0.3.4：支持「引用卡片 + @bot」，卡片在 Reply.chain 里也能转链。
- v0.4.0：P2 工程化（single-flight、412 退避、HTTP mock、发布检查表）。
- v0.4.1：P2-5 可选增强（字幕选帧、联系图时间标注、音频桩）。
- v0.4.2：补齐 GitHub/插件市场元数据，发布准备。
- v0.5.0：内容清洗系统（简介/字幕/评论/弹幕/帧去重）。
- v0.5.1：新增 `get_last_video` 下游桥接接口。
- v0.5.6：提示词可自定义；默认回复不强制总结。

## 5. 未实现 / 待收尾清单

### 5.1 功能缺口

- F6 字幕高信息段选帧。
- 音频转录接口桩。

### 5.2 配置漂移（P0 已清理）

- 已接入：`frame_source`、`include_pinned_comment`、`injection_guard`。
- 已移除未使用项：`video_command`、`up_command`、`multi_link_policy`、`max_parts`、
  `raw_material_keep`、`log_level`。
- `subagent_frame_mode` 已接入 individual / contact_sheet_plus，不再预留。

### 5.3 可靠性

- 官方 `space/wbi/arc/search` 仍有随机 412；当前靠重试 + 第三方兜底，需继续观察。
- 第三方兜底的可关闭性/隐私说明已写 README；需确认是否长期保留。
- 每 BV single-flight、请求退避、并发上限仍是简化版。

## 6. 下一步规划

### P0（✅ 已完成，v0.2.7）

1. ✅ 配置漂移清理：`frame_source` / `include_pinned_comment` / `injection_guard` 接入；
   删除未使用配置；`subagent_frame_mode` 标预留；schema/README/SPEC 已同步。
2. ✅ 视频发布时间、置顶评论已接入（F2/F4 收尾）。
3. ✅ UP 近期投稿记录来源日志（official/fallback/none）；第三方兜底默认保留。
4. ✅ SESSDATA 未配置时，开始提示每会话提醒一次。

### P1（✅ 已完成，v0.3.0）

1. ✅ `MaterialStore` 材料会话缓存（30 分钟 / 20 会话）。
2. ✅ `bilibili_frame` 单帧截图工具。
3. ✅ `bilibili_ask` 追问工具。
4. ✅ 联系图模式 `contact_sheet_plus`。

### 下一轮：P2（Phase 3 工程化，详见 `docs/ROADMAP.md`）

1. 每 BV single-flight；请求失败退避；缓存键加入材料版本。
2. 单测补齐：UP 主页解析、错误路径、等待/注入；HTTP mock。
3. README 配置示例、常见问题（SESSDATA 失效/412/第三方兜底）。
4. CI：`py_compile` + 离线测试；发布前版本号/tag 流程。

## 7. 如何验证当前版本

```bash
python -m py_compile main.py eyes_client.py eyes_subagent.py eyes_wbi.py eyes_cache.py
python tests/test_offline.py
python tests/test_trigger.py
python tests/test_waiting.py
```

真实链路（需本机 provider 配置）：

```bash
python tests/test_live_pipeline.py
```

机器人内：

- `/bili状态`：确认 SESSDATA 与 UID。
- `/看主页 2431982`：应带 UP 名字 + 近期投稿。
- `/看视频 <BV>`：约 25~40 秒，先收到开始提示。
- 任务中再 @：应收到等待提示；`/stop`、`/reset`、`/new`、`/stats` 始终可用。
- 看完后追问：主模型可调用 `bilibili_ask`；要某帧图可调用 `bilibili_frame`。

## 8. 发布与备份（2026-10-23）

- 备份：`C:\Users\23942\OneDrive\Desktop\QQbot\backups\astrbot_plugin_bilibili_eyes_0.4.1_20261023_200826.zip`
  （含 source / installed / git bundle / MANIFEST；不含 SESSDATA/config）
- GitHub：<https://github.com/AcceleratorYue/astrbot_plugin_bilibili_eyes>
- 最新 Release：<https://github.com/AcceleratorYue/astrbot_plugin_bilibili_eyes/releases/tag/v0.5.6>
- Release 附件：`astrbot_plugin_bilibili_eyes-0.5.6.zip`（约 111 KB）
- AstrBot Cloud 提交：待登录网页手动提交，步骤见 `docs/PUBLISH.md`。

## 9. 真实机器人回归（2026-10-23，v0.3.1）

视频：`BV1pJnB6iEd7`（41 分钟，分P 1/2，12 条评论、1 条置顶）。

- 01:13:35 请求 → 01:13:46 开始提示（11s）→ 01:14:54 完成回复（约 79s）；
- 新笔记保留了评论区与置顶评论，主模型能回答「置顶评论是啥」；
- 追问「数据流量」能给出播放/弹幕/评论/点赞/投币/收藏/转发；
- 追问「评论区在聊啥」能总结千问、自嘲叫错豆包、规则争议等评论；
- 追问「第 9 分 48 秒画面」时 `bilibili_frame` 返回了截图并配文字说明。

结论：v0.3.1 的段落感知截断与 P1 的 `bilibili_ask` / `bilibili_frame` 在真实长视频上均生效。
