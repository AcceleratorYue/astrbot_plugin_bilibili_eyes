"""Phase 0 验证用：极简 WBI 签名实现（不依赖第三方库）。"""

from __future__ import annotations

import hashlib
import time
import urllib.parse
import urllib.request

MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def http_get_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20):
    h = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        import json

        return json.loads(resp.read().decode("utf-8"))


def get_wbi_keys() -> tuple[str, str]:
    data = http_get_json("https://api.bilibili.com/x/web-interface/nav")
    img_url = data["data"]["wbi_img"]["img_url"]
    sub_url = data["data"]["wbi_img"]["sub_url"]
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    return img_key, sub_key


def get_mixin_key(img_key: str, sub_key: str) -> str:
    orig = img_key + sub_key
    return "".join(orig[index] for index in MIXIN_KEY_ENC_TAB)[:32]


def sign(params: dict[str, str | int], img_key: str, sub_key: str) -> dict[str, str | int]:
    signed = dict(params)
    signed["wts"] = int(time.time())
    signed = {
        key: "".join(ch for ch in str(value) if ch not in "!'()*")
        for key, value in signed.items()
    }
    query = urllib.parse.urlencode(sorted(signed.items()))
    mixin_key = get_mixin_key(img_key, sub_key)
    signed["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return signed


def sign_url(base: str, params: dict[str, str | int], img_key: str, sub_key: str) -> str:
    signed = sign(params, img_key, sub_key)
    return f"{base}?{urllib.parse.urlencode(sorted(signed.items()))}"


def get_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20):
    return http_get_json(url, headers=headers, timeout=timeout)
