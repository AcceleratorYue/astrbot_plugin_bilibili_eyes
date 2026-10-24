"""B 站数据层：视频信息 / 字幕 / 评论 / 弹幕密度 / 取流截帧 / UP 查询。

全部方法为同步实现，插件侧用 asyncio.to_thread 调用，避免阻塞事件循环。
"""

from __future__ import annotations

import base64
import html
import json
import math
import random
import re
import string
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from eyes_clean import (
    danmaku_keywords,
    extract_time_marks,
    is_low_value_comment,
)
from eyes_wbi import UA, BiliHTTP


class BiliError(Exception):
    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")
AV_RE = re.compile(r"av(\d+)", re.IGNORECASE)
SPACE_RE = re.compile(r"space\.bilibili\.com/(\d+)")
URL_RE = re.compile(r"https?://[^\s，。！？、）)】\]]+")
B23_RE = re.compile(r"https?://b23\.tv/[0-9A-Za-z]+")


def extract_video_refs(text: str) -> list[str]:
    """提取视频标识（BV/av/短链），保持出现顺序，去重。"""

    refs: list[str] = []
    for match in BV_RE.finditer(text or ""):
        if match.group(0) not in refs:
            refs.append(match.group(0))
    for match in AV_RE.finditer(text or ""):
        ref = "av" + match.group(1)
        if ref not in refs:
            refs.append(ref)
    for match in B23_RE.finditer(text or ""):
        if match.group(0) not in refs:
            refs.append(match.group(0))
    return refs


def extract_space_refs(text: str) -> list[str]:
    return list(dict.fromkeys(SPACE_RE.findall(text or "")))


def extract_page(text: str) -> int | None:
    match = re.search(r"[?&]p=(\d+)", text or "")
    if match:
        try:
            return max(1, int(match.group(1)))
        except Exception:
            return None
    return None


UID_QUERY_RE = re.compile(r"(?i)^\s*uid\s*[:：]?\s*(\d+)\s*$")


def normalize_up_query(text: str) -> str:
    """宽容解析 UP 查询：uid:123 / uid：123 / UID:123 / uid 123 / uid123 / 123。"""

    value = str(text or "").strip()
    match = UID_QUERY_RE.match(value)
    if match:
        return match.group(1)
    return value


def parse_time_point(value: str | int | float) -> float | None:
    """解析时间点：30 / "30" / "00:30" / "1:02:03"；非法返回 None。"""

    text = str(value or "").strip()
    if not text:
        return None
    try:
        if ":" not in text:
            seconds = float(text)
        else:
            parts = [part.strip() for part in text.split(":")]
            if not 2 <= len(parts) <= 3:
                return None
            numbers = [float(part) for part in parts]
            seconds = 0.0
            for number in numbers:
                seconds = seconds * 60 + number
        if seconds < 0 or seconds != seconds:
            return None
        return round(seconds, 2)
    except Exception:
        return None


@dataclass
class VideoInfo:
    bvid: str
    aid: int
    cid: int
    page: int
    page_count: int
    title: str
    up_name: str
    up_uid: int
    duration: int
    desc: str
    pubdate: int = 0
    views: int = 0
    danmaku: int = 0
    replies: int = 0
    likes: int = 0
    coins: int = 0
    favorites: int = 0
    shares: int = 0


@dataclass
class CommentItem:
    uname: str
    content: str
    like: int
    replies: list[str] = field(default_factory=list)
    pinned: bool = False
    role: str = "audience"
    time_marks: list[str] = field(default_factory=list)


@dataclass
class UpInfo:
    uid: int
    name: str
    sign: str
    level: int
    fans: int
    archives: list[str]
    archive_count: int = 0
    archive_source: str = "official"


# B 站空间接口的风控参数；仿照 yt-dlp 每次随机生成，固定值反而更容易 412
def dm_params() -> dict[str, str]:
    width, height = random.choice(
        ((1920, 1080), (1366, 768), (1536, 864), (1280, 720))
    )
    rnd = math.floor(114 * random.random())
    wh = [2 * width + 2 * height + 3 * rnd, 4 * width - height + rnd, rnd]
    rnd2 = math.floor(514 * random.random())
    of = [3 * 10 + 2 * 10 + rnd2, 4 * 10 - 4 * 10 + 2 * rnd2, rnd2]
    return {
        "dm_img_list": "[]",
        "dm_img_str": base64.b64encode(
            "".join(random.choices(string.printable, k=random.randint(16, 64))).encode()
        )[:-2].decode(),
        "dm_cover_img_str": base64.b64encode(
            "".join(random.choices(string.printable, k=random.randint(32, 128))).encode()
        )[:-2].decode(),
        "dm_img_inter": json.dumps(
            {"ds": [], "wh": wh, "of": of}, separators=(",", ":")
        ),
    }


@dataclass
class LoginStatus:
    is_login: bool
    uid: int = 0
    uname: str = ""
    message: str = ""


@dataclass
class Material:
    video: VideoInfo
    subtitles: list[tuple[float, str]] = field(default_factory=list)
    comments: list[CommentItem] = field(default_factory=list)
    danmaku_peaks: list[float] = field(default_factory=list)
    danmaku_keywords: list[tuple[float, str]] = field(default_factory=list)
    view_points: list[float] = field(default_factory=list)
    frames: list[Path] = field(default_factory=list)
    frame_times: list[float] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    cached_digest: str | None = None


class BiliClient:
    def __init__(
        self,
        sessdata: str = "",
        user_agent: str = "",
        timeout: int = 20,
        interval: float = 0.8,
        archive_fallback_enabled: bool = True,
        archive_fallback_api: str = "https://uapis.cn/api/v1/social/bilibili",
    ):
        self.http = BiliHTTP(sessdata, user_agent, interval)
        self.timeout = int(timeout)
        self.archive_fallback_enabled = bool(archive_fallback_enabled)
        self.archive_fallback_api = str(archive_fallback_api or "").strip().rstrip("/")
        self._ffmpeg: str | None = None

    # -- 基础 ---------------------------------------------------------

    def _api(self, path: str) -> str:
        return "https://api.bilibili.com" + path

    def _check(self, payload: dict, what: str) -> dict:
        code = payload.get("code")
        if code != 0:
            if code in (-101, -111):
                raise BiliError("need_login", f"{what} 需要登录态（code={code}）")
            if code in (-412, -352):
                raise BiliError("rate_limited", f"{what} 触发风控（code={code}）")
            if code == -404:
                raise BiliError("not_found", f"{what} 不存在（code={code}）")
            raise BiliError("api_error", f"{what} 失败 code={code} {payload.get('message')}")
        return payload.get("data") or {}

    def resolve_short(self, url: str) -> str:
        try:
            final = self.http.request(url)  # 会跟随重定向
            text = final.decode("utf-8", "replace")
        except Exception as exc:
            raise BiliError("network", f"短链解析失败：{exc}") from exc
        match = BV_RE.search(text)
        if match:
            return match.group(0)
        raise BiliError("not_found", "短链里没有找到 BV 号")

    def get_video(self, ref: str, page: int | None = None) -> VideoInfo:
        if ref.startswith("http"):
            if "b23.tv" in ref:
                ref = self.resolve_short(ref)
            else:
                match = BV_RE.search(ref)
                if match:
                    ref = match.group(0)
        if ref.startswith("BV"):
            data = self._check(
                self.http.get_json(
                    self._api(f"/x/web-interface/view?bvid={ref}"),
                    timeout=self.timeout,
                ),
                "视频信息",
            )
        elif ref.lower().startswith("av"):
            data = self._check(
                self.http.get_json(
                    self._api(f"/x/web-interface/view?aid={ref[2:]}"),
                    timeout=self.timeout,
                ),
                "视频信息",
            )
        else:
            raise BiliError("not_found", f"无法识别的视频标识：{ref}")

        pages = data.get("pages") or []
        page_count = len(pages) or 1
        index = min(max(1, page or 1), page_count)
        page_data = pages[index - 1] if pages else data
        stat = data.get("stat") or {}
        video = VideoInfo(
            bvid=str(data.get("bvid") or ref),
            aid=int(data.get("aid") or 0),
            cid=int(page_data.get("cid") or data.get("cid") or 0),
            page=index,
            page_count=page_count,
            title=str(data.get("title") or ""),
            up_name=str((data.get("owner") or {}).get("name") or ""),
            up_uid=int((data.get("owner") or {}).get("mid") or 0),
            duration=int(page_data.get("duration") or data.get("duration") or 0),
            desc=str(data.get("desc") or ""),
            pubdate=int(data.get("pubdate") or 0),
            views=int(stat.get("view") or 0),
            danmaku=int(stat.get("danmaku") or 0),
            replies=int(stat.get("reply") or 0),
            likes=int(stat.get("like") or 0),
            coins=int(stat.get("coin") or 0),
            favorites=int(stat.get("favorite") or 0),
            shares=int(stat.get("share") or 0),
        )
        return video

    # -- 播放器 / 字幕 -------------------------------------------------

    def get_player(self, bvid: str, cid: int) -> dict:
        url = self.http.wbi_url(
            self._api("/x/player/wbi/v2"), {"bvid": bvid, "cid": cid}
        )
        return self._check(self.http.get_json(url, timeout=self.timeout), "播放器信息")

    def get_view_point_times(self, player: dict) -> list[float]:
        points = []
        for item in player.get("view_points") or []:
            if not isinstance(item, dict):
                continue
            for key in ("time", "from", "start", "timestamp"):
                value = item.get(key)
                if isinstance(value, (int, float)) and value >= 0:
                    points.append(float(value))
                    break
        return points

    def get_subtitles(
        self,
        player: dict,
        langs: list[str],
        max_lines: int = 2000,
    ) -> list[tuple[float, str]]:
        subtitles = ((player.get("subtitle") or {}).get("subtitles") or [])
        if not subtitles:
            return []
        chosen = None
        for lang in langs:
            for item in subtitles:
                if str(item.get("lan") or "") == lang:
                    chosen = item
                    break
            if chosen:
                break
        if chosen is None:
            chosen = subtitles[0]
        url = self.http.absolute(str(chosen.get("subtitle_url") or ""))
        if not url:
            return []
        payload = self.http.get_json(url, timeout=self.timeout)
        lines = []
        for item in (payload.get("body") or [])[:max_lines]:
            content = str(item.get("content") or "").strip()
            if content:
                lines.append((float(item.get("from") or 0), content))
        return lines

    # -- 评论 -----------------------------------------------------------

    def get_comments(
        self,
        aid: int,
        limit: int = 12,
        reply_limit: int = 3,
        filter_ads: bool = True,
        include_pinned: bool = True,
        up_uid: int = 0,
    ) -> list[CommentItem]:
        url = self._api(
            f"/x/v2/reply?type=1&oid={aid}&pn=1&ps={max(1, min(limit, 20))}&sort=2"
        )
        data = self._check(self.http.get_json(url, timeout=self.timeout), "评论")
        result: list[CommentItem] = []
        seen: set[str] = set()

        def add(item: dict, pinned: bool = False) -> None:
            content = str((item.get("content") or {}).get("message") or "").strip()
            if not content or content in seen:
                return
            if filter_ads and _looks_like_ad(content):
                return
            if not pinned and is_low_value_comment(content):
                return
            mid = int((item.get("member") or {}).get("mid") or 0)
            role = "up" if up_uid and mid == int(up_uid) else "audience"
            sub = []
            for child in (item.get("replies") or [])[:reply_limit]:
                child_content = str(
                    (child.get("content") or {}).get("message") or ""
                ).strip()
                if child_content:
                    sub.append(child_content[:200])
            seen.add(content)
            result.append(
                CommentItem(
                    uname=str((item.get("member") or {}).get("uname") or ""),
                    content=content[:500],
                    like=int(item.get("like") or 0),
                    replies=sub,
                    pinned=pinned,
                    role=role,
                    time_marks=extract_time_marks(content),
                )
            )

        if include_pinned:
            for item in data.get("top_replies") or []:
                add(item, pinned=True)
                if len(result) >= limit:
                    break
        for item in data.get("replies") or []:
            add(item)
            if len(result) >= limit:
                break
        return result

    # -- 弹幕密度 -------------------------------------------------------

    def get_danmaku_insights(
        self, cid: int, duration: int, top: int = 8, keyword_limit: int = 6
    ) -> tuple[list[float], list[tuple[float, str]]]:
        """返回 (高能时间点, [(时间点, 关键词)])，过滤打卡/666 等刷屏。"""

        try:
            raw = self.http.request(
                self._api(f"/x/v1/dm/list.so?oid={cid}"), timeout=self.timeout
            )
        except Exception:
            return [], []
        text = raw.decode("utf-8", "replace")
        entries = re.findall(r'<d p="([^"]+)">(.*?)</d>', text, re.S)
        step = max(1, int(duration or 0) // 60)
        buckets: dict[int, list[str]] = {}
        counts: dict[int, int] = {}
        for param, content in entries:
            try:
                timestamp = float(param.split(",")[0])
            except Exception:
                continue
            bin_index = int(timestamp // step)
            counts[bin_index] = counts.get(bin_index, 0) + 1
            cleaned = html.unescape(re.sub(r"<[^>]+>", "", content)).strip()
            if cleaned:
                buckets.setdefault(bin_index, []).append(cleaned)
        if not counts:
            return [], []
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]
        peaks = [bin_index * step + step / 2 for bin_index, _ in ranked]
        keywords: list[tuple[float, str]] = []
        for bin_index, _count in ranked:
            words = danmaku_keywords(buckets.get(bin_index, []), keyword_limit)
            if words:
                keywords.append((bin_index * step + step / 2, "、".join(words)))
        return peaks, keywords

    # -- 取流 / 截帧 ----------------------------------------------------

    def get_playurl(self, bvid: str, cid: int) -> tuple[str, int]:
        url = self.http.wbi_url(
            self._api("/x/player/wbi/playurl"),
            {"bvid": bvid, "cid": cid, "qn": 32, "fnval": 16, "fourk": 1},
        )
        data = self._check(self.http.get_json(url, timeout=self.timeout), "播放地址")
        dash = data.get("dash") or {}
        videos = [
            item
            for item in dash.get("video") or []
            if item.get("baseUrl") or item.get("base_url")
        ]
        if videos:
            videos.sort(key=lambda item: int(item.get("height") or 0))
            chosen = next(
                (v for v in videos if int(v.get("height") or 0) >= 360), videos[-1]
            )
            return (
                str(chosen.get("baseUrl") or chosen.get("base_url")),
                int(chosen.get("height") or 0),
            )
        durl = [item for item in data.get("durl") or [] if item.get("url")]
        if durl:
            return str(durl[0]["url"]), 0
        raise BiliError("no_stream", "播放接口没有返回可用视频流")

    def _ffmpeg_exe(self) -> str:
        if self._ffmpeg:
            return self._ffmpeg
        try:
            import imageio_ffmpeg  # type: ignore

            self._ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            self._ffmpeg = "ffmpeg"
        return self._ffmpeg

    def select_timestamps(
        self,
        duration: int,
        view_points: list[float],
        danmaku_peaks: list[float],
        count: int,
        subtitles: list[tuple[float, str]] | None = None,
    ) -> list[float]:
        candidates: list[float] = []
        candidates.extend(view_points)
        candidates.extend(danmaku_peaks)
        # 字幕高信息段：优先选择字数多/带问号的句子
        subtitle_candidates: list[tuple[int, float]] = []
        for timestamp, text in subtitles or []:
            plain = re.sub(r"\s+", "", str(text or ""))
            if len(plain) < 6:
                continue
            score = len(plain) + (4 if any(ch in plain for ch in "？?！!") else 0)
            subtitle_candidates.append((score, float(timestamp)))
        subtitle_candidates.sort(reverse=True)
        for _score, timestamp in subtitle_candidates[: max(2, count // 3)]:
            candidates.append(timestamp)
        # 均匀保底
        for index in range(count):
            candidates.append(
                duration * (0.05 + 0.9 * index / max(1, count - 1))
            )
        chosen: list[float] = []
        lower = duration * 0.05 if duration else 0
        upper = duration * 0.95 if duration else 0
        for value in candidates:
            if value < lower or value > upper:
                continue
            if all(abs(value - existing) >= 3 for existing in chosen):
                chosen.append(round(value, 1))
            if len(chosen) >= count:
                break
        return sorted(chosen)[:count]

    def extract_frames(
        self,
        stream_url: str,
        timestamps: list[float],
        out_dir: Path,
        height: int = 480,
        max_mb: float = 3.0,
        referer: str = "https://www.bilibili.com/",
    ) -> list[tuple[Path, float]]:
        out_dir.mkdir(parents=True, exist_ok=True)
        headers = (
            f"Referer: {referer}\r\n"
            f"User-Agent: {self.http._headers.get('User-Agent', '')}\r\n"
        )
        frames: list[tuple[Path, float]] = []
        for index, seconds in enumerate(timestamps, start=1):
            out = out_dir / f"frame_{index:02d}_{int(seconds)}s.jpg"
            cmd = [
                self._ffmpeg_exe(),
                "-hide_banner",
                "-loglevel",
                "error",
                "-headers",
                headers,
                "-ss",
                f"{seconds:.1f}",
                "-i",
                stream_url,
                "-frames:v",
                "1",
                "-vf",
                f"scale=-2:{height}",
                "-q:v",
                "3",
                "-y",
                str(out),
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            except Exception:
                continue
            if out.exists() and out.stat().st_size <= max_mb * 1024 * 1024:
                frames.append((out, seconds))
        return frames

    # -- UP -------------------------------------------------------------

    def _fallback_archives(self, uid: int) -> tuple[list[str], int]:
        """官方空间接口被风控时，用可配置的第三方 API 兜底（只发送 UID，不带 Cookie）。"""

        if not self.archive_fallback_enabled or not self.archive_fallback_api:
            return [], 0
        url = (
            f"{self.archive_fallback_api}/archives"
            f"?mid={uid}&pn=1&ps=5&orderby=pubdate"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=min(self.timeout, 10)) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return [], 0
        titles: list[str] = []
        for item in payload.get("videos") or []:
            title = str(item.get("title") or "").strip()
            if title:
                titles.append(title[:80])
        try:
            total = int(payload.get("total") or 0)
        except Exception:
            total = 0
        return titles[:5], total

    def get_up_profile(self, uid: int) -> UpInfo:
        """UP 主页信息。

        优先用 `x/web-interface/card`（游客可用），`space/wbi/acc/info` 在游客态
        很容易 -352/-799 风控，只作为兜底。
        """

        self.http.ensure_buvid()
        name = ""
        sign = ""
        level = 0
        fans = 0
        archive_count = 0
        try:
            card = self._check(
                self.http.get_json(
                    self._api(f"/x/web-interface/card?mid={uid}"),
                    timeout=min(self.timeout, 8),
                ),
                "UP 信息",
            )
            card_data = card.get("card") or {}
            name = str(card_data.get("name") or "")
            sign = str(card_data.get("sign") or "")
            level = int(((card_data.get("level_info") or {}).get("current_level")) or 0)
            fans = int(card_data.get("fans") or card.get("follower") or 0)
            archive_count = int(card.get("archive_count") or 0)
        except Exception:
            pass
        if not name:
            try:
                data = self._check(
                    self.http.get_json(
                        self.http.wbi_url(
                            self._api("/x/space/wbi/acc/info"), {"mid": uid}
                        ),
                        timeout=min(self.timeout, 8),
                    ),
                    "UP 信息",
                )
                name = str(data.get("name") or "")
                sign = str(data.get("sign") or "")
                level = int(
                    ((data.get("level_info") or {}).get("current_level")) or 0
                )
            except Exception:
                pass
        if fans <= 0:
            try:
                relation = self.http.get_json(
                    self.http.wbi_url(
                        self._api("/x/relation/stat"), {"vmid": uid}
                    ),
                    timeout=min(self.timeout, 8),
                )
                fans = int((relation.get("data") or {}).get("follower") or 0)
            except Exception:
                pass
        archives = []
        # 重试统一由 BiliHTTP.get_json 的指数退避处理，这里只尝试一次
        for _attempt in range(1):
            try:
                arc_data = self._check(
                    self.http.get_json(
                        self.http.wbi_url(
                            self._api("/x/space/wbi/arc/search"),
                            {
                                "mid": uid,
                                "ps": 5,
                                "pn": 1,
                                "order": "pubdate",
                                **dm_params(),
                            },
                        ),
                        timeout=min(self.timeout, 8),
                        headers={
                            "Referer": f"https://space.bilibili.com/{uid}/video",
                            "Origin": "https://space.bilibili.com",
                        },
                    ),
                    "UP 投稿",
                )
                for item in ((arc_data.get("list") or {}).get("vlist") or [])[:5]:
                    title = str(item.get("title") or "").strip()
                    if title:
                        archives.append(title[:80])
                if not archive_count:
                    archive_count = int(
                        (arc_data.get("page") or {}).get("count") or 0
                    )
                break
            except Exception:
                archives.clear()
        archive_source = "official" if archives else "none"
        if not archives:
            fallback_titles, fallback_total = self._fallback_archives(uid)
            if fallback_titles:
                archives = fallback_titles
                archive_source = "fallback"
                if fallback_total and not archive_count:
                    archive_count = fallback_total
        if not name:
            raise BiliError("need_login", f"找不到 UID {uid} 的公开主页信息")
        return UpInfo(
            uid=uid,
            name=name,
            sign=sign,
            level=level,
            fans=fans,
            archives=archives,
            archive_count=archive_count,
            archive_source=archive_source,
        )

    def search_up(self, keyword: str, limit: int = 5, exact: bool = True) -> list[UpInfo]:
        self.http.ensure_buvid()
        url = self._api(
            f"/x/web-interface/search/type?search_type=bili_user&keyword="
            + _quote(str(keyword))
        )
        try:
            payload = self.http.get_json(
                url,
                timeout=min(self.timeout, 8),
                headers={"Referer": "https://search.bilibili.com/"},
            )
        except Exception as exc:
            raise BiliError("network", f"UP 搜索失败：{exc}") from exc
        if payload.get("code") not in (0, None):
            raise BiliError("api_error", f"UP 搜索失败 code={payload.get('code')}")
        users = ((payload.get("data") or {}).get("result") or [])
        result: list[UpInfo] = []
        target = str(keyword).strip()
        for item in users:
            name = re.sub(r"<[^>]+>", "", str(item.get("uname") or "")).strip()
            if exact and name != target:
                continue
            result.append(
                UpInfo(
                    uid=int(item.get("mid") or item.get("uid") or 0),
                    name=name,
                    sign=str(item.get("usign") or ""),
                    level=int(item.get("level") or 0),
                    fans=int(item.get("fans") or 0),
                    archives=[],
                )
            )
            if len(result) >= limit:
                break
        return result

    def check_login(self) -> LoginStatus:
        """用 nav 接口检查 SESSDATA 是否有效。"""

        try:
            payload = self.http.get_json(
                self._api("/x/web-interface/nav"), timeout=min(self.timeout, 5)
            )
        except Exception as exc:
            raise BiliError("network", f"登录态检查失败：{exc}") from exc
        data = payload.get("data") or {}
        if payload.get("code") == 0 and data.get("isLogin"):
            return LoginStatus(
                is_login=True,
                uid=int(data.get("mid") or 0),
                uname=str(data.get("uname") or ""),
                message=str(payload.get("message") or ""),
            )
        return LoginStatus(
            is_login=False,
            uid=int(data.get("mid") or 0),
            uname=str(data.get("uname") or ""),
            message=str(payload.get("message") or ""),
        )


def _looks_like_ad(text: str) -> bool:
    markers = ("抽奖", "广告", "接龙", "互关", "关注我", "私信", "代练", "推广")
    return any(marker in text for marker in markers)


def _quote(value: str) -> str:
    import urllib.parse

    return urllib.parse.quote(value)



