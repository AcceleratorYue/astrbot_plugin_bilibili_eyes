"""Phase 1 端到端联调（手动运行，走真实 B 站 + 真实 deepseek-flash 视觉）。

不依赖 QQ/AstrBot 运行时：用 stub context 注入 llm_generate（内部直接调 DeepSeek API）。
用法：
    python tests/test_live_pipeline.py [BV号]
"""

from __future__ import annotations

import asyncio
import base64
import glob
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve()
PLUGIN_DIR = HERE.parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

import main as plugin_main  # noqa: E402


def load_key() -> tuple[str, str, str]:
    path = glob.glob(r"D:\QQbot\astrbot\data\config\abconf_*.json")[0]
    cfg = json.load(open(path, encoding="utf-8-sig"))
    sources = {item.get("id"): item for item in cfg.get("provider_sources", [])}
    providers = {item.get("id"): item for item in cfg.get("provider", [])}
    source = sources["deepseek_source"]
    provider = providers["deepseek"]
    key = source.get("key")
    if isinstance(key, (list, tuple)):
        key = key[0]
    return key, source.get("api_base"), provider.get("model", "deepseek-flash")


KEY, API_BASE, MODEL = load_key()


def image_part(path: Path) -> dict:
    data = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{data}", "detail": "auto"},
    }


class FakeProvider:
    provider_config = {"id": "deepseek", "modalities": ["text", "image"]}


class FakeContext:
    def get_using_provider(self, umo=None):
        return FakeProvider()

    async def llm_generate(
        self,
        *,
        chat_provider_id,
        prompt,
        image_urls,
        system_prompt,
        request_max_retries=1,
        **kwargs,
    ):
        content = [{"type": "text", "text": prompt or ""}]
        for path in image_urls or []:
            content.append(image_part(Path(path)))
        payload = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system_prompt or ""},
                {"role": "user", "content": content},
            ],
            "max_tokens": 6000,
            "reasoning_effort": "low",
        }
        req = urllib.request.Request(
            f"{API_BASE.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {KEY}",
            },
            method="POST",
        )
        started = time.time()
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        print(
            f"  [subagent] {time.time() - started:.1f}s "
            f"prompt={data.get('usage', {}).get('prompt_tokens')} "
            f"completion={data.get('usage', {}).get('completion_tokens')}"
        )
        return SimpleNamespace(completion_text=text)


class FakeEvent:
    def __init__(self, text: str):
        self.message_str = text
        self.unified_msg_origin = "test:GroupMessage:123456"
        self.is_at_or_wake_command = True
        self._stopped = False
        self.requests = []

    def get_group_id(self):
        return "123456"

    def get_sender_id(self):
        return "10001"

    def stop_event(self):
        self._stopped = True

    async def send(self, chain):
        pass

    def request_llm(self, prompt: str):
        self.requests.append(prompt)
        return {"type": "provider_request", "prompt": prompt}


async def main() -> int:
    bvid = sys.argv[1] if len(sys.argv) > 1 else "BV1AHnB6NEhM"
    plugin = object.__new__(plugin_main.BilibiliEyesPlugin)
    plugin._config = {
        **plugin_main.DEFAULT_OPTIONS,
        "cache_enabled": False,
        "frame_count": 12,
    }
    plugin._active = {}
    plugin._wait_at = {}
    plugin._cooldown = {}
    plugin._quota = {}
    plugin._semaphore = asyncio.Semaphore(1)
    plugin._executor = ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="bili-test"
    )
    plugin._cache = None
    plugin._session_materials = {}
    plugin._pending = {}
    plugin.context = FakeContext()
    event = FakeEvent(f"@bot 看看这个视频 https://www.bilibili.com/video/{bvid}")
    plugin._pending[event.unified_msg_origin] = {
        "kind": "video",
        "refs": [bvid],
        "ref": bvid,
        "page": None,
        "ignored": 0,
    }
    req = SimpleNamespace(prompt="用户：看看这个视频")
    started = time.time()
    await plugin.on_llm_request(event, req)
    elapsed = time.time() - started
    print(f"\n总耗时: {elapsed:.1f}s | 事件停止: {event._stopped}")
    prompt = req.prompt or ""
    if prompt:
        print("\n=== 主模型提示词（前 1600 字） ===")
        print(prompt[:1600])
        (PLUGIN_DIR / "_live_prompt.txt").write_text(prompt, encoding="utf-8")
        print("\n完整提示词已写入 _live_prompt.txt")
    plugin._executor.shutdown(wait=False, cancel_futures=True)
    return 0 if "video_observation" in prompt else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
