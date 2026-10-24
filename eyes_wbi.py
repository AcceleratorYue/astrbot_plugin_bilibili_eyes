"""B 站 WBI 签名与 HTTP 基础（自研，无第三方依赖）。"""

from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import random
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

from astrbot.api import logger

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


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    """只走 IPv4 的 HTTPS 连接。

    B 站域名会先返回一串 IPv6；在没有 IPv6 出口的机器上，urllib 会逐个
    等待超时（8 个地址 × timeout），表现为 nav 一次 40~80 秒。
    """

    def connect(self) -> None:
        last_error: OSError | None = None
        for family, socktype, proto, _canon, addr in socket.getaddrinfo(
            self.host, self.port, socket.AF_INET, socket.SOCK_STREAM
        ):
            sock = socket.socket(family, socktype, proto)
            sock.settimeout(self.timeout)
            try:
                sock.connect(addr)
                self.sock = self._context.wrap_socket(
                    sock, server_hostname=self.host
                )
                return
            except OSError as exc:
                last_error = exc
                sock.close()
        raise last_error or OSError(f"{self.host} 没有可用的 IPv4 地址")


_SSL_CONTEXT = ssl.create_default_context()


class BiliHTTP:
    """同步 HTTP 客户端；插件里通过独立线程池调用。"""

    def __init__(self, sessdata: str = "", user_agent: str = "", interval: float = 0.8):
        self._headers = {
            "User-Agent": user_agent or UA,
            "Referer": "https://www.bilibili.com/",
        }
        if sessdata:
            self._headers["Cookie"] = f"SESSDATA={sessdata}"
        self._interval = max(0.0, interval)
        self._last_request = 0.0
        self._wbi_keys: tuple[str, str] | None = None
        self._wbi_time = 0.0
        self._buvid_ready = False

    def ensure_buvid(self) -> None:
        """获取游客 buvid 指纹；很多搜索/空间接口缺了它会被风控。"""

        if self._buvid_ready:
            return
        try:
            data = self.get_json(
                "https://api.bilibili.com/x/frontend/finger/spi", timeout=8
            )
            b3 = data["data"]["b_3"]
            b4 = data["data"]["b_4"]
            import uuid

            cookie = (
                f"buvid3={b3}; buvid4={b4}; b_nut={int(time.time())}; "
                f"_uuid={uuid.uuid4()}; b_lsid=ABCDEF1234567890"
            )
            existing = self._headers.get("Cookie")
            self._headers["Cookie"] = f"{existing}; {cookie}" if existing else cookie
            self._buvid_ready = True
        except Exception:
            return

    def _throttle(self) -> None:
        if self._interval <= 0:
            return
        delta = time.monotonic() - self._last_request
        if delta < self._interval:
            time.sleep(self._interval - delta)
        self._last_request = time.monotonic()

    def request(
        self, url: str, timeout: int = 20, headers: dict[str, str] | None = None
    ) -> bytes:
        self._throttle()
        merged = dict(self._headers)
        if headers:
            merged.update(headers)
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme == "https":
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            conn = _IPv4HTTPSConnection(
                parsed.hostname,
                parsed.port or 443,
                timeout=timeout,
                context=_SSL_CONTEXT,
            )
            try:
                conn.request("GET", path, headers=merged)
                resp = conn.getresponse()
                status = resp.status
                reason = resp.reason
                resp_headers = resp.headers
                raw = resp.read()
            finally:
                conn.close()
            if status >= 400:
                raise urllib.error.HTTPError(
                    url, status, reason or "HTTP error", resp_headers, None
                )
            encoding = resp_headers.get("Content-Encoding", "")
        else:
            req = urllib.request.Request(url, headers=merged)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                encoding = resp.headers.get("Content-Encoding", "")
        if raw[:2] == b"\x1f\x8b":
            return gzip.decompress(raw)
        if encoding == "deflate" or (raw[:1] not in (b"{", b"[", b"<")):
            try:
                return zlib.decompress(raw)
            except Exception:
                try:
                    return zlib.decompress(raw, -zlib.MAX_WBITS)
                except Exception:
                    return raw
        return raw

    @staticmethod
    def _backoff_delay(attempt: int) -> float:
        return min(4.0, 0.8 * (2**attempt)) + random.uniform(0, 0.3)

    def get_json(
        self,
        url: str,
        timeout: int = 20,
        headers: dict[str, str] | None = None,
        retries: int = 2,
    ) -> dict:
        attempts = max(1, int(retries) + 1)
        for attempt in range(attempts):
            try:
                data = json.loads(
                    self.request(url, timeout=timeout, headers=headers).decode("utf-8")
                )
                if data.get("code") == -352 and attempt < attempts - 1:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        f"B站风控 -352，{delay:.1f}s 后重试 "
                        f"({attempt + 1}/{attempts})"
                    )
                    time.sleep(delay)
                    continue
                return data
            except urllib.error.HTTPError as exc:
                if exc.code in (412, 429) and attempt < attempts - 1:
                    delay = self._backoff_delay(attempt)
                    logger.warning(
                        f"B站 HTTP {exc.code}，{delay:.1f}s 后重试 "
                        f"({attempt + 1}/{attempts}): {url[:120]}"
                    )
                    time.sleep(delay)
                    continue
                raise
        return {}

    def wbi_keys(self) -> tuple[str, str]:
        # nav 的 wbi key 会轮换；缓存太久会导致签名过期、空间接口 412
        if self._wbi_keys and time.monotonic() - self._wbi_time < 30:
            return self._wbi_keys
        data = self.get_json("https://api.bilibili.com/x/web-interface/nav")
        img_url = data["data"]["wbi_img"]["img_url"]
        sub_url = data["data"]["wbi_img"]["sub_url"]
        img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
        sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
        self._wbi_keys = (img_key, sub_key)
        self._wbi_time = time.monotonic()
        return self._wbi_keys

    def wbi_sign(self, params: dict) -> dict:
        img_key, sub_key = self.wbi_keys()
        signed = dict(params)
        signed["wts"] = int(time.time())
        signed = {
            key: "".join(ch for ch in str(value) if ch not in "!'()*")
            for key, value in signed.items()
        }
        query = urllib.parse.urlencode(sorted(signed.items()))
        orig = img_key + sub_key
        mixin_key = "".join(orig[index] for index in MIXIN_KEY_ENC_TAB)[:32]
        signed["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
        return signed

    def wbi_url(self, base: str, params: dict) -> str:
        return f"{base}?{urllib.parse.urlencode(sorted(self.wbi_sign(params).items()))}"

    def absolute(self, url: str) -> str:
        if url.startswith("//"):
            return "https:" + url
        return url
