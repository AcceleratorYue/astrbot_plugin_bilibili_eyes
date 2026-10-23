"""把 QQ 小程序卡片里的 B 站链接转出来，供 /看视频 或自然语言触发使用。

QQ/NapCat 的卡片会放在 raw_message 的 json 段里，常见形态：
{"meta": {"detail_1": {"qqdocurl": "https://b23.tv/..."}}}
这里只提取 B 站域名，避免把卡片里的其它链接当成视频。
"""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any

_ALLOWED_DOMAINS = (
    "bilibili.com",
    "b23.tv",
    "bili22.cn",
    "bili23.cn",
    "bili33.cn",
    "bili2233.cn",
)

CQ_JSON_RE = re.compile(r"\[CQ:json,data=(.*?)\]", re.S)


def _is_bilibili_url(url: str) -> bool:
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower().rstrip(".")
        return any(host == domain or host.endswith("." + domain) for domain in _ALLOWED_DOMAINS)
    except Exception:
        return False


def _find_url(data: Any, depth: int = 0) -> str:
    """递归查找 qqdocurl/url；只接受 B 站域名。"""

    if depth > 8:
        return ""
    if isinstance(data, dict):
        for key in ("qqdocurl", "url", "jumpUrl", "shareUrl"):
            value = data.get(key)
            if isinstance(value, str):
                value = value.replace("&amp;", "&").strip()
            if isinstance(value, str) and value.startswith("http") and _is_bilibili_url(value):
                return value
        for value in data.values():
            found = _find_url(value, depth + 1)
            if found:
                return found
    elif isinstance(data, (list, tuple)):
        for value in data:
            found = _find_url(value, depth + 1)
            if found:
                return found
    elif isinstance(data, str):
        text = data.strip()
        if text.startswith("{") or text.startswith("["):
            return _parse_json(text)
    return ""


def _parse_json(text: str) -> str:
    try:
        return _find_url(json.loads(text))
    except Exception:
        return ""


def _parse_cq(text: str) -> str:
    match = CQ_JSON_RE.search(text)
    if not match:
        return ""
    data = (
        match.group(1)
        .replace("&amp;", "&")
        .replace("&#44;", ",")
        .replace("&#91;", "[")
        .replace("&#93;", "]")
    )
    return _parse_json(data)


def extract_bilibili_card_url(event: Any) -> str:
    """从事件的消息组件/raw_message 中提取 B 站小程序链接。"""

    message_obj = getattr(event, "message_obj", None)
    raw_candidates: list[Any] = []
    if message_obj is not None:
        raw_candidates.append(getattr(message_obj, "raw_message", None))
        for component in getattr(message_obj, "message", None) or []:
            raw_candidates.append(getattr(component, "raw", None))
            raw_candidates.append(getattr(component, "data", None))
    text = str(getattr(event, "message_str", "") or "").strip()
    if text.startswith("{") or "[CQ:json" in text:
        raw_candidates.append(text)

    for raw in raw_candidates:
        if raw is None:
            continue
        if isinstance(raw, str):
            url = _parse_cq(raw) or _parse_json(raw)
        else:
            url = _find_url(raw)
        if url:
            return url
    return ""
