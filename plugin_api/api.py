"""B站之眼插件 WebUI 后端。

只读为主：概览、视频、笔记、原文、缓存、诊断。
写操作仅限缓存清理；配置只读，SESSDATA 永不返回。
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from quart import jsonify, request

try:
    import eyes_subagent as sa
    import eyes_transcript as et
except ImportError:  # pragma: no cover - 直接运行测试时
    from .. import eyes_subagent as sa  # type: ignore
    from .. import eyes_transcript as et  # type: ignore


class PluginWebApi:
    def __init__(self, plugin: Any):
        self.plugin = plugin
        self._routes: list[tuple[str, object, tuple[str, ...]]] = []

    def register(self) -> None:
        routes = (
            ("overview", self.overview, ["GET"], "B站之眼概览"),
            ("videos", self.videos, ["GET"], "最近视频记录"),
            ("video", self.video_detail, ["GET"], "视频笔记详情"),
            ("transcript", self.transcript, ["GET"], "原文检索"),
            ("cache-summary", self.cache_summary, ["GET"], "缓存统计"),
            ("cache-cleanup", self.cache_cleanup, ["POST"], "清理缓存"),
            ("config", self.config, ["GET"], "只读配置摘要"),
            ("diagnostics", self.diagnostics, ["GET"], "诊断信息"),
        )
        for path, handler, methods, description in routes:
            route = f"/astrbot_plugin_bilibili_eyes/{path}"
            try:
                self.plugin.context.register_web_api(
                    route, handler, methods, description
                )
                self._routes.append((route, handler, tuple(methods)))
            except Exception:
                # 某些测试环境没有 WebAPI；不影响插件主流程。
                continue

    def unregister(self) -> None:
        if not self._routes:
            return
        registry = getattr(self.plugin.context, "registered_web_apis", None)
        if not isinstance(registry, list):
            self._routes.clear()
            return
        owned = set(self._routes)
        registry[:] = [
            item
            for item in registry
            if not (
                isinstance(item, tuple)
                and len(item) >= 3
                and (item[0], item[1], tuple(item[2])) in owned
            )
        ]
        self._routes.clear()

    # -- helpers -----------------------------------------------------

    @staticmethod
    def _int(value: Any, default: int = 0, low: int = 0, high: int = 100) -> int:
        try:
            number = int(value)
        except Exception:
            number = default
        return max(low, min(high, number))

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _ok(**payload: Any):
        return jsonify({"success": True, **payload})

    @staticmethod
    def _error(message: str, status: int = 400):
        return jsonify({"success": False, "error": message}), status

    def _notes(self, limit: int = 500) -> list[dict]:
        cache = getattr(self.plugin, "_cache", None)
        if cache is None:
            return []
        try:
            return cache.list_records(limit)
        except Exception:
            return []

    def _transcripts(self, limit: int = 500) -> list[dict]:
        try:
            return self.plugin._transcript_store().list_records(limit)
        except Exception:
            return []

    def _note_record(self, bvid: str, page: int) -> dict | None:
        cache = getattr(self.plugin, "_cache", None)
        if cache is None:
            return None
        try:
            return cache.get_record(bvid, page)
        except Exception:
            return None

    def _data_dir(self) -> Path:
        try:
            return self.plugin._data_dir()
        except Exception:
            return Path(".")

    @staticmethod
    def _dir_stats(directory: Path) -> dict:
        count = 0
        size = 0
        if directory.exists():
            for path in directory.rglob("*"):
                if path.is_file():
                    try:
                        count += 1
                        size += path.stat().st_size
                    except OSError:
                        pass
        return {"count": count, "bytes": size}

    def _video_map(self) -> list[dict]:
        notes = {
            (item.get("bvid"), int(item.get("page") or 1)): item
            for item in self._notes()
            if item.get("bvid")
        }
        transcripts = {
            (item.get("bvid"), int(item.get("page") or 1)): item
            for item in self._transcripts()
            if item.get("bvid")
        }
        keys = set(notes) | set(transcripts)
        rows = []
        for bvid, page in keys:
            note = notes.get((bvid, page)) or {}
            transcript = transcripts.get((bvid, page)) or {}
            meta = note.get("meta") or {}
            created = max(
                float(note.get("created") or 0),
                float(transcript.get("created") or 0),
            )
            rows.append(
                {
                    "bvid": bvid,
                    "page": page,
                    "title": meta.get("title") or transcript.get("title") or "",
                    "mode": meta.get("mode") or "",
                    "created": created,
                    "note": bool(note),
                    "official_status": meta.get("official_status")
                    or transcript.get("official_status")
                    or "unknown",
                    "asr_status": meta.get("asr_status")
                    or transcript.get("asr_status")
                    or "unknown",
                    "official_count": transcript.get("official_count", 0),
                    "asr_count": transcript.get("asr_count", 0),
                    "languages": transcript.get("languages", []),
                    "track_count": transcript.get("track_count", 0),
                    "text_origin": meta.get("text_origin", ""),
                    "ocr_status": meta.get("ocr_status", ""),
                    "frames": int(meta.get("frames") or 0),
                    "core_chars": int(meta.get("core_chars") or 0),
                    "other_chars": int(meta.get("other_chars") or 0),
                }
            )
        rows.sort(key=lambda item: item["created"], reverse=True)
        return rows

    # -- GET ---------------------------------------------------------

    async def overview(self):
        try:
            videos = await asyncio.to_thread(self._video_map)
            notes = await asyncio.to_thread(self._notes)
            transcripts = await asyncio.to_thread(self._transcripts)
            notes_dir = getattr(getattr(self.plugin, "_cache", None), "directory", None)
            transcript_dir = getattr(
                getattr(self.plugin, "_transcript_store", lambda: None)(),
                "directory",
                None,
            )
            frames_dir = self._data_dir() / "frames"
            note_stats = await asyncio.to_thread(self._dir_stats, notes_dir) if notes_dir else {"count": 0, "bytes": 0}
            transcript_stats = await asyncio.to_thread(self._dir_stats, transcript_dir) if transcript_dir else {"count": 0, "bytes": 0}
            frame_stats = await asyncio.to_thread(self._dir_stats, frames_dir)
            last = videos[0] if videos else None
            return self._ok(
                overview={
                    "version": "0.12.2",
                    "enabled": self.plugin._bool_opt("enabled"),
                    "video_mode": self.plugin._video_mode(),
                    "last_video": last,
                    "notes": note_stats,
                    "transcripts": transcript_stats,
                    "frames": frame_stats,
                    "counts": {
                        "videos": len(videos),
                        "notes": len(notes),
                        "transcripts": len(transcripts),
                    },
                    "asr_enabled": self.plugin._bool_opt("audio_transcription_enabled"),
                }
            )
        except Exception as exc:
            return self._error(f"读取概览失败：{type(exc).__name__}", 500)

    async def videos(self):
        try:
            rows = await asyncio.to_thread(self._video_map)
            query = str(request.args.get("q", "") or "").strip().lower()
            mode = str(request.args.get("mode", "") or "").strip()
            if query:
                rows = [
                    item
                    for item in rows
                    if query in str(item.get("title", "")).lower()
                    or query in str(item.get("bvid", "")).lower()
                ]
            if mode:
                rows = [item for item in rows if item.get("mode") == mode]
            limit = self._int(request.args.get("limit", "50"), 50, 1, 200)
            offset = self._int(request.args.get("offset", "0"), 0, 0, 10000)
            return self._ok(rows=rows[offset : offset + limit], total=len(rows))
        except Exception as exc:
            return self._error(f"读取视频列表失败：{type(exc).__name__}", 500)

    async def video_detail(self):
        bvid = str(request.args.get("bvid", "") or "").strip()
        page = self._int(request.args.get("page", "1"), 1, 1, 9999)
        if not bvid:
            return self._error("缺少 bvid")
        try:
            record = await asyncio.to_thread(self._note_record, bvid, page)
            transcript = None
            try:
                transcript = self.plugin._transcript_store().load(bvid, page)
            except Exception:
                transcript = None
            if not record and not transcript:
                return self._error("没有找到该视频的笔记或原文", 404)
            digest = str((record or {}).get("digest") or "")
            core, other = sa.split_note_sections(digest) if digest else ("", "")
            if digest and not core and not other:
                core = digest
            meta = (record or {}).get("meta") or {}
            return self._ok(
                video={
                    "bvid": bvid,
                    "page": page,
                    "title": meta.get("title")
                    or (transcript or {}).get("title")
                    or "",
                    "created": (record or {}).get("created")
                    or (transcript or {}).get("created")
                    or 0,
                },
                meta=meta,
                note={
                    "available": bool(record),
                    "core": core,
                    "other": other,
                },
                transcript={
                    "available": bool(transcript),
                    "official_count": len((transcript or {}).get("official") or []),
                    "asr_count": len((transcript or {}).get("asr") or []),
                    "official_status": (transcript or {}).get("official_status", "unknown"),
                    "asr_status": (transcript or {}).get("asr_status", "unknown"),
                    "tracks": [
                        {
                            "lang": track.get("lang", ""),
                            "lang_doc": track.get("lang_doc", ""),
                            "role": track.get("role", ""),
                            "origin": track.get("origin", "official"),
                            "confidence": track.get("confidence", 1.0),
                            "line_count": len(track.get("lines") or []),
                        }
                        for track in (transcript or {}).get("tracks") or []
                    ],
                },
            )
        except Exception as exc:
            return self._error(f"读取视频详情失败：{type(exc).__name__}", 500)

    async def transcript(self):
        bvid = str(request.args.get("bvid", "") or "").strip()
        page = self._int(request.args.get("page", "1"), 1, 1, 9999)
        if not bvid:
            return self._error("缺少 bvid")
        try:
            doc = self.plugin._transcript_store().load(bvid, page)
        except Exception:
            doc = None
        if not doc:
            return self._error("没有该视频的原文缓存，请重新观看后再查", 404)
        result = et.search(
            doc,
            query=str(request.args.get("query", "") or ""),
            start=self._float(request.args.get("start", 0)),
            end=self._float(request.args.get("end", 0)),
            source=str(request.args.get("source", "both") or "both"),
            max_lines=self._int(request.args.get("limit", "20"), 20, 1, 50),
            lang=str(request.args.get("lang", "") or ""),
        )
        return self._ok(text=et.format_result(doc, result), result=result)

    async def cache_summary(self):
        try:
            cache = getattr(self.plugin, "_cache", None)
            notes_dir = getattr(cache, "directory", None)
            transcript_dir = getattr(
                getattr(self.plugin, "_transcript_store", lambda: None)(),
                "directory",
                None,
            )
            notes = await asyncio.to_thread(self._dir_stats, notes_dir) if notes_dir else {"count": 0, "bytes": 0}
            transcripts = await asyncio.to_thread(self._dir_stats, transcript_dir) if transcript_dir else {"count": 0, "bytes": 0}
            frames = await asyncio.to_thread(self._dir_stats, self._data_dir() / "frames")
            return self._ok(
                notes=notes,
                transcripts=transcripts,
                frames=frames,
            )
        except Exception as exc:
            return self._error(f"读取缓存统计失败：{type(exc).__name__}", 500)

    async def config(self):
        try:
            group_keys = getattr(self.plugin, "CONFIG_GROUP_KEYS", None)
            if not group_keys:
                module = sys.modules.get(type(self.plugin).__module__)
                group_keys = getattr(module, "CONFIG_GROUP_KEYS", {}) if module else {}
            groups = {}
            for group, keys in (group_keys or {}).items():
                values = {}
                for key in keys:
                    if key == "_grouped_config_migrated":
                        continue
                    if key == "sessdata":
                        values[key] = "已配置" if self.plugin._opt(key) else ""
                    else:
                        values[key] = self.plugin._opt(key)
                groups[group] = values
            return self._ok(groups=groups)
        except Exception as exc:
            return self._error(f"读取配置失败：{type(exc).__name__}", 500)

    async def diagnostics(self):
        try:
            notes = await asyncio.to_thread(self._notes, 200)
            transcripts = await asyncio.to_thread(self._transcripts, 200)
            recent = []
            for item in notes[:20]:
                meta = item.get("meta") or {}
                recent.append(
                    {
                        "bvid": item.get("bvid"),
                        "page": item.get("page"),
                        "mode": meta.get("mode", ""),
                        "created": item.get("created", 0),
                        "official_status": meta.get("official_status", "unknown"),
                        "asr_status": meta.get("asr_status", "unknown"),
                        "frames": meta.get("frames", 0),
                        "warnings": [],
                    }
                )
            return self._ok(
                mode=self.plugin._video_mode(),
                notes=len(notes),
                transcripts=len(transcripts),
                recent=recent,
            )
        except Exception as exc:
            return self._error(f"读取诊断失败：{type(exc).__name__}", 500)

    # -- POST --------------------------------------------------------

    async def cache_cleanup(self):
        try:
            payload = await request.get_json() or {}
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            return self._error("请求内容必须是对象")
        kind = str(payload.get("kind") or "all").strip()
        bvid = str(payload.get("bvid") or "").strip()
        page = self._int(payload.get("page", 0), 0, 0, 9999)
        expired_only = bool(payload.get("expired_only", False))
        if kind not in {"notes", "transcripts", "frames", "all"}:
            return self._error("不支持的缓存类型")
        if bvid and not bvid.upper().startswith("BV"):
            return self._error("bvid 格式不正确")
        removed = {"notes": 0, "transcripts": 0, "frames": 0}
        try:
            if kind in {"notes", "all"}:
                cache = getattr(self.plugin, "_cache", None)
                directory = getattr(cache, "directory", None)
                if directory and Path(directory).exists():
                    pattern = f"{bvid}_p{page}*.json" if bvid and page else (
                        f"{bvid}_p*.json" if bvid else "*.json"
                    )
                    for path in Path(directory).glob(pattern):
                        try:
                            path.unlink()
                            removed["notes"] += 1
                        except OSError:
                            pass
            if kind in {"transcripts", "all"}:
                try:
                    directory = self.plugin._transcript_store().directory
                except Exception:
                    directory = None
                if directory and Path(directory).exists():
                    pattern = f"{bvid}_p{page}.json" if bvid and page else (
                        f"{bvid}_p*.json" if bvid else "*.json"
                    )
                    for path in Path(directory).glob(pattern):
                        try:
                            path.unlink()
                            removed["transcripts"] += 1
                        except OSError:
                            pass
            if kind in {"frames", "all"}:
                frames_dir = self._data_dir() / "frames"
                targets = [frames_dir / bvid] if bvid else list(frames_dir.glob("*"))
                for target in targets:
                    if not target.exists():
                        continue
                    if not target.resolve().is_relative_to(frames_dir.resolve()):
                        continue
                    files = list(target.rglob("*")) if target.is_dir() else [target]
                    for path in files:
                        if path.is_file():
                            try:
                                path.unlink()
                                removed["frames"] += 1
                            except OSError:
                                pass
            return self._ok(removed=removed)
        except Exception as exc:
            return self._error(f"清理缓存失败：{type(exc).__name__}", 500)
