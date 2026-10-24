# 发布检查表

> 当前版本：0.5.6（提示词自定义）
> 适用：每次改代码后的版本发布。

## 1. 改代码

- [ ] 功能/修复完成，未提交的调试代码已清理；
- [ ] 没有把 SESSDATA、QQ 号、临时路径写进仓库；
- [ ] 新配置有默认值、schema、README 说明；
- [ ] 版本号在 `metadata.yaml` / `main.py` 日志 / 测试断言三处一致。

## 2. 文档

- [ ] `CHANGELOG.md` 增加当前版本条目；
- [ ] `docs/SPEC.md` 记录行为变化；
- [ ] `docs/PROGRESS.md` 更新版本与完成项；
- [ ] `docs/ROADMAP.md` 标记本轮任务状态；
- [ ] `README.md` 配置/FAQ/限制同步。

## 3. 测试

```bash
python -m py_compile main.py eyes_client.py eyes_subagent.py eyes_wbi.py eyes_cache.py eyes_card.py
python tests/test_offline.py
python tests/test_trigger.py
python tests/test_waiting.py
```

- [ ] 全部离线测试通过；
- [ ] 需要时跑 `tests/test_live_pipeline.py`（真实 B 站 + provider）；
- [ ] 机器人内回归：看视频 → 追问 → 截图 → UP 主页 → `/stop`。

## 4. 安装与版本

```powershell
# 同步到 AstrBot 插件目录（按实际路径）
Copy-Item main.py,eyes_client.py,eyes_subagent.py,eyes_wbi.py,eyes_cache.py,eyes_card.py,metadata.yaml,_conf_schema.json,README.md,CHANGELOG.md,requirements.txt `
  D:\QQbot\astrbot\data\plugins\astrbot_plugin_bilibili_eyes -Force
```

- [ ] 重载插件，日志版本号正确；
- [ ] `/bili状态` 正常；
- [ ] git 提交 + `git tag v<version>`；
- [ ] 如发布到 AstrBot Cloud，附图标、简介、配置截图。
