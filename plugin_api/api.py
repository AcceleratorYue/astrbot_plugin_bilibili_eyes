"""B站之眼插件 WebUI 后端。

只读为主：概览、视频、笔记、原文、缓存、诊断。
写操作仅限缓存清理；配置只读，SESSDATA 永不返回。
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import sys
import time
from pathlib import Path
from typing import Any

from quart import jsonify, request

try:
    import eyes_subagent as sa
    import eyes_transcript as et
    from . import settings_spec
except ImportError:  # pragma: no cover - 直接运行测试时
    from .. import eyes_subagent as sa  # type: ignore
    from .. import eyes_transcript as et  # type: ignore
    from ..plugin_api import settings_spec  # type: ignore


class PluginWebApi:
    def __init__(self, plugin: Any):
        self.plugin = plugin
        self._routes: list[tuple[str, object, tuple[str, ...]]] = []

    def register(self) -> None:
        routes = (
            ("status", self.status, ["GET"], "插件状态"),
            ("overview", self.overview, ["GET"], "B站之眼概览"),
            ("settings", self.settings, ["GET"], "读取设置"),
            ("settings/save", self.settings_save, ["POST"], "保存设置"),
            ("settings/reset", self.settings_reset, ["POST"], "恢复默认设置"),
            ("login/qr", self.login_qr, ["POST"], "申请扫码登录二维码"),
            ("login/status", self.login_status, ["GET"], "轮询扫码状态"),
            ("login/account", self.login_account, ["GET"], "读取登录账号"),
            ("login/logout", self.login_logout, ["POST"], "清除扫码凭据"),
            ("cache", self.cache_summary, ["GET"], "缓存统计"),
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

    def _config_mapping(self) -> dict[str, str]:
        mapping = getattr(self.plugin, "CONFIG_KEY_TO_GROUP", None)
        if mapping:
            return mapping
        module = sys.modules.get(type(self.plugin).__module__)
        return getattr(module, "CONFIG_KEY_TO_GROUP", {}) if module else {}

    def _cache_stats(self) -> dict:
        cache = getattr(self.plugin, "_cache", None)
        notes_dir = getattr(cache, "directory", None)
        try:
            transcript_dir = self.plugin._transcript_store().directory
        except Exception:
            transcript_dir = None
        return {
            "notes": self._dir_stats(notes_dir) if notes_dir else {"count": 0, "bytes": 0},
            "transcripts": self._dir_stats(transcript_dir) if transcript_dir else {"count": 0, "bytes": 0},
            "frames": self._dir_stats(self._data_dir() / "frames"),
        }

    async def _save_values(self, values: dict) -> dict:
        config = getattr(self.plugin, "_config", None)
        if config is None:
            raise RuntimeError("插件配置对象不可用")
        mapping = self._config_mapping()
        restart_required = False
        for key, value in values.items():
            group = mapping.get(key)
            if not group:
                continue
            current = config.get(group)
            if not isinstance(current, dict):
                current = {}
                config[group] = current
            current[key] = value
            try:
                config[key] = value
            except Exception:
                pass
        saver = getattr(config, "save_config_async", None)
        if callable(saver):
            try:
                result = saver()
                if inspect.isawaitable(result):
                    await result
            except TypeError:
                result = saver(values)
                if inspect.isawaitable(result):
                    await result
        else:
            saver = getattr(config, "save_config", None)
            if callable(saver):
                result = saver()
                if inspect.isawaitable(result):
                    await result
            else:
                raise RuntimeError("当前 AstrBot 配置对象不支持保存")
        if any(key in values for key in ("worker_threads", "concurrency_limit")):
            restart_required = True
        if "cache_ttl_hours" in values or "cache_max_entries" in values:
            cache = getattr(self.plugin, "_cache", None)
            if cache is not None:
                if "cache_ttl_hours" in values:
                    cache.ttl_seconds = max(1, int(values["cache_ttl_hours"])) * 3600
                if "cache_max_entries" in values:
                    cache.max_entries = max(1, int(values["cache_max_entries"]))
        if "transcript_ttl_hours" in values or "transcript_max_entries" in values:
            transcripts = getattr(self.plugin, "_transcripts", None)
            if transcripts is not None:
                if "transcript_ttl_hours" in values:
                    transcripts.ttl_seconds = max(1, int(values["transcript_ttl_hours"])) * 3600
                if "transcript_max_entries" in values:
                    transcripts.max_entries = max(1, int(values["transcript_max_entries"]))
        if "sessdata" in values:
            self.plugin._account_cache = None
        return {"restart_required": restart_required}

    async def status(self):
        try:
            login = self.plugin._login_summary()
            account = await self.plugin._bili_account() if login.get("logged_in") else None
            cache = await asyncio.to_thread(self._cache_stats)
            ffmpeg_path = ""
            try:
                ffmpeg_path = str(self.plugin._client()._ffmpeg_exe() or "")
            except Exception:
                pass
            return self._ok(
                status={
                    "version": "0.14.1",
                    "plugin_name": "astrbot_plugin_bilibili_eyes",
                    "data_dir": str(self._data_dir()),
                    "login": {**login, "account": account},
                    "video_mode": self.plugin._video_mode(),
                    "vision_provider_id": self.plugin._opt("vision_provider_id") or "",
                    "asr": {
                        "enabled": self.plugin._bool_opt("audio_transcription_enabled"),
                        "mode": self.plugin._opt("audio_transcription_mode") or "",
                    },
                    "ocr": {
                        "enabled": self.plugin._bool_opt("ocr_subtitle_enabled"),
                        "engine": self.plugin._opt("ocr_engine") or "",
                        "priority": self.plugin._opt("ocr_subtitle_priority") or "",
                    },
                    "ffmpeg": {"path": ffmpeg_path, "available": bool(ffmpeg_path)},
                    "cache": cache,
                    "registered_apis": [item[0] for item in self._routes],
                    "server_time": int(time.time()),
                }
            )
        except Exception as exc:
            return self._error(f"读取状态失败：{type(exc).__name__}", 500)

    async def settings(self):
        try:
            values, secrets = settings_spec.public_values(self.plugin)
            return self._ok(
                groups=settings_spec.GROUPS,
                values=values,
                secrets_present=secrets,
            )
        except Exception as exc:
            return self._error(f"读取设置失败：{type(exc).__name__}", 500)

    async def settings_save(self):
        try:
            payload = await request.get_json() or {}
        except Exception:
            payload = {}
        values = payload.get("values") if isinstance(payload, dict) and isinstance(payload.get("values"), dict) else payload
        clean, errors = settings_spec.validate_values(values if isinstance(values, dict) else {})
        if errors:
            return self._error(errors[0])
        if not clean:
            return self._ok(saved=False, message="没有需要保存的更改")
        try:
            extra = await self._save_values(clean)
            values_out, secrets = settings_spec.public_values(self.plugin)
            return self._ok(
                saved=True,
                message=f"已保存 {len(clean)} 项设置",
                values=values_out,
                secrets_present=secrets,
                **extra,
            )
        except Exception as exc:
            return self._error(f"保存设置失败：{type(exc).__name__}", 500)

    async def settings_reset(self):
        try:
            payload = await request.get_json() or {}
        except Exception:
            payload = {}
        keys = payload.get("keys") if isinstance(payload, dict) else None
        group = str(payload.get("group") or "") if isinstance(payload, dict) else ""
        if isinstance(keys, list):
            select = [str(item) for item in keys]
        elif group:
            select = settings_spec.group_keys(group)
        else:
            select = None
        defaults = settings_spec.default_values(select)
        try:
            extra = await self._save_values(defaults)
            values_out, secrets = settings_spec.public_values(self.plugin)
            return self._ok(
                saved=True,
                message=f"已恢复 {len(defaults)} 项默认值",
                values=values_out,
                secrets_present=secrets,
                **extra,
            )
        except Exception as exc:
            return self._error(f"恢复默认失败：{type(exc).__name__}", 500)

    async def login_qr(self):
        try:
            session = await asyncio.to_thread(
                self.plugin._qr_login.request_qrcode,
                self._data_dir() / "qrcode",
            )
        except Exception as exc:
            return self._error(f"申请二维码失败：{exc}")
        image = None
        if session.qr_image_path:
            try:
                raw = Path(session.qr_image_path).read_bytes()
                image = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
                Path(session.qr_image_path).unlink(missing_ok=True)
            except Exception:
                image = None
        return self._ok(key=session.qrcode_key, url=session.url, image=image, expires_in=180)

    async def login_status(self):
        key = str(request.args.get("key", "") or "").strip()
        if not key:
            return self._error("缺少二维码 key")
        try:
            result = await asyncio.to_thread(self.plugin._qr_login.poll_status, key)
        except Exception as exc:
            return self._ok(state="error", code=-1, message=f"轮询失败：{exc}")
        if result.code == 0 and result.credentials:
            if not str(result.credentials.get("sessdata") or "").strip():
                return self._ok(
                    state="error",
                    code=0,
                    message="登录已确认，但没有取到 SESSDATA，请刷新二维码重试",
                )
            self.plugin._credentials.save(result.credentials)
            self.plugin._account_cache = None
            account = await self.plugin._bili_account(force=True)
            return self._ok(
                state="confirmed",
                code=0,
                message="登录成功",
                account=account,
                login=self.plugin._login_summary(),
            )
        state = {86101: "waiting", 86090: "scanned", 86038: "expired"}.get(
            result.code, "waiting" if result.code > 0 else "error"
        )
        return self._ok(state=state, code=result.code, message=result.message)

    async def login_account(self):
        refresh = str(request.args.get("refresh", "0") or "").lower() in ("1", "true", "yes")
        try:
            account = await self.plugin._bili_account(force=refresh)
        except Exception as exc:
            return self._error(f"读取账号失败：{type(exc).__name__}", 500)
        return self._ok(
            logged_in=bool(self.plugin._login_summary().get("logged_in")),
            account=account,
            login=self.plugin._login_summary(),
        )

    async def login_logout(self):
        try:
            self.plugin._credentials.clear()
            self.plugin._account_cache = None
            return self._ok(
                cleared=True,
                message="已清除扫码凭据",
                login=self.plugin._login_summary(),
            )
        except Exception as exc:
            return self._error(f"清除凭据失败：{type(exc).__name__}", 500)

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
                    "version": "0.14.1",
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
        active = getattr(self.plugin, "_active", {}) or {}
        if kind in {"frames", "all"} and active:
            return self._error("有视频正在处理中，暂不能清理帧缓存；请等任务结束后再试")
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
