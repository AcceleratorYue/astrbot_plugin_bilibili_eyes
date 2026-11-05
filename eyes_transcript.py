"""字幕 / ASR 原文缓存与直接检索。

这个模块只处理文字，不依赖子代理，也不调用任何模型。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Iterable

LINE_CHAR_LIMIT = 300
DEFAULT_TOTAL_CHARS = 2500


def _safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_\-]", "_", str(value or ""))
    return text or "unknown"


def _normalize_lines(lines: Iterable[Any]) -> list[tuple[float, str]]:
    result: list[tuple[float, str]] = []
    for item in lines or []:
        try:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                stamp = float(item[0])
                text = str(item[1] or "").strip()
            else:
                continue
        except Exception:
            continue
        if text:
            result.append((round(max(0.0, stamp), 2), text))
    result.sort(key=lambda row: row[0])
    return result


def _normalize_track(track: Any) -> dict:
    if isinstance(track, dict):
        lang = str(track.get("lang") or "")
        lang_doc = str(track.get("lang_doc") or lang)
        role = str(track.get("role") or "primary")
        is_ai = bool(track.get("is_ai"))
        bilingual = bool(track.get("bilingual"))
        lines = track.get("lines") or track.get("body") or []
    else:
        lang = str(getattr(track, "lang", "") or "")
        lang_doc = str(getattr(track, "lang_doc", "") or lang)
        role = str(getattr(track, "role", "primary") or "primary")
        is_ai = bool(getattr(track, "is_ai", False))
        bilingual = bool(getattr(track, "bilingual", False))
        lines = getattr(track, "lines", []) or []
    return {
        "lang": lang,
        "lang_doc": lang_doc,
        "role": role,
        "is_ai": is_ai,
        "bilingual": bilingual,
        "lines": [list(item) for item in _normalize_lines(lines)],
    }


def _doc_tracks(doc: dict) -> list[dict]:
    tracks = doc.get("tracks")
    if isinstance(tracks, list) and tracks:
        return [_normalize_track(track) for track in tracks]
    official = _normalize_lines(doc.get("official") or [])
    secondary = _normalize_lines(doc.get("official_secondary") or [])
    result: list[dict] = []
    if official:
        result.append(
            {
                "lang": str(doc.get("official_lang") or ""),
                "lang_doc": str(doc.get("official_lang_doc") or ""),
                "role": "primary",
                "is_ai": False,
                "bilingual": False,
                "lines": [list(item) for item in official],
            }
        )
    if secondary:
        result.append(
            {
                "lang": str(doc.get("secondary_lang") or ""),
                "lang_doc": str(doc.get("secondary_lang_doc") or ""),
                "role": "secondary",
                "is_ai": False,
                "bilingual": False,
                "lines": [list(item) for item in secondary],
            }
        )
    return result


def _track_label(track: dict) -> str:
    if track.get("role") == "secondary":
        base = "官方辅轨"
    else:
        base = "官方字幕"
    lang = str(track.get("lang_doc") or track.get("lang") or "").strip()
    return f"{base}·{lang}" if lang else base


def _lang_matches(track_lang: str, wanted: str) -> bool:
    wanted = str(wanted or "").strip().lower()
    if not wanted:
        return True
    value = str(track_lang or "").strip().lower().replace("_", "-")
    if wanted in value:
        return True
    families = {
        "zh": ("zh", "chinese", "中文"),
        "en": ("en", "english", "英文", "英语"),
        "ja": ("ja", "jp", "japanese", "日文", "日语", "日本語"),
        "ko": ("ko", "korean", "韩文", "韩语", "한국어"),
    }
    aliases = families.get(wanted, (wanted,))
    return any(alias in value for alias in aliases)


class TranscriptStore:
    """按 bvid + 分P 保存官方字幕 / ASR 原文，只存文字。"""

    def __init__(
        self,
        directory: Path,
        ttl_hours: int = 168,
        max_entries: int = 200,
    ):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = max(1, int(ttl_hours)) * 3600
        self.max_entries = max(1, int(max_entries))

    def _path(self, bvid: str, page: int) -> Path:
        return self.directory / f"{_safe_name(bvid)}_p{int(page or 1)}.json"

    def save(
        self,
        bvid: str,
        page: int,
        title: str,
        duration: float,
        official: Iterable[Any],
        asr: Iterable[Any],
        official_status: str = "unknown",
        asr_status: str = "unknown",
        asr_fingerprint: str = "",
        tracks: Iterable[Any] | None = None,
    ) -> bool:
        if not bvid:
            return False
        track_payload = [_normalize_track(track) for track in (tracks or [])]
        official_lines = _normalize_lines(official)
        secondary_lines = _normalize_lines([])
        if track_payload:
            official_lines = track_payload[0].get("lines") or official_lines
            secondary_lines = next(
                (
                    track.get("lines") or []
                    for track in track_payload
                    if track.get("role") == "secondary"
                ),
                [],
            )
        payload = {
            "version": 2,
            "bvid": str(bvid),
            "page": int(page or 1),
            "title": str(title or ""),
            "duration": round(float(duration or 0), 2),
            "tracks": track_payload,
            "official": [list(item) for item in official_lines],
            "official_secondary": [list(item) for item in secondary_lines],
            "official_lang": (
                track_payload[0].get("lang", "") if track_payload else ""
            ),
            "official_lang_doc": (
                track_payload[0].get("lang_doc", "") if track_payload else ""
            ),
            "secondary_lang": next(
                (
                    track.get("lang", "")
                    for track in track_payload
                    if track.get("role") == "secondary"
                ),
                "",
            ),
            "secondary_lang_doc": next(
                (
                    track.get("lang_doc", "")
                    for track in track_payload
                    if track.get("role") == "secondary"
                ),
                "",
            ),
            "asr": [list(item) for item in _normalize_lines(asr)],
            "official_status": str(official_status or "unknown"),
            "asr_status": str(asr_status or "unknown"),
            "asr_fingerprint": str(asr_fingerprint or ""),
            "created": time.time(),
            "updated": time.time(),
        }
        try:
            path = self._path(bvid, page)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            self.prune()
            return True
        except Exception:
            return False

    def load(self, bvid: str, page: int = 1) -> dict | None:
        path = self._path(bvid, page)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        updated = float(payload.get("updated") or payload.get("created") or 0)
        if not updated or time.time() - updated > self.ttl_seconds:
            try:
                path.unlink()
            except Exception:
                pass
            return None
        payload["official"] = _normalize_lines(payload.get("official") or [])
        payload["asr"] = _normalize_lines(payload.get("asr") or [])
        payload["official_secondary"] = _normalize_lines(
            payload.get("official_secondary") or []
        )
        payload["tracks"] = _doc_tracks(payload)
        return payload

    def list_records(self, limit: int = 200) -> list[dict]:
        self.prune()
        records: list[dict] = []
        for path in self.directory.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            updated = float(payload.get("updated") or payload.get("created") or 0)
            if not updated or time.time() - updated > self.ttl_seconds:
                continue
            records.append(
                {
                    "bvid": str(payload.get("bvid") or ""),
                    "page": int(payload.get("page") or 1),
                    "title": str(payload.get("title") or ""),
                    "created": updated,
                    "official_count": len(payload.get("official") or []),
                    "asr_count": len(payload.get("asr") or []),
                    "official_status": str(payload.get("official_status") or ""),
                    "asr_status": str(payload.get("asr_status") or ""),
                    "track_count": len(_doc_tracks(payload)),
                    "languages": [
                        str(track.get("lang_doc") or track.get("lang") or "")
                        for track in _doc_tracks(payload)
                    ],
                    "filename": path.name,
                }
            )
        records.sort(key=lambda item: item.get("created", 0), reverse=True)
        return records[: max(1, int(limit))]

    def prune(self) -> None:
        files = sorted(
            self.directory.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        now = time.time()
        for path in files:
            try:
                if now - path.stat().st_mtime > self.ttl_seconds:
                    path.unlink()
            except Exception:
                pass
        files = sorted(
            self.directory.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in files[self.max_entries :]:
            try:
                path.unlink()
            except Exception:
                pass


def _query_tokens(query: str) -> list[str]:
    text = str(query or "").strip()
    if not text:
        return []
    tokens = [text]
    tokens.extend(
        item for item in re.split(r"[\s,，。.!！?？、:：;；]+", text) if item
    )
    # 中文长词补二元组，英文按空格切分。
    if re.search(r"[\u4e00-\u9fff]", text) and len(text) > 2:
        tokens.extend(text[i : i + 2] for i in range(len(text) - 1))
    seen: list[str] = []
    for token in tokens:
        lowered = token.lower()
        if lowered and lowered not in seen:
            seen.append(lowered)
    return seen


def _line_match_score(text: str, tokens: list[str]) -> int:
    if not tokens:
        return 1
    lowered = str(text or "").lower()
    score = 0
    for token in tokens:
        if token and token in lowered:
            score += 1
    return score


def search(
    doc: dict,
    query: str = "",
    start: float = 0.0,
    end: float = 0.0,
    source: str = "both",
    max_lines: int = 20,
    max_chars: int = DEFAULT_TOTAL_CHARS,
    lang: str = "",
) -> dict:
    """在官方主/辅字幕与 ASR 中查找片段；返回可直接给主模型的结果。"""

    source = str(source or "both").strip().lower()
    if source not in ("official", "asr", "both"):
        source = "both"
    max_lines = max(1, min(50, int(max_lines or 20)))
    max_chars = max(300, min(6000, int(max_chars or DEFAULT_TOTAL_CHARS)))
    start = max(0.0, float(start or 0.0))
    end = max(0.0, float(end or 0.0))
    if end and end < start:
        start, end = end, start
    tokens = _query_tokens(query)
    lang = str(lang or "").strip().lower()

    rows: list[dict] = []

    def add_row(stamp: float, text: str, source_name: str, track: dict | None = None) -> None:
        if start and stamp < start:
            return
        if end and stamp > end:
            return
        track = track or {}
        rows.append(
            {
                "source": source_name,
                "time": float(stamp),
                "text": str(text),
                "lang": str(track.get("lang") or ""),
                "lang_doc": str(track.get("lang_doc") or track.get("lang") or ""),
                "role": str(track.get("role") or ""),
                "label": (
                    _track_label(track)
                    if source_name == "official"
                    else "ASR（约）"
                ),
            }
        )

    if source in ("official", "both"):
        for track in _doc_tracks(doc):
            if lang and not _lang_matches(
                str(track.get("lang_doc") or track.get("lang") or ""), lang
            ):
                continue
            for stamp, text in track.get("lines") or []:
                add_row(float(stamp), str(text), "official", track)
    if source == "asr" or (source == "both" and not lang):
        for stamp, text in doc.get("asr") or []:
            add_row(float(stamp), str(text), "asr")

    rows.sort(key=lambda item: (item["time"], item["source"], item["lang"]))

    if tokens:
        matched = [
            row for row in rows if _line_match_score(row["text"], tokens) > 0
        ]
        # 匹配行 + 前后各一条上下文；用 source/lang/role/time 去重。
        chosen: list[dict] = []
        seen: set[tuple[str, str, str, float]] = set()
        index_map = {
            (row["source"], row["lang"], row["role"], row["time"]): index
            for index, row in enumerate(rows)
        }
        for row in matched:
            index = index_map.get(
                (row["source"], row["lang"], row["role"], row["time"]), 0
            )
            for near in (index - 1, index, index + 1):
                if 0 <= near < len(rows):
                    item = rows[near]
                    key = (
                        item["source"],
                        item["lang"],
                        item["role"],
                        item["time"],
                    )
                    if key not in seen:
                        seen.add(key)
                        chosen.append(item)
        rows = sorted(
            chosen,
            key=lambda item: (item["time"], item["source"], item["lang"]),
        )
    elif not start and not end:
        # 没有关键词也没有时间范围：不返回全文，只给前后目录。
        if len(rows) > 10:
            rows = rows[:5] + rows[-5:]

    total = len(rows)
    truncated = total > max_lines
    selected = rows[:max_lines]
    output: list[dict] = []
    used = 0
    for row in selected:
        text = row["text"][:LINE_CHAR_LIMIT]
        cost = len(text) + 32
        if used + cost > max_chars:
            truncated = True
            break
        used += cost
        output.append({**row, "text": text})

    return {
        "rows": output,
        "total": total,
        "truncated": truncated,
        "query": str(query or ""),
        "source": source,
        "lang": lang,
        "start": start,
        "end": end,
    }


def format_result(doc: dict, result: dict) -> str:
    title = str(doc.get("title") or "")
    bvid = str(doc.get("bvid") or "")
    lines = [f"视频：{bvid} {title}".strip()]
    status = []
    if doc.get("official_status") not in (None, "", "unknown", "available"):
        status.append(f"官方字幕状态={doc.get('official_status')}")
    if doc.get("asr_status") not in (None, "", "unknown", "available"):
        status.append(f"ASR 状态={doc.get('asr_status')}")
    if status:
        lines.append("状态：" + "；".join(status))
    rows = result.get("rows") or []
    if not rows:
        lines.append("没有匹配的字幕/ASR 原文片段。")
        lines.append("可以换关键词，或指定更小的时间范围。")
        return "\n".join(lines)

    lines.append(
        f"来源：{result.get('source')}；"
        f"匹配 {result.get('total', len(rows))} 条；"
        f"返回 {len(rows)} 条"
    )
    for row in rows:
        source = str(row.get("label") or "")
        if not source:
            source = "官方字幕" if row["source"] == "official" else "ASR（约）"
        stamp = _fmt_time(float(row["time"]))
        lines.append(f"[{stamp}] {source}：{row['text']}")
    if result.get("truncated"):
        lines.append("结果已截断；请缩小关键词或时间范围。")
    return "\n".join(lines)


def _fmt_time(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def doc_from_material(material: Any) -> dict:
    """从 Material 生成查询用的临时 doc，保留主/辅字幕轨。"""

    video = getattr(material, "video", None)
    source = str(getattr(material, "subtitle_source", "official") or "official")
    official = getattr(material, "subtitles", []) or []
    secondary = getattr(material, "secondary_subtitles", []) or []
    asr = getattr(material, "asr_subtitles", []) or []
    tracks = getattr(material, "subtitle_tracks", []) or []
    if source == "asr":
        asr = asr or official
        official = []
        secondary = []
        tracks = []
    return {
        "bvid": str(getattr(video, "bvid", "") or ""),
        "page": int(getattr(video, "page", 1) or 1),
        "title": str(getattr(video, "title", "") or ""),
        "duration": float(getattr(video, "duration", 0) or 0),
        "tracks": [_normalize_track(track) for track in tracks],
        "official": _normalize_lines(official),
        "official_secondary": _normalize_lines(secondary),
        "official_lang": str(getattr(material, "subtitle_lang", "") or ""),
        "official_lang_doc": str(
            getattr(material, "subtitle_lang_doc", "") or ""
        ),
        "secondary_lang": str(getattr(material, "secondary_lang", "") or ""),
        "secondary_lang_doc": str(
            getattr(material, "secondary_lang_doc", "") or ""
        ),
        "asr": _normalize_lines(asr),
        "official_status": (
            "absent"
            if source == "asr"
            else str(getattr(material, "official_status", "unknown") or "unknown")
        ),
        "asr_status": str(getattr(material, "asr_status", "unknown") or "unknown"),
        "asr_fingerprint": str(
            getattr(material, "asr_fingerprint", "") or ""
        ),
    }
