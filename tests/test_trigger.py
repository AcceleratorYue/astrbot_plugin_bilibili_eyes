"""触发/命令/注入/等待隔离的离线测试（不依赖网络与 LLM）。"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

import main as plugin_main  # noqa: E402


class FakeEvent:
    def __init__(self, text: str):
        self.message_str = text
        self.unified_msg_origin = "test:GroupMessage:1"
        self.is_at_or_wake_command = True
        self._stopped = False
        self.results = []
        self.sent = []
        self.extras = {}
        self.call_llm = False
        self.admin = False

    def is_admin(self):
        return self.admin

    def should_call_llm(self, value):
        self.call_llm = value

    def get_group_id(self):
        return "1"

    def get_sender_id(self):
        return "10001"

    def stop_event(self):
        self._stopped = True

    def plain_result(self, text):
        self.results.append(text)
        return text

    def set_extra(self, key, value):
        self.extras[key] = value

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    async def send(self, chain):
        self.sent.append(chain)

    def sent_text(self) -> str:
        texts = []
        for chain in self.sent:
            for comp in getattr(chain, "chain", []):
                text = getattr(comp, "text", "")
                if text:
                    texts.append(text)
        return "".join(texts)


def make_plugin():
    plugin = object.__new__(plugin_main.BilibiliEyesPlugin)
    plugin._config = {**plugin_main.DEFAULT_OPTIONS, "cache_enabled": False}
    plugin._active = {}
    plugin._wait_at = {}
    plugin._cooldown = {}
    plugin._quota = {}
    plugin._semaphore = asyncio.Semaphore(1)
    plugin._cache = None
    plugin._materials = plugin_main.MaterialStore(1800, 20)
    plugin._video_locks = {}
    plugin._video_results = {}
    plugin._session_materials = {}
    plugin._pending = {}
    plugin._sessdata_warned = set()
    return plugin


async def run() -> int:
    # 1) /看主页 命令只登记任务，不 stop、不直接产出消息
    plugin = make_plugin()
    event = FakeEvent("看主页 2431982")
    async for _ in plugin.cmd_up(event):
        pass
    pending = plugin._pending.get(event.unified_msg_origin, {})
    assert pending.get("kind") == "up" and pending.get("query") == "2431982", pending
    assert event._stopped is False and not event.results
    print("✅ /看主页 命令登记 pending")

    # 1b) UID 输入宽容
    for raw in (
        "看主页 uid:2431982",
        "看主页 uid：2431982",
        "看主页 UID:2431982",
        "看主页 UID： 2431982",
        "看主页 uid 2431982",
        "看主页 uid2431982",
    ):
        p = make_plugin()
        e = FakeEvent(raw)
        async for _ in p.cmd_up(e):
            pass
        pending = p._pending.get(e.unified_msg_origin, {})
        assert pending.get("query") == "2431982", (raw, pending)
    print("✅ /看主页 UID 前缀/冒号/空格/大小写宽容")

    # 2) on_llm_request 注入 + 开始提示（ack）
    async def fake_prepare(event, pending, job):
        return "<up_profile>\nfake-up\n</up_profile>"

    plugin._prepare_up = fake_prepare
    req = SimpleNamespace(prompt="用户：看看这个 UP")
    await plugin.on_llm_request(event, req)
    assert "<up_profile>" in req.prompt and "用户：看看这个 UP" in req.prompt
    assert not plugin._pending and not plugin._active
    assert event._stopped is False
    assert "我去翻一下这个 UP 的主页" in event.sent_text(), event.sent_text()
    print("✅ on_llm_request 注入 + ack，且不 stop")

    # 2b) 30 分钟内的追问会再次注入摘要
    plugin_follow = make_plugin()
    event_follow = FakeEvent("刚刚那个视频的置顶评论是啥？")
    plugin_follow._session_materials[event_follow.unified_msg_origin] = {
        "kind": "video",
        "digest": "摘要：这是一个游戏预告",
        "bvid": "BV1AHnB6NEhM",
        "pinned": ["一键直达 Steam 预购：https://b23.tv/example"],
        "created": time.time(),
    }
    follow_req = SimpleNamespace(prompt="用户：刚刚那个视频的置顶评论是啥？")
    await plugin_follow.on_llm_request(event_follow, follow_req)
    assert "一键直达 Steam 预购" in follow_req.prompt
    assert "<video_observation>" in follow_req.prompt
    unrelated = FakeEvent("今天晚饭吃什么")
    unrelated_req = SimpleNamespace(prompt="用户：今天晚饭吃什么")
    await plugin_follow.on_llm_request(unrelated, unrelated_req)
    assert "一键直达 Steam 预购" not in unrelated_req.prompt
    print("✅ 追问注入（30 分钟内）且不污染无关消息")

    # 3) 自然语言视频触发
    plugin2 = make_plugin()
    event2 = FakeEvent("看看这个视频 BV1AHnB6NEhM")
    await plugin2.on_message(event2)
    pending = plugin2._pending.get(event2.unified_msg_origin, {})
    assert pending.get("kind") == "video" and pending.get("ref") == "BV1AHnB6NEhM", pending
    assert event2._stopped is False
    print("✅ 自然语言视频触发登记 pending")

    # 3b) QQ 小程序卡片转链后登记 pending
    plugin_card = make_plugin()
    event_card = FakeEvent("")
    event_card.message_obj = SimpleNamespace(
        raw_message={
            "meta": {
                "detail_1": {"qqdocurl": "https://b23.tv/AbCdEf"}
            }
        },
        message=[],
    )
    await plugin_card.on_message(event_card)
    card_pending = plugin_card._pending.get(event_card.unified_msg_origin, {})
    assert "AbCdEf" in str(card_pending.get("ref")), card_pending
    print("✅ QQ小程序卡片转链触发")

    # 4) 指令消息不会被自然语言分支重复登记
    plugin3 = make_plugin()
    event3 = FakeEvent("看主页 2431982")
    await plugin3.on_message(event3)
    assert not plugin3._pending
    print("✅ 指令消息不被自然语言分支重复登记")

    # 4b) UP 主不再支持自然语言触发
    plugin3b = make_plugin()
    for text in ("这个 up 主叫啥名字", "看看这个 UP 的主页", "space.bilibili.com/2431982"):
        event3b = FakeEvent(text)
        await plugin3b.on_message(event3b)
        assert not plugin3b._pending, text
    print("✅ UP 主自然语言触发已移除（仅限 /看主页）")

    # 5) 无活跃任务时不发/不拦等待提示
    plugin4 = make_plugin()
    event4 = FakeEvent("在吗")
    await plugin4.on_waiting(event4)
    assert not event4.sent and not event4._stopped
    print("✅ 无活跃任务时不提示")

    # 6) 有活跃任务时，系统核心指令（/stop、/stats 等白名单）放行
    event5 = FakeEvent("stop")
    plugin4._active[event5.unified_msg_origin] = plugin_main.Job(
        started=0, stage="查UP主页", up=True
    )
    plugin4._wait_at.clear()
    await plugin4.on_waiting(event5)
    assert not event5.sent and not event5._stopped, "核心指令不能被等待提示拦截"
    event_stats = FakeEvent("stats")
    await plugin4.on_waiting(event_stats)
    assert not event_stats.sent and not event_stats._stopped
    print("✅ /stop、/stats 等核心指令放行")

    # 7) 有活跃任务时，普通聊天也要拦截并提示（避免并发）
    event6 = FakeEvent("你好呀")
    plugin4._active[event6.unified_msg_origin] = plugin_main.Job(
        started=0, stage="取信息"
    )
    plugin4._wait_at.clear()
    await plugin4.on_waiting(event6)
    assert event6._stopped and "还在看呢" in event6.sent_text(), event6.sent_text()
    print("✅ 普通聊天被拦截并提示")

    # 8) 非核心指令（例如 /看视频）同样拦截并提示
    event7 = FakeEvent("看视频 BV1AHnB6NEhM")
    plugin4._active[event7.unified_msg_origin] = plugin_main.Job(
        started=0, stage="查UP主页", up=True
    )
    plugin4._wait_at.clear()
    await plugin4.on_waiting(event7)
    assert event7._stopped and "还在看呢" in event7.sent_text(), event7.sent_text()
    print("✅ 非核心指令被拦截并提示")

    # 9) 冷却期内只拦截不重复提示
    event8 = FakeEvent("再问一句")
    plugin4._active[event8.unified_msg_origin] = plugin_main.Job(
        started=0, stage="取信息"
    )
    sent_before = len(event8.sent)
    await plugin4.on_waiting(event8)
    assert event8._stopped and len(event8.sent) == sent_before
    print("✅ 冷却期内只拦截不刷屏")

    # 10) /bili状态：未配置 / 有效 / 失效
    class FakeClient:
        def __init__(self, status):
            self.status = status

        def check_login(self):
            return self.status

    plugin5 = make_plugin()
    event9 = FakeEvent("bili状态")
    await plugin5.cmd_bili_status(event9)
    assert "未配置 SESSDATA" in event9.sent_text()
    assert event9._stopped is True

    plugin5._config["sessdata"] = "fake"
    plugin5._client = lambda: FakeClient(
        plugin_main.bc.LoginStatus(is_login=True, uid=123, uname="测试UP")
    )
    event10 = FakeEvent("bili状态")
    await plugin5.cmd_bili_status(event10)
    assert "有效" in event10.sent_text() and "123" in event10.sent_text()

    plugin5._client = lambda: FakeClient(
        plugin_main.bc.LoginStatus(is_login=False, message="账号未登录")
    )
    event11 = FakeEvent("bili状态")
    await plugin5.cmd_bili_status(event11)
    assert "无效" in event11.sent_text()
    print("✅ /bili状态 未配置/有效/失效三种情况（直接发送）")

    # 12) 未配置 SESSDATA 时，开始提示只提醒一次
    plugin7 = make_plugin()
    event13 = FakeEvent("看视频 BV1AHnB6NEhM")
    await plugin7._send_ack(event13, {"kind": "video"})
    assert "未配置 SESSDATA" in event13.sent_text()
    event14 = FakeEvent("看视频 BV1AHnB6NEhM")
    await plugin7._send_ack(event14, {"kind": "video"})
    assert "未配置 SESSDATA" not in event14.sent_text()
    print("✅ SESSDATA 未配置提醒（每会话一次）")

    # 13) 每日额度：管理员豁免 + 用户白名单
    plugin_q = make_plugin()
    plugin_q._config = {
        **plugin_q._config,
        "user_daily_quota": 1,
        "quota_exempt_admins": True,
        "quota_exempt_users": ["10002"],
    }
    admin_event = FakeEvent("看视频 BV1AHnB6NEhM")
    admin_event.admin = True
    assert plugin_q._quota_ok(admin_event) and plugin_q._quota_ok(admin_event)
    normal_event = FakeEvent("看视频 BV1AHnB6NEhM")
    assert plugin_q._quota_ok(normal_event)
    assert not plugin_q._quota_ok(normal_event)
    exempt_event = FakeEvent("看视频 BV1AHnB6NEhM")
    exempt_event.get_sender_id = lambda: "10002"
    assert plugin_q._quota_ok(exempt_event) and plugin_q._quota_ok(exempt_event)
    print("✅ 每日额度：管理员/白名单豁免")

    # 14) 同一 BV+page 并发只抓一次、只跑一次子代理
    plugin_sf = make_plugin()
    counts = {"collect": 0, "digest": 0}

    async def fake_collect(job, ref, page):
        counts["collect"] += 1
        await asyncio.sleep(0.05)
        return SimpleNamespace(video=SimpleNamespace(bvid=ref, page=page))

    async def fake_digest(material, event):
        counts["digest"] += 1
        return "摘要"

    plugin_sf._collect = fake_collect
    plugin_sf._digest = fake_digest
    job_sf = SimpleNamespace()
    results = await asyncio.gather(
        plugin_sf._collect_video_once(job_sf, FakeEvent(""), "BV1single", 1),
        plugin_sf._collect_video_once(job_sf, FakeEvent(""), "BV1single", 1),
    )
    assert counts == {"collect": 1, "digest": 1}, counts
    assert all(result[1] == "摘要" for result in results)
    print("✅ single-flight：并发只抓一次")

    # 15) 下游桥接：get_last_video 只返回 30 分钟内的视频目标
    plugin_bridge = make_plugin()
    material = SimpleNamespace(
        video=SimpleNamespace(
            bvid="BV1bridge",
            aid=111,
            cid=222,
            page=1,
            title="桥接测试",
            up_uid=333,
            up_name="UP",
        )
    )
    plugin_bridge._materials.put("bridge:umo", material, "digest")
    plugin_bridge._session_materials["bridge:umo"] = {
        "kind": "video",
        "bvid": "BV1bridge",
        "page": 1,
        "title": "桥接测试",
        "created": time.time(),
        "digest": "digest",
    }
    target = plugin_bridge.get_last_video("bridge:umo")
    assert target and target["aid"] == 111 and target["cid"] == 222
    assert target["title"] == "桥接测试" and target["digest"] == "digest"
    plugin_bridge._session_materials["bridge:umo"]["kind"] = "up"
    assert plugin_bridge.get_last_video("bridge:umo") is None
    plugin_bridge._session_materials["bridge:umo"]["kind"] = "video"
    plugin_bridge._session_materials["bridge:umo"]["created"] = time.time() - 1900
    assert plugin_bridge.get_last_video("bridge:umo") is None
    print("✅ 下游桥接：只返回 30 分钟内的视频目标")

    source = (PLUGIN_DIR / "main.py").read_text(encoding="utf-8")
    assert "asyncio.to_thread(" not in source, "不应再使用默认线程池"
    assert "ThreadPoolExecutor" in source and "def _run(" in source
    assert "bilibili_up" not in source, "UP 工具应移除，只保留 /看主页 指令"
    assert "自然地说出 UP 主名字" in source
    assert "不要主动报 UID" in source
    print("✅ 阻塞调用全部走插件独立线程池；UP 仅指令")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
