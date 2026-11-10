"""B站扫码登录与凭据持久化。

凭据优先级：
    credentials.json（扫码） > 配置 sessdata > 游客。

二维码只在本地使用 passport 链接生成，不经过第三方二维码服务。
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.api import logger

QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
CREDENTIAL_FILE = "credentials.json"


@dataclass
class QrCodeSession:
    url: str
    qrcode_key: str
    qr_image_path: Path | None = None


@dataclass
class PollResult:
    code: int
    message: str
    credentials: dict[str, str] | None = None


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".credentials-", suffix=".json", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


class CredentialManager:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.file_path = self.data_dir / CREDENTIAL_FILE
        self._cached: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self._cached = {}
        if not self.file_path.is_file():
            return
        try:
            payload = json.loads(self.file_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                self._cached = {
                    str(key): str(value)
                    for key, value in payload.items()
                    if value is not None
                }
        except Exception as exc:
            logger.warning(f"[B站之眼] 读取扫码凭据失败：{type(exc).__name__}")

    def get_sessdata(self) -> str:
        return str(self._cached.get("sessdata") or "").strip()

    def get_refresh_token(self) -> str:
        return str(self._cached.get("refresh_token") or "").strip()

    def has_valid_credential(self) -> bool:
        return bool(self.get_sessdata())

    def summary(self) -> dict:
        sessdata = self.get_sessdata()
        return {
            "present": bool(sessdata),
            "sessdata_tail": f"…{sessdata[-4:]}" if len(sessdata) > 4 else "",
            "updated_at": float(self._cached.get("updated_at") or 0),
        }

    def save(self, credentials: dict[str, str]) -> None:
        sessdata = str((credentials or {}).get("sessdata") or "").strip()
        if not sessdata:
            raise ValueError("扫码结果没有 SESSDATA")
        payload = {str(k): str(v) for k, v in credentials.items() if v}
        payload["sessdata"] = sessdata
        payload["updated_at"] = str(time.time())
        _write_atomic(self.file_path, payload)
        self._cached = payload
        logger.info("[B站之眼] B站扫码凭据已保存")

    def clear(self) -> None:
        self._cached = {}
        try:
            self.file_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"[B站之眼] 删除扫码凭据失败：{exc}")


def _render_qr_png(data: str, out_dir: Path) -> Path | None:
    try:
        import qrcode  # type: ignore
    except ImportError:
        logger.warning("[B站之眼] 未安装 qrcode，扫码登录仅返回文本链接")
        return None
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        digest = re.sub(r"[^A-Za-z0-9]", "", data)[-10:] or str(int(time.time()))
        path = out_dir / f"login_qr_{digest}.png"
        qrcode.make(data).save(path)
        return path
    except Exception as exc:
        logger.warning(f"[B站之眼] 二维码渲染失败：{exc}")
        return None


class BiliQrLoginService:
    def __init__(self, timeout: int = 15):
        self.timeout = max(5, int(timeout))

    def request_qrcode(self, qr_dir: Path | None = None) -> QrCodeSession:
        request = urllib.request.Request(
            QR_GENERATE_URL,
            headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("code") != 0:
            raise RuntimeError(payload.get("message") or "申请二维码失败")
        data = payload.get("data") or {}
        url = str(data.get("url") or "")
        key = str(data.get("qrcode_key") or "")
        if not url or not key:
            raise RuntimeError("二维码返回数据不完整")
        return QrCodeSession(
            url=url,
            qrcode_key=key,
            qr_image_path=_render_qr_png(url, qr_dir) if qr_dir else None,
        )

    def poll_status(self, qrcode_key: str) -> PollResult:
        url = f"{QR_POLL_URL}?{urllib.parse.urlencode({'qrcode_key': qrcode_key})}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("code") != 0:
            return PollResult(code=-1, message=payload.get("message") or "轮询失败")
        data = payload.get("data") or {}
        code = int(data.get("code", -1))
        message = str(data.get("message") or "")
        if code != 0:
            return PollResult(code=code, message=message)
        target = str(data.get("url") or "")
        refresh_token = str(data.get("refresh_token") or "")
        credentials = self._extract_credentials(target, refresh_token)
        return PollResult(code=0, message="登录成功", credentials=credentials)

    def _extract_credentials(
        self, target_url: str, refresh_token: str
    ) -> dict[str, str]:
        cookies: dict[str, str] = {}
        if "crossDomain" in target_url:
            jar = http.cookiejar.CookieJar()
            opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(jar)
            )
            request = urllib.request.Request(
                target_url,
                headers={"User-Agent": UA, "Referer": "https://passport.bilibili.com/"},
            )
            try:
                opener.open(request, timeout=self.timeout)
                for cookie in jar:
                    cookies[cookie.name] = cookie.value
            except Exception as exc:
                logger.warning(f"[B站之眼] 跟随 crossDomain 失败：{exc}")
        if not cookies.get("SESSDATA"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(target_url).query)
            for name in ("SESSDATA", "bili_jct", "DedeUserID", "buvid3"):
                values = query.get(name)
                if values:
                    cookies[name] = values[0]
        return {
            "sessdata": cookies.get("SESSDATA", ""),
            "bili_jct": cookies.get("bili_jct", ""),
            "dedeuserid": cookies.get("DedeUserID", ""),
            "refresh_token": refresh_token,
        }
