# 下一轮规划：P2（Phase 3 工程化）

> 基线：v0.3.1（P0/P1 已完成，Phase 1/2 闭环）
> 状态：**未开始**，等待真实机器人测试反馈后启动
> 目标：把「能用」变成「稳定、可发布、可回归」。

## 1. P1 完成情况

| 任务 | 状态 | 结果 |
| --- | --- | --- |
| P1-1 材料会话缓存 | ✅ | `MaterialStore` 内存保存 Material/摘要，30 分钟 TTL、20 会话上限 |
| P1-2 `bilibili_frame` | ✅ | 秒/`mm:ss`/`hh:mm:ss`，复用最近帧或按点截取，返回 ImageContent |
| P1-3 `bilibili_ask` | ✅ | 基于会话材料回答追问，不重新抓 B 站 |
| P1-4 联系图 | ✅ | `subagent_frame_mode=contact_sheet_plus`，12 帧拼图省 token |
| P1 回归 | ✅ | `BV1pJnB6iEd7` 41 分钟视频：评论/置顶/播放数据/追问/9:48 截图均通过 |

## 2. P2 任务板（按执行顺序）

### P2-0 测试反馈归档（✅ 已完成）

已归档并修复：

| 反馈 | 处理 | 版本 |
| --- | --- | --- |
| UP 介绍带 UID 不自然 | 去掉强制 UID，自然说名字 | 0.3.2 |
| 每日额度需要豁免 | `quota_exempt_admins` + `quota_exempt_users` | 0.3.2 |
| 插件名改「B站之眼」 | display_name + 日志前缀 | 0.3.2 |
| 小程序卡片无法观看 | 新增卡片转链 | 0.3.3 |
| **引用**卡片仍不行 | 扫描 Reply.chain | 0.3.4 |
| 长视频评论被截断 | 段落感知截断 | 0.3.1 |

遗留：无阻塞问题。

### P2-1 每 BV single-flight（✅ 已完成）

**目标**：同一 `bvid + page` 同时被多个会话请求时，只执行一次抓取/子代理，其他请求等待并复用结果。

**实现要点**

- 新增 `VideoInflight`/锁表：`asyncio.Lock` + 结果 Future，键 `f"{bvid}:{page}"`；
- 锁只包住「抓取 + 摘要」，不包 ack 和主模型回复；
- 第二个请求等待后：
  - 优先读 `NoteCache`；
  - 没有缓存则复用一个 `Material`/摘要，但按会话写入 `MaterialStore`；
- 锁超时/异常时释放，避免死锁；
- 日志：`single-flight wait` / `single-flight reuse` / 耗时。

**验收**

- 两个会话同时看同一 BV，B 站 `view/player/reply/playurl` 请求次数不翻倍；
- 第二个会话不重复调用子代理；
- 失败时两个会话都收到结构化失败状态，不卡死。

### P2-2 风控退避（✅ 已完成）

**目标**：B 站 412/风控时不再固定短间隔重试。

**实现要点**

- `BiliHTTP`/`BiliClient` 增加可配置退避：412、429、-352 等使用指数退避（如 1s→2s→4s，带抖动）；
- 区分「可重试」和「不可重试」（404/参数错误不重试）；
- UP 近期投稿现有 3 次重试迁移到统一退避；
- 日志记录每次重试的状态码、等待时间；
- 避免多个任务同时重试：可在插件层加全局退避时间窗。

**验收**

- 模拟连续 412，请求间隔按指数增长且不超过上限；
- 不出现固定 0.6s 连打；
- 日志可看出「第几次重试、等待多久」。

### P2-3 测试补齐（✅ 已完成）

**目标**：P1/P2 新路径有离线回归，尽量不依赖网络。

**清单**

- `MaterialStore` TTL 过期（可注入时钟或直接改内部时间）；
- `bilibili_ask`：无材料、bvid 不匹配、provider 缺失、超时；
- `bilibili_frame`：非法时间点、超时长、无帧、路径越界；
- `get_video` 的 `stat` 解析、`get_comments` 的置顶；
- `get_up_profile`：官方成功 / 回落第三方 / 全失败；
- `truncate_digest`：长文本保留观众观点/不确定项；
- HTTP mock：用 monkeypatch 替换 `BiliHTTP.get_json/request`，测试不联网。

**验收**

- `python tests/test_offline.py`、`test_trigger.py`、`test_waiting.py` 全绿；
- 新增用例覆盖上述分支；
- 测试不依赖真实 SESSDATA。

### P2-4 文档与发布流程（🟡 文档已完成，市场发布/真实回归待做）

- README FAQ：
  - SESSDATA 失效/风控；
  - 412 与第三方兜底；
  - 缓存版本升级后「要重新看一次」；
  - `bilibili_ask` / `bilibili_frame` 使用示例。
- 版本流程固定：改代码 → CHANGELOG/SPEC/PROGRESS → 测试 → 安装 → git tag；
- 评估 AstrBot Cloud 插件市场发布材料（图标、简介、配置截图）；
- 发布前真实机器人回归：看视频 → 追问 → 截图 → UP 主页 → `/stop`。

**验收**：文档可直接给新用户看；发布检查表可执行。

### P2-5 可选增强（⏳ 未开始，不阻塞发布）

- F6：字幕高信息段参与选帧，改善无弹幕视频；
- F3：音频转录接口桩（只留接口，不实现 ASR）；
- 联系图每格标时间点，减少子模型对时间的误判；
- 长视频（>30 分钟）自适应增加 `digest_max_chars` 或分段摘要。

## 3. 技术设计要点

### single-flight 与缓存关系

```
请求 A ──┐
请求 B ──┴─> inflight[bvid:p] 首次执行
              ├─ 成功：写 NoteCache + MaterialStore
              └─ 失败：记录错误，释放锁
请求 B 等待结束 → 读 NoteCache / MaterialStore → 回复
```

- 锁表在插件内存，`terminate` 时清空；
- 不能把 `asyncio.Lock` 放在线程池里；只在事件循环层持有；
- 子代理调用仍走 `_semaphore` 全局并发 2。

### 退避策略

- 仅对 412/429/-352 重试；
- 重试次数最多 3；
- 基础等待 1s，指数 + 抖动，总等待上限例如 8s；
- 失败后把「风控」结构化状态交给主模型，不暴露堆栈。

## 4. 完成定义（DoD）

- 同一 BV 并发只抓一次、只跑一次子代理；
- 412 有退避且日志可追踪；
- 新增测试覆盖 P1/P2 主要分支；
- README/CHANGELOG/SPEC/PROGRESS 同步；
- 真实机器人回归通过，打 tag `v0.3.2`（或按改动决定版本号）。
