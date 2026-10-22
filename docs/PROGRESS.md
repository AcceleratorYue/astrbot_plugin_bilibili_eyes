# 项目进度（v0.2.9，2026-10-23）

> 仓库：`plugins/astrbot_plugin_bilibili_eyes`
> 当前版本：`0.2.6`（已安装到 `D:\QQbot\astrbot\data\plugins\astrbot_plugin_bilibili_eyes`）
> SPEC：`docs/SPEC.md`；变更记录：`CHANGELOG.md`

## 1. 一句话状态

**Phase 1 已完成并在真实机器人上跑通；Phase 2 的核心「子代理视觉 + UP 主页」已完成，但追问/附图未做；Phase 3 的工程化只做了一部分。**

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
| F6 | 热点选帧 | 🟡 | `view_points` + 弹幕密度 + 均匀保底；`frame_source` 已支持 hotspot/uniform；**字幕高信息段未接入** |
| F7 | 截帧与联系图 | 🟡 | 12 帧 ffmpeg 截取已实现；**contact sheet / `subagent_frame_mode` 未接入** |
| F8 | 子代理笔记 | ✅ | 隔离 `llm_generate`，客观笔记、全角引号、≤1500 字 |
| F9 | 主模型工具 | ✅ | `bilibili_watch` 可用；`bilibili_up` 已于 v0.2.1 移除，UP 仅指令（SPEC 已同步） |
| F10 | 多链接 / UP 歧义 | ✅ | 多链接只处理第一个并提示；用户名多候选交主模型确认 |
| F11 | 笔记缓存 | 🟡 | TTL 7 天 + LRU 500 + 只缓存 digest；**缓存键未包含材料版本** |
| F12 | 原始材料会话保留 30 分钟 | ❌ | 目前只存 `_session_materials` 的 digest/bvid/page，不保留帧/原始材料；追问依赖它 |
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
| Phase 1 | ✅ | v0.1.0 起；现 v0.2.9，真实机器人可用 |
| Phase 2 | 🟡 | F5 已完成；F6/F7 大部分完成；`bilibili_ask`、`bilibili_frame`、联系图未做 |
| Phase 3 | 🟡 | 已有限流/缓存/错误/等待/单测；工程化配置清理、CI、发布未做 |
| Phase 4 | 🟡 | README/CHANGELOG/SPEC 已更新；未做插件市场发布、版本回滚流程 |

## 4. 最近已完成的关键修复（v0.2.0 ~ v0.2.9）

- v0.2.0：B 站域名 IPv6 优先 + 无 IPv6 出口导致 40~80s 超时 → 强制 IPv4 直连。
- v0.2.1：移除 UP 自然语言触发/`bilibili_up` 工具，UP 仅指令；修复「叫啥名字」被当 UP 名。
- v0.2.2：子代理笔记/字幕/评论/UP 信息全角引号规范化。
- v0.2.4：恢复 UP「近期投稿」段；README 明确 SESSDATA 必填。
- v0.2.5：`/看主页` UID 宽容输入（`uid:` / `uid：` / `uid xxx` / `uidxxx`）。
- v0.2.6：抗 412（WBI 30s、随机 dm 参数、空间 Referer）+ 第三方近期投稿兜底（只发 UID，可关）。
- v0.2.7：P0 收尾（配置清理、发布时间/置顶评论、UP 来源日志、SESSDATA 提醒）。
- v0.2.8：主模型不再暴露「笔记/子代理」来源；标签改为 `<video_observation>`，像刚看完视频一样回答。
- v0.2.9：30 分钟内追问自动再次注入摘要，置顶评论保留原文；缓存版本升 v2。

## 5. 未实现 / 待收尾清单

### 5.1 功能缺口

- `bilibili_ask`：基于缓存材料/笔记的追问。
- `bilibili_frame`：按时间点返回单帧图（`ImageContent`）。
- 联系图（contact sheet）与 `subagent_frame_mode=contact_sheet_plus`。
- 音频转录接口桩。
- 原始材料会话保留 30 分钟（F12）。

### 5.2 配置漂移（P0 已清理）

- 已接入：`frame_source`、`include_pinned_comment`、`injection_guard`。
- 已移除未使用项：`video_command`、`up_command`、`multi_link_policy`、`max_parts`、
  `raw_material_keep`、`log_level`。
- 仅保留 `subagent_frame_mode` 为「预留」，schema 已标注只支持 `individual`。

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

### 下一轮：P1（Phase 2 收尾，详见 `docs/ROADMAP.md`）

1. `bilibili_frame(bvid, 时间点)`：返回单帧 `ImageContent`，带路径安全校验。
2. `bilibili_ask(bvid, 问题)`：基于会话缓存材料回答，限制短答案。
3. 原始材料会话 TTL 30 分钟（F12），供追问使用。
4. 联系图模式（`subagent_frame_mode=contact_sheet_plus`）作为可选项，降低视觉 token/耗时。

### P2（Phase 3 工程化）

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
