"""极致模式：动态帧预算、动态笔记预算与可读性容量规划。

这里只做纯计算，不访问网络、不调用模型。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

# 无文本、普通运动时的时长基础曲线（秒 -> 帧数）
BASE_CURVE: tuple[tuple[float, int], ...] = (
    (15, 5),
    (30, 7),
    (60, 10),
    (120, 13),
    (300, 18),
    (600, 24),
    (1200, 30),
    (1800, 34),
    (3600, 40),
)

# 16:9 画布、默认可读性目标下每张建议格数
READABILITY_CAPACITY = {"shot": 8, "scene": 6, "text": 4}

FLOOR_CURVE: tuple[tuple[float, int], ...] = (
    (15, 4),
    (60, 6),
    (180, 8),
    (600, 12),
    (10**9, 16),
)


def _interp(points: Sequence[tuple[float, float]], value: float) -> float:
    value = max(0.0, float(value or 0))
    if value <= points[0][0]:
        return float(points[0][1])
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if value <= right_x:
            ratio = (value - left_x) / max(1e-9, right_x - left_x)
            return left_y + (right_y - left_y) * ratio
    return float(points[-1][1])


def base_frames(duration: float) -> float:
    return _interp(BASE_CURVE, duration)


def frame_floor(duration: float) -> int:
    return max(1, int(round(_interp(FLOOR_CURVE, duration))))


def _char_count(lines: Iterable[Any]) -> int:
    total = 0
    for item in lines or []:
        text = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else item
        clean = re.sub(r"[\s\W_]+", "", str(text or ""))
        total += len(clean)
    return total


def _coverage(lines: Iterable[Any], duration: float) -> float:
    stamps = sorted(
        max(0.0, float(item[0]))
        for item in lines or []
        if isinstance(item, (list, tuple)) and item
    )
    if not stamps or duration <= 0:
        return 0.0
    covered = 0.0
    for index, stamp in enumerate(stamps):
        following = stamps[index + 1] if index + 1 < len(stamps) else duration
        covered += max(0.0, min(8.0, following - stamp))
    return min(1.0, covered / max(1.0, duration))


def _diversity(lines: Iterable[Any]) -> float:
    text = "".join(
        str(item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else item)
        for item in lines or []
    )
    text = re.sub(r"\s+", "", text)
    if not text:
        return 0.0
    if re.search(r"[\u4e00-\u9fff]", text):
        grams = [text[i : i + 2] for i in range(max(1, len(text) - 1))]
    else:
        grams = re.findall(r"[a-zA-Z0-9]{2,}", text.lower())
    if not grams:
        return 0.0
    return len(set(grams)) / max(1, len(grams))


@dataclass
class TextProfile:
    status: str = "none"
    coverage: float = 0.0
    density: float = 0.0
    diversity: float = 0.0
    quality: float = 0.0
    score: float = 0.0
    chars: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "coverage": round(self.coverage, 4),
            "density": round(self.density, 4),
            "diversity": round(self.diversity, 4),
            "quality": round(self.quality, 4),
            "score": round(self.score, 4),
            "chars": self.chars,
            "warnings": list(self.warnings),
        }


@dataclass
class VisualProfile:
    cut_rate: float = 0.0
    mean_change: float = 0.0
    scene_count: int = 0
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "cut_rate": round(self.cut_rate, 2),
            "mean_change": round(self.mean_change, 2),
            "scene_count": self.scene_count,
            "score": round(self.score, 4),
        }


@dataclass
class FramePlan:
    duration: int = 0
    base: float = 0.0
    target_frames: int = 0
    actual_frames: int = 0
    floor: int = 0
    cap: int = 0
    cells_per_sheet: int = 6
    max_sheets: int = 8
    readability: str = "scene"
    text: TextProfile = field(default_factory=TextProfile)
    visual: VisualProfile = field(default_factory=VisualProfile)
    reason: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "mode": "extreme",
            "duration": self.duration,
            "base": round(self.base, 2),
            "target_frames": self.target_frames,
            "actual_frames": self.actual_frames,
            "floor": self.floor,
            "cap": self.cap,
            "cells_per_sheet": self.cells_per_sheet,
            "max_sheets": self.max_sheets,
            "readability": self.readability,
            "text": self.text.to_dict(),
            "visual": self.visual.to_dict(),
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


def estimate_text_profile(material: Any) -> TextProfile:
    video = getattr(material, "video", None)
    duration = float(getattr(video, "duration", 0) or 0)
    official = list(getattr(material, "subtitles", []) or [])
    asr = list(getattr(material, "asr_subtitles", []) or [])
    official_status = str(getattr(material, "official_status", "unknown") or "unknown")
    asr_status = str(getattr(material, "asr_status", "unknown") or "unknown")

    if official and asr:
        status = "mixed"
        lines = official
        quality = 0.85
    elif official:
        status = "official"
        lines = official
        quality = 1.0
    elif asr:
        status = "asr"
        lines = asr
        quality = 0.75
    else:
        status = "none"
        lines = []
        quality = 0.0

    coverage = _coverage(lines, duration)
    chars = _char_count(lines)
    minutes = max(1.0 / 60.0, duration / 60.0)
    density = chars / minutes
    diversity = _diversity(lines)
    score = (
        math.sqrt(max(0.0, coverage))
        * min(1.0, density / 240.0)
        * (0.55 + 0.45 * diversity)
        * quality
    )
    warnings: list[str] = []
    if status == "none":
        if official_status in ("failed", "absent") and asr_status in (
            "failed",
            "not_configured",
            "empty",
            "unknown",
        ):
            warnings.append("没有可用字幕/ASR；不等于视频没有人声")
        else:
            warnings.append("没有可用字幕/ASR，画面权重提高")
    if asr_status in ("failed", "empty"):
        warnings.append(f"ASR 状态：{asr_status}；不能据此判断无人声")
    return TextProfile(
        status=status,
        coverage=coverage,
        density=density,
        diversity=diversity,
        quality=quality,
        score=max(0.0, min(1.0, score)),
        chars=chars,
        warnings=warnings,
    )


def readability_label(width: float, height: float) -> str:
    """按目标尺寸给实际格子标注可读性等级。"""

    width, height = max(0.0, float(width)), max(0.0, float(height))
    if width >= 480 * 0.95 and height >= 270 * 0.95:
        return "text"
    if width >= 320 * 0.95 and height >= 180 * 0.95:
        return "scene"
    if width >= 160 * 0.95 and height >= 90 * 0.95:
        return "shot"
    return "composition"


def estimate_visual_profile(keyframes: Sequence[Any], duration: float) -> VisualProfile:
    if not keyframes:
        return VisualProfile()
    cuts = sum(1 for item in keyframes if getattr(item, "via", "") == "cut")
    scores = [max(0.0, float(getattr(item, "score", 0) or 0)) for item in keyframes]
    mean_change = sum(scores) / max(1, len(scores))
    minutes = max(1.0 / 60.0, float(duration or 0) / 60.0)
    cut_rate = cuts / minutes
    score = 0.5 * min(1.0, cut_rate / 20.0) + 0.5 * min(1.0, mean_change / 60.0)
    return VisualProfile(
        cut_rate=cut_rate,
        mean_change=mean_change,
        scene_count=max(1, cuts + 1),
        score=max(0.0, min(1.0, score)),
    )


def readability_capacity(readability: str) -> int:
    key = str(readability or "scene").strip().lower()
    return READABILITY_CAPACITY.get(key, READABILITY_CAPACITY["scene"])


def plan_frames(
    material: Any,
    keyframes: Sequence[Any],
    max_frames: int = 48,
    max_sheets: int = 8,
    readability: str = "scene",
) -> FramePlan:
    video = getattr(material, "video", None)
    duration = max(0, int(getattr(video, "duration", 0) or 0))
    text = estimate_text_profile(material)
    visual = estimate_visual_profile(keyframes, duration)
    base = base_frames(duration)
    floor = frame_floor(duration)
    capacity = readability_capacity(readability)
    max_frames = max(4, min(64, int(max_frames or 48)))
    max_sheets = max(1, min(12, int(max_sheets or 8)))
    cap = min(max_frames, capacity * max_sheets)

    raw = base * (1.0 - 0.35 * text.score) * (1.0 + 0.30 * visual.score)
    target = max(floor, int(round(raw)))
    target = min(target, cap)
    reason = (
        f"时长 {duration}s，基础 {base:.1f}；"
        f"文本 {text.status}/{text.score:.2f}，画面 {visual.score:.2f}；"
        f"目标 {target}（可读性 {readability}，每张 {capacity}，上限 {cap}）"
    )
    warnings = list(text.warnings)
    if target >= cap and raw > cap:
        warnings.append(
            f"可读性/图片上限把目标从 {int(round(raw))} 调整为 {target}，细节可能遗漏"
        )
    return FramePlan(
        duration=duration,
        base=base,
        target_frames=target,
        actual_frames=0,
        floor=floor,
        cap=cap,
        cells_per_sheet=capacity,
        max_sheets=max_sheets,
        readability=readability,
        text=text,
        visual=visual,
        reason=reason,
        warnings=warnings,
    )


@dataclass
class NoteBudget:
    core_chars: int
    other_chars: int
    total_chars: int
    reason: str
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "core_chars": self.core_chars,
            "other_chars": self.other_chars,
            "total_chars": self.total_chars,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


def estimate_note_budget(
    material: Any,
    frame_plan: FramePlan | None = None,
    core_min: int = 1500,
    core_max: int = 9000,
    other_min: int = 800,
    other_max: int = 3500,
) -> NoteBudget:
    video = getattr(material, "video", None)
    duration = max(0.0, float(getattr(video, "duration", 0) or 0))
    d_min = min(duration, 3600.0) / 60.0
    transcript_chars = min(
        12000,
        _char_count(getattr(material, "subtitles", []) or [])
        + _char_count(getattr(material, "asr_subtitles", []) or []),
    )
    if isinstance(frame_plan, dict):
        frame_n = int(frame_plan.get("actual_frames") or frame_plan.get("target_frames") or 0)
        scenes = int((frame_plan.get("visual") or {}).get("scene_count") or 0)
    else:
        frame_n = int((frame_plan.actual_frames if frame_plan else 0) or 0)
        scenes = int((frame_plan.visual.scene_count if frame_plan else 0) or 0)
    comments = list(getattr(material, "comments", []) or [])
    comment_chars = min(
        20000,
        sum(len(str(getattr(item, "content", "") or "")) for item in comments),
    )
    comment_count = min(50, len(comments))

    core_raw = (
        1500
        + 500 * math.sqrt(d_min)
        + 0.25 * transcript_chars
        + 12 * frame_n
        + 40 * min(scenes, 20)
    )
    other_raw = (
        800
        + 200 * math.sqrt(d_min)
        + 0.08 * comment_chars
        + 3 * frame_n
        + 30 * comment_count
    )
    core_min = max(500, int(core_min or 1500))
    other_min = max(300, int(other_min or 800))
    core_max = max(core_min, int(core_max or 9000))
    other_max = max(other_min, int(other_max or 3500))
    core = max(core_min, min(core_max, int(round(core_raw * 1.1))))
    other = max(other_min, min(other_max, int(round(other_raw * 1.1))))
    return NoteBudget(
        core_chars=core,
        other_chars=other,
        total_chars=core + other,
        reason=(
            f"时长 {duration:.0f}s，文本 {transcript_chars} 字，"
            f"帧 {frame_n}，场景 {scenes}，评论 {len(comments)} 条"
        ),
    )
