# 发布到 AstrBot 插件市场

> 状态：GitHub 仓库与 v0.5.11 Release 已就绪，等待在 AstrBot Cloud 网页提交。
> 官方说明：<https://docs.astrbot.app/dev/star/plugin-publish.html>

## 已完成

- GitHub 仓库：<https://github.com/AcceleratorYue/astrbot_plugin_bilibili_eyes>
- v0.5.11 Release：
  <https://github.com/AcceleratorYue/astrbot_plugin_bilibili_eyes/releases/tag/v0.5.11>
- Release 附件：`astrbot_plugin_bilibili_eyes-0.5.11.zip`（约 111 KB，远低于 16 MB 限制）
- `metadata.yaml` 已包含：
  - `name` / `display_name` / `short_desc` / `desc`
  - `version: 0.5.11`
  - `author` / `repo` / `social_link`
  - `astrbot_version` / `support_platforms` / `tags`

## 在 AstrBot Cloud 提交

1. 打开 <https://cloud.astrbot.app/publish>；
2. 使用 GitHub 账号登录并授权 AstrBot Cloud GitHub App；
3. 选择 `AcceleratorYue/astrbot_plugin_bilibili_eyes`；
4. 选择版本 `v0.5.11`；
5. 分类建议：**工具**（或 **娱乐**，看市场分类更贴合哪个）；
6. 确认自动解析的 `metadata.yaml` 信息；
7. 提交审核/发布。

## 发布前检查

- [ ] 仓库 public，README 完整；
- [ ] `metadata.yaml` 的 `repo` 指向正确仓库；
- [ ] Release 附件 < 16 MB；
- [ ] 不包含 SESSDATA、Cookie、QQ 号、日志；
- [ ] `python tests/test_offline.py` / `test_trigger.py` / `test_waiting.py` 全绿。

## 仓库里不要提交的东西

`.gitignore` 已排除：

- `__pycache__/`、`*.pyc`
- `data/`（本地测试数据）
- `_live_prompt.txt`
- `phase0/out/`
- `dist/`（本地发布包）
- `.venv/`

## 发布后

- 在 AstrBot Cloud 更新版本时，改 `metadata.yaml` 的 `version`，同步 CHANGELOG/SPEC/PROGRESS，重新打 tag；
- 插件市场可能缓存旧版本，更新后确认页面显示的版本号。
