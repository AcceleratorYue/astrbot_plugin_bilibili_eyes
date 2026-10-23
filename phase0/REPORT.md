# Phase 0 验证报告

日期：2026-10-22
测试视频：`BV1AHnB6NEhM`《影之刃零》最终预告（191s，单 P）
环境：`astrbot` venv（Python 3.12）、`imageio-ffmpeg` 静态二进制、AstrBot 4.29.1

## 1. B 站接口直连

| 项 | 结果 | 耗时 | 备注 |
| --- | --- | --- | --- |
| `view` 视频信息 | ✅ code=0 | ~0.3s | 标题/UP/时长/分P 正常 |
| WBI 签名 | ✅ | ~0.3s | nav 取 img/sub key + mixin 重排，签名可用 |
| `player/wbi/v2` | ✅ code=0 | ~0.3s | 同时返回 `view_points`（本视频 0 个） |
| 弹幕 XML（`x/v1/dm/list.so`） | ✅ 1200 条 | ~0.3s | 响应是 **deflate** 压缩，需 `zlib.decompress`；pbp 旧接口已 404 |
| 评论（`x/v2/reply` 旧接口） | ✅ code=0 | ~0.3s | 游客只返回 3 条；登录后可翻页拿更多 |
| 取流（`player/wbi/playurl`） | ✅ code=0 | ~0.3s | 游客最高 360P；登录可 480P/720P |

### 字幕

- 接口 `player/wbi/v2` 正常（code=0），但本视频 `subtitle.subtitles` 为空，且响应含 `need_login_subtitle`。
- 结论：**B 站 CC/AI 字幕需要登录态（SESSDATA）**；无登录时按 SPEC 降级为「画面 + 简介 + 评论」并在笔记标注无字幕。
- 音频转录保持为配置项 + 函数桩（默认关），Phase 1 不实现。

### 热点时间点

- `pbp/data` 接口（文档里的高能进度条）已 **404**，`bvc.bilivideo.com` 同样 404；
- `player/v2` 的 `view_points` 本视频为 0（部分视频才有）；
- **可行方案**：下载弹幕 XML，按时间分桶算密度（本视频 step=3s，峰值如 3s/6s/9s/12s），作为热点时间点来源之一；
- 最终选点策略（Phase 1 实现）：`view_points`（有则用）→ 弹幕密度峰值 → 字幕高信息段（有字幕时）→ 均匀保底，去重后凑满 12 帧。

## 2. 截帧

| 项 | 结果 |
| --- | --- |
| 取流 | 游客 360P DASH，可正常拉流 |
| ffmpeg | `imageio_ffmpeg` 静态二进制可用，无需系统安装 |
| 单帧耗时 | **0.77 ~ 1.10s**（HTTP 直接 seek） |
| 单帧大小 | 13 ~ 47 KB（480P 缩放到高 480） |
| 12 帧总耗时 | **约 11s** |
| 联系图 | 4×3 联系图生成正常（Pillow） |

## 3. deepseek-flash 原生视觉

同一组 12 帧，两种输入方式：

| 输入 | 图片数 | 耗时 | prompt tokens | completion tokens | total | 质量观察 |
| --- | --- | --- | --- | --- | --- | --- |
| 12 帧原图 | 12 | **11.97s** | **3415** | 2368（含 reasoning 1550） | 5783 | 能逐帧描述人物/场景/文字，细节较准 |
| 4×3 联系图 | 1 | **11.66s** | **586** | 2224（含 reasoning 1534） | 2810 | 整体概括可以，细节弱于单帧 |

结论：

1. **12 帧原图完全可行**：prompt 仅 3.4k tokens，图片成本远低于预期；
2. 主要成本在 **completion / reasoning**（`reasoning_effort=low` 已设，仍有约 1.5k reasoning tokens）；
3. 50 帧以内都会受 completion 限制，**12 帧是合理默认值**；
4. **子代理默认 12 帧原图**；联系图留给「主模型按需附图/用户要截图」场景（1 张图 586 tokens，很省）；
5. 子代理调用 `max_tokens` 需给够（本次 6000），否则会被 reasoning 吃满导致正文截断；
6. 单次观看预估：抓取 ~2s + 截帧 ~11s + 子代理 ~12s ≈ **25s 左右**，等待提示确有必要。

## 4. 风险 / 需要调整项

| 项 | 状态 | 处理 |
| --- | --- | --- |
| 字幕需要登录 | 未解决 | 需要用户在配置里填 `SESSDATA`；无字幕走降级路径 |
| pbp 接口 404 | 已规避 | 改用弹幕 XML 密度 + view_points + 字幕密度 |
| 游客评论只有 3 条 | 待登录验证 | 登录后 `reply/wbi/main` 翻页；Phase 1 用登录态测试 |
| 游客 360P | 可接受 | 关键帧 480P 缩放后足够子代理辨认；登录可提高 |
| 12 帧 + reasoning 成本 | 可接受 | 默认 reasoning_effort=low；缓存笔记后重复观看近乎 0 成本 |
| 单次约 25s | 需产品化 | 等待提示 + 后台任务 + 阶段上报 |

## 5. 对 SPEC 的修订

- F6 热点来源由「pbp 心跳图」改为：**弹幕密度（XML）+ `view_points` + 字幕高信息段 + 均匀保底**；
- 字幕路径明确依赖 `SESSDATA`（`need_login_subtitle`）；
- 子代理 `max_tokens` 建议 6000、`reasoning_effort=low`；
- 12 帧原图为默认（`subagent_frame_mode=individual`），联系图用于按需附图；
- Phase 1 需拿到 SESSDATA 才能完整验证字幕/评论链路。

## 6. 下一步（Phase 1 范围）

1. 插件骨架 + 配置 schema；
2. 链接识别 + 指令 + 触发/等待提示；
3. B 站数据层（view / player / 弹幕 / 评论 / 取流 / 截帧）；
4. 子代理 `llm_generate` + 笔记 schema + 主模型工具；
5. 用本报告同款视频跑通端到端，再测有字幕视频（需 SESSDATA）。
