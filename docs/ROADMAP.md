# 下一轮规划：P2（Phase 3 工程化）

> 基线：v0.3.0（P0/P1 已完成，Phase 1/2 闭环）
> 目标：把「能用」变成「稳定、可发布、可回归」。

## 1. P1 完成情况

| 任务 | 状态 | 结果 |
| --- | --- | --- |
| P1-1 材料会话缓存 | ✅ | `MaterialStore` 内存保存 Material/摘要，30 分钟 TTL、20 会话上限 |
| P1-2 `bilibili_frame` | ✅ | 秒/`mm:ss`/`hh:mm:ss`，复用最近帧或按点截取，返回 ImageContent |
| P1-3 `bilibili_ask` | ✅ | 基于会话材料回答追问，不重新抓 B 站 |
| P1-4 联系图 | ✅ | `subagent_frame_mode=contact_sheet_plus`，12 帧拼图省 token |

## 2. P2 目标

### P2-1 限流与稳定性

- 每 BV single-flight：同一视频并发请求只抓一次，其余等待结果；
- 请求失败退避（B 站 412/风控时指数退避，避免连续重试加重风控）；
- 全局并发与插件线程池配合，避免多个任务把 provider 打满；
- 日志补充：耗时、命中缓存/材料、失败原因、single-flight 等待。

**验收**：同一 BV 同时两个会话观看，B 站请求数不翻倍；412 时不会有雪崩式重试。

### P2-2 测试补齐

- `MaterialStore` 过期测试（可用可注入时钟或调小 TTL）；
- UP 主页解析、用户名歧义、`not_found` 分支；
- `bilibili_ask`/`bilibili_frame` 的工具参数校验（缺材料、bvid 不匹配、非法时间点、路径越界）；
- 错误路径：无 provider、无视觉、超时、风控；
- HTTP mock，避免测试必须联网。

**验收**：离线测试覆盖 P1 新增工具的主要分支；`python tests/test_offline.py` 可全绿。

### P2-3 文档与发布

- README 增加「追问/截图」示例、常见问题（SESSDATA 失效、412、第三方兜底、缓存版本）；
- 版本/tag 流程固定：改代码 → 改 CHANGELOG/SPEC/PROGRESS → 测试 → 安装 → tag；
- 评估插件市场发布（AstrBot Cloud）所需材料；
- 发布前做一次真实机器人回归（看视频 → 追问 → 截图 → UP 主页）。

### P2-4 可选增强（不阻塞发布）

- F6：字幕高信息段选帧，提升无弹幕视频的选帧质量；
- F3：音频转录接口桩（保持不实现 ASR，只留可插拔接口）；
- 联系图模式下给每张缩略图标时间点，减少子代理对时间的误判。

## 3. 顺序

1. P2-2 测试补齐（先保证改动可回归）；
2. P2-1 single-flight/退避；
3. P2-3 文档/发布流程；
4. P2-4 可选增强。

## 4. 完成定义

- 同一 BV 并发只抓一次；
- 新工具主要错误分支有测试；
- README/CHANGELOG/SPEC/PROGRESS 同步；
- 真实机器人回归通过，打 tag `v0.3.1`（或按改动决定版本号）。
