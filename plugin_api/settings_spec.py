"""WebUI 设置字段规格与校验。

页面不直接读 `_conf_schema.json`；服务端从这里给出分组、控件和默认值，
保存时也用同一份规格做白名单校验，避免页面与真实配置漂移。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "_conf_schema.json"
SECRET_KEYS = {"sessdata"}
CLEAR = "__clear__"


def _load_schema() -> dict:
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


SCHEMA = _load_schema()


def _field_kind(raw: dict) -> str:
    kind = str(raw.get("type") or "string").lower()
    if kind in ("bool", "int", "float", "list"):
        return kind
    if kind == "text":
        return "text"
    return "string"


def schema_groups() -> list[dict]:
    groups: list[dict] = []
    for group_id, group in SCHEMA.items():
        if not isinstance(group, dict):
            continue
        fields: list[dict] = []
        for key, raw in (group.get("items") or {}).items():
            if not isinstance(raw, dict) or str(key).startswith("_"):
                continue
            kind = _field_kind(raw)
            if key in SECRET_KEYS:
                kind = "secret"
            options = raw.get("options") or []
            fields.append(
                {
                    "key": str(key),
                    "label": str(raw.get("description") or key),
                    "kind": kind,
                    "hint": str(raw.get("hint") or ""),
                    "default": raw.get("default"),
                    "options": [
                        {"value": str(item), "label": str(item)} for item in options
                    ],
                    "wide": kind in ("text", "list"),
                }
            )
        if fields:
            groups.append(
                {
                    "id": str(group_id),
                    "title": str(group.get("description") or group_id),
                    "desc": str(group.get("hint") or ""),
                    "fields": fields,
                }
            )
    return groups


GROUPS = schema_groups()
FIELDS: dict[str, dict] = {
    field["key"]: field
    for group in GROUPS
    for field in group["fields"]
}


def _value(plugin: Any, key: str) -> Any:
    try:
        return plugin._opt(key)
    except Exception:
        return FIELDS.get(key, {}).get("default")


def public_values(plugin: Any) -> tuple[dict, dict]:
    values: dict[str, Any] = {}
    secrets_present: dict[str, bool] = {}
    for key, field in FIELDS.items():
        value = _value(plugin, key)
        if field["kind"] == "secret":
            secrets_present[key] = bool(str(value or "").strip())
            values[key] = ""
        else:
            values[key] = value
    return values, secrets_present


def _parse_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "开", "开启"}


def _parse_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        text = str(value or "").replace("，", ",")
        items = [part for part in text.replace("\n", ",").split(",")]
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in result:
            result.append(text)
    return result


def validate_values(incoming: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(incoming, dict):
        return {}, ["请求内容必须是对象"]
    clean: dict[str, Any] = {}
    errors: list[str] = []
    for key, value in incoming.items():
        field = FIELDS.get(key)
        if field is None:
            errors.append(f"未知配置项：{key}")
            continue
        kind = field["kind"]
        if kind == "secret":
            if value == CLEAR:
                clean[key] = ""
            elif str(value or "").strip():
                clean[key] = str(value).strip()
            continue
        if kind == "bool":
            clean[key] = _parse_bool(value)
        elif kind == "int":
            try:
                clean[key] = int(value)
            except (TypeError, ValueError):
                errors.append(f"{field['label']} 必须是整数")
        elif kind == "float":
            try:
                clean[key] = float(value)
            except (TypeError, ValueError):
                errors.append(f"{field['label']} 必须是数字")
        elif kind == "list":
            clean[key] = _parse_list(value)
        else:
            text = str(value or "")
            if len(text) > 30000:
                errors.append(f"{field['label']} 过长")
            else:
                clean[key] = text
        options = {item["value"] for item in field.get("options") or []}
        if options and key in clean and str(clean[key]) not in options:
            errors.append(f"{field['label']} 不是可选值")
    return clean, errors


def default_values(keys: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, field in FIELDS.items():
        if keys is not None and key not in keys:
            continue
        result[key] = field.get("default")
    return result


def group_keys(group_id: str) -> list[str]:
    for group in GROUPS:
        if group["id"] == group_id:
            return [field["key"] for field in group["fields"]]
    return []


__all__ = [
    "CLEAR",
    "FIELDS",
    "GROUPS",
    "SECRET_KEYS",
    "default_values",
    "group_keys",
    "public_values",
    "schema_groups",
    "validate_values",
]
