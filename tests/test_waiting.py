"""等待提示的离线测试（不依赖 B 站/LLM）。"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

import main as plugin_main  # noqa: E402


class FakeEvent:
    def __init__(self):
        self.unified_msg_origin = "test:GroupMessage:1"
        self.is_at_or_wake_command = True
        self.message_str = "看看这个视频 BV1AHnB6NEhM"
        self.sent = []
        self._stopped = False
        self._extras = {}

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def set_extra(self, key, value):
        self._extras[key] = value

    def stop_event(self):
        self._stopped = True

    async def send(self, chain):
        self.sent.append(chain)


def make_plugin(overrides=None):
    plugin = object.__new__(plugin_main.BilibiliEyesPlugin)
    plugin._config = {**plugin_main.DEFAULT_OPTIONS, **(overrides or {})}
    plugin._active = {}
    plugin._wait_at = {}
    return plugin


async def run() -> int:
    plugin = make_plugin()
    event = FakeEvent()
    plugin._active[event.unified_msg_origin] = plugin_main.Job(
        started=time.monotonic() - 42,
        stage="截帧",
        bvid="BV1xx",
        title="测试视频",
    )
    await plugin.on_waiting(event)
    assert event._stopped is True
    assert len(event.sent) == 1
    text = "".join(getattr(c, "text", "") for c in event.sent[0].chain)
    assert "42 秒" in text and "截帧" in text, text
    print("✅ 等待提示：", text)

    # 冷却内第二次不发送
    event2 = FakeEvent()
    await plugin.on_waiting(event2)
    assert len(event2.sent) == 0
    print("✅ 等待提示冷却生效")

    # 关闭等待提示
    off = make_plugin({"wait_notice_enabled": False})
    off._active[event2.unified_msg_origin] = plugin_main.Job(
        started=time.monotonic(), stage="取信息"
    )
    event3 = FakeEvent()
    await off.on_waiting(event3)
    assert not event3.sent and not event3._stopped
    print("✅ 关闭开关后不发提示")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
