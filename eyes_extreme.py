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
    sheet_width: int = 1280
    sheet_height: int = 720
    pixel_budget: int = 1200000
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
            "sheet_width": self.sheet_width,
            "sheet_height": self.sheet_height,
            "pixel_budget": self.pixel_budget,
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


def candidate_groups(keyframes: Sequence[Any], duration: float) -> list[dict]:
    """为每个关键帧生成 2~3 个候选时间，避开切点。"""

    duration = max(0.0, float(duration or 0))
    groups: list[dict] = []
    for item in keyframes:
        base = float(getattr(item, "time", 0) or 0)
        via = str(getattr(item, "via", "") or "")
        if via == "cut":
            offsets = (0.25, 0.55, 0.9)
        else:
            offsets = (-0.18, 0.0, 0.18)
        times = []
        for offset in offsets:
            stamp = base + offset
            if 0 <= stamp <= max(0.0, duration - 0.05):
                times.append(round(stamp, 2))
        if not times:
            times = [round(min(max(0.0, base), max(0.0, duration - 0.05)), 2)]
        groups.append({"target": round(base, 2), "times": sorted(set(times))})
    return groups


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


NEED_SIZE = {"shot": (160, 90), "scene": (320, 180), "text": (480, 270)}
GUTTER = 4


def plan_sheet_layout(
    readability: str = "scene",
    pixel_budget: int = 1200000,
    base_width: int = 1280,
    max_cells: int = 16,
) -> dict:
    """在 16:9 画布和像素预算内规划每张最多几格。"""

    key = str(readability or "scene").strip().lower()
    if key not in NEED_SIZE:
        key = "scene"
    target_w, target_h = NEED_SIZE[key]
    budget = max(200000, min(4000000, int(pixel_budget or 1200000)))
    base_width = max(320, min(2560, int(base_width or 1280)))
    width = min(base_width, max(320, int(math.sqrt(budget * 16 / 9))))
    height = max(180, int(round(width * 9 / 16)))
    max_cells = max(1, min(24, int(max_cells or 16)))
    capacity = 1
    columns = rows = 1
    for count in range(1, max_cells + 1):
        best_for_count = None
        for cols in range(1, count + 1):
            row_count = int(math.ceil(count / cols))
            cell_w = (width - (cols + 1) * GUTTER) // max(1, cols)
            cell_h = (height - (row_count + 1) * GUTTER) // max(1, row_count)
            image_w = min(cell_w, int(cell_h * 16 / 9))
            image_h = min(cell_h, int(image_w * 9 / 16))
            if image_w < target_w * 0.95 or image_h < target_h * 0.95:
                continue
            score = image_w * image_h
            if best_for_count is None or score > best_for_count[0]:
                best_for_count = (score, cols, row_count)
        if best_for_count is not None:
            _, columns, rows = best_for_count
            capacity = count
    return {
        "readability": key,
        "width": width,
        "height": height,
        "capacity": capacity,
        "columns": columns,
        "rows": rows,
        "pixel_budget": budget,
        "target_cell": [target_w, target_h],
    }


def readability_capacity(readability: str) -> int:
    key = str(readability or "scene").strip().lower()
    return READABILITY_CAPACITY.get(key, READABILITY_CAPACITY["scene"])


def _text_chars_between(lines: Iterable[Any], start: float, end: float) -> int:
    total = 0
    for item in lines or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        try:
            stamp = float(item[0])
        except Exception:
            continue
        if start <= stamp < end:
            total += len(re.sub(r"[\s\W_]+", "", str(item[1] or "")))
    return total


def _scene_boundaries(
    keyframes: Sequence[Any], duration: float, target: int
) -> list[float]:
    duration = max(0.1, float(duration or 0))
    cuts = sorted(
        float(getattr(item, "time", 0) or 0)
        for item in keyframes
        if getattr(item, "via", "") == "cut"
        and 0.1 < float(getattr(item, "time", 0) or 0) < duration - 0.1
    )
    # 去重并合并过近切点，避免 0.1 秒一个“场景”。
    boundaries = [0.0]
    for stamp in cuts:
        if stamp - boundaries[-1] >= 0.6:
            boundaries.append(stamp)
    boundaries.append(duration)
    # 切点太少时补均匀时间边界，避免整段只剩 1~2 个场景，
    # 导致帧预算被单场景的 4 帧上限吃掉。
    min_scenes = max(1, min(target, int(math.ceil(target / 4.0))))
    if len(boundaries) - 1 < min_scenes:
        boundaries = [duration * index / min_scenes for index in range(min_scenes + 1)]
    # 场景数远大于目标时，合并最短的相邻场景。
    while len(boundaries) - 1 > max(1, target):
        spans = [
            (boundaries[index + 1] - boundaries[index], index)
            for index in range(len(boundaries) - 1)
        ]
        _, merge_at = min(spans)
        boundaries.pop(merge_at + 1)
    return boundaries


def plan_scene_times(
    material: Any,
    keyframes: Sequence[Any],
    target: int,
    duration: float,
) -> list[dict]:
    """按场景权重分配目标帧数；返回按时序排列的时间点。"""

    duration = max(0.1, float(duration or 0))
    target = max(1, int(target or 1))
    boundaries = _scene_boundaries(keyframes, duration, target)
    scenes = max(1, len(boundaries) - 1)
    # 目标小于场景数时，上面已合并；补足到最少 1。
    if scenes > target:
        scenes = target
        boundaries = [duration * i / target for i in range(target + 1)]
    official = getattr(material, "subtitles", []) or []
    asr = getattr(material, "asr_subtitles", []) or []
    lines = official or asr
    max_score = max(
        [max(0.0, float(getattr(item, "score", 0) or 0)) for item in keyframes] or [1.0]
    )
    weights = []
    for start, end in zip(boundaries, boundaries[1:]):
        span = max(0.1, end - start)
        scene_scores = [
            max(0.0, float(getattr(item, "score", 0) or 0))
            for item in keyframes
            if start <= float(getattr(item, "time", 0) or 0) < end
        ]
        visual = (sum(scene_scores) / max(1, len(scene_scores))) / max(1.0, max_score)
        chars = _text_chars_between(lines, start, end)
        cpm = chars / max(1.0 / 60.0, span / 60.0)
        text_gap = 1.0 - min(1.0, cpm / 240.0)
        weights.append(0.25 + 0.75 * min(1.0, visual) + 0.25 * text_gap)

    quotas = [1] * scenes
    remaining = max(0, target - scenes)
    while remaining > 0:
        candidates = [index for index in range(scenes) if quotas[index] < 4]
        if not candidates:
            break
        index = max(candidates, key=lambda pos: weights[pos] / (quotas[pos] + 1))
        quotas[index] += 1
        remaining -= 1

    result: list[dict] = []
    for scene_index, ((start, end), quota) in enumerate(
        zip(zip(boundaries, boundaries[1:]), quotas)
    ):
        span = max(0.1, end - start)
        existing = sorted(
            float(getattr(item, "time", 0) or 0)
            for item in keyframes
            if start <= float(getattr(item, "time", 0) or 0) < end
        )
        used: set[float] = set()
        for index in range(quota):
            ratio = (index + 1) / (quota + 1)
            target_time = start + span * ratio
            stamp = target_time
            if existing:
                nearest = min(
                    (value for value in existing if value not in used),
                    key=lambda value: abs(value - target_time),
                    default=None,
                )
                if nearest is not None and abs(nearest - target_time) <= max(
                    1.0, span / max(1, quota) * 0.75
                ):
                    stamp = nearest
                    used.add(nearest)
            result.append(
                {
                    "time": round(min(max(0.0, stamp), max(0.0, duration - 0.05)), 2),
                    "from": round(start, 2),
                    "to": round(end, 2),
                    "via": "cut" if start > 0 else "mark",
                    "score": max(0.0, weights[scene_index]),
                }
            )
    return result


def plan_frames(
    material: Any,
    keyframes: Sequence[Any],
    max_frames: int = 48,
    max_sheets: int = 8,
    readability: str = "scene",
    pixel_budget: int = 1200000,
    base_sheet_width: int = 1280,
) -> FramePlan:
    video = getattr(material, "video", None)
    duration = max(0, int(getattr(video, "duration", 0) or 0))
    text = estimate_text_profile(material)
    visual = estimate_visual_profile(keyframes, duration)
    base = base_frames(duration)
    floor = frame_floor(duration)
    layout = plan_sheet_layout(
        readability,
        pixel_budget,
        base_width=base_sheet_width,
        max_cells=24,
    )
    capacity = int(layout["capacity"])
    max_frames = max(4, min(64, int(max_frames or 48)))
    max_sheets = max(1, min(12, int(max_sheets or 8)))
    cap = min(max_frames, capacity * max_sheets)

    raw = base * (1.0 - 0.35 * text.score) * (1.0 + 0.30 * visual.score)
    target = max(floor, int(round(raw)))
    target = min(target, cap)
    reason = (
        f"时长 {duration}s，基础 {base:.1f}；"
        f"文本 {text.status}/{text.score:.2f}，画面 {visual.score:.2f}；"
        f"目标 {target}（可读性 {readability}，每张 {capacity}，"
        f"画布 {layout['width']}×{layout['height']}，上限 {cap}）"
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
        sheet_width=int(layout["width"]),
        sheet_height=int(layout["height"]),
        pixel_budget=int(layout["pixel_budget"]),
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
