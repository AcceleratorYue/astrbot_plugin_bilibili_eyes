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
    ) -> bool:
        if not bvid:
            return False
        payload = {
            "bvid": str(bvid),
            "page": int(page or 1),
            "title": str(title or ""),
            "duration": round(float(duration or 0), 2),
            "official": [list(item) for item in _normalize_lines(official)],
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
) -> dict:
    """在官方字幕/ASR 中查找片段；返回可直接给主模型的结果。"""

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

    rows: list[dict] = []
    sources = ["official", "asr"] if source == "both" else [source]
    for name in sources:
        for stamp, text in doc.get(name) or []:
            if start and stamp < start:
                continue
            if end and stamp > end:
                continue
            rows.append(
                {
                    "source": name,
                    "time": float(stamp),
                    "text": str(text),
                }
            )
    rows.sort(key=lambda item: (item["time"], item["source"]))

    if tokens:
        matched = [
            row for row in rows if _line_match_score(row["text"], tokens) > 0
        ]
        # 匹配行 + 前后各一条上下文；用 (source,time) 去重。
        chosen: list[dict] = []
        seen: set[tuple[str, float]] = set()
        index_map = {
            (row["source"], row["time"]): index for index, row in enumerate(rows)
        }
        for row in matched:
            index = index_map.get((row["source"], row["time"]), 0)
            for near in (index - 1, index, index + 1):
                if 0 <= near < len(rows):
                    item = rows[near]
                    key = (item["source"], item["time"])
                    if key not in seen:
                        seen.add(key)
                        chosen.append(item)
        rows = sorted(chosen, key=lambda item: (item["time"], item["source"]))
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
    """从 Material 生成查询用的临时 doc。"""

    video = getattr(material, "video", None)
    source = str(getattr(material, "subtitle_source", "official") or "official")
    official = getattr(material, "subtitles", []) or []
    asr = getattr(material, "asr_subtitles", []) or []
    if source == "asr":
        asr = asr or official
        official = []
    return {
        "bvid": str(getattr(video, "bvid", "") or ""),
        "page": int(getattr(video, "page", 1) or 1),
        "title": str(getattr(video, "title", "") or ""),
        "duration": float(getattr(video, "duration", 0) or 0),
        "official": _normalize_lines(official),
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
