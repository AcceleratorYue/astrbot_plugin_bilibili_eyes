"""增强模式：画面变化选帧、16:9 分镜拼图与 DP 装箱。

普通模式不导入本模块。这里的算法参考 dsh-see-now 的
"变化分 + 切点/积分 + tiers + DP 装箱" 思路，按 B站离线视频重写。
"""

from __future__ import annotations

import math
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw

SCAN_W = 64
SCAN_H = 36
UNIT = 840
FREE = 0
DEFAULT_GROW = (3, 4, 5, 6, 7, 8)
LEVEL_THRESHOLDS = (0.26, 0.6, 0.9, 1.2, 1.8, 2.4, 3.0)
REF_SCORE = 4.0


@dataclass
class EnhancedConfig:
    frame_count: int = 24
    sample_fps: int = 2
    max_analysis_seconds: int = 1200
    cut_abs: float = 12.0
    cut_spike: float = 2.5
    cut_min_gap: float = 0.4
    integral_seconds: float = 3.0
    dup_min: float = 8.0
    silent_floor_seconds: float = 20.0
    sheet_width: int = 1280
    sheet_height: int = 720
    gutter: int = 4


@dataclass
class FrameSample:
    time: float
    hsv: array
    score: float = 0.0


@dataclass
class Keyframe:
    time: float
    score: float = 0.0
    via: str = "sample"


@dataclass
class PackCell:
    x: float
    y: float
    w: float
    h: float
    tier: int
    seq: int
    bin: int = 0


def rgb_to_hsv(rgb: bytes, width: int = SCAN_W, height: int = SCAN_H) -> array:
    """RGB24 → HSV，H/S/V 都缩放到 0–255。"""

    out = array("f", [0.0]) * (width * height * 3)
    count = min(width * height, len(rgb) // 3)
    for index in range(count):
        offset = index * 3
        rn = rgb[offset] / 255.0
        gn = rgb[offset + 1] / 255.0
        bn = rgb[offset + 2] / 255.0
        maximum = max(rn, gn, bn)
        minimum = min(rn, gn, bn)
        delta = maximum - minimum
        if delta == 0:
            hue = 0.0
        elif maximum == rn:
            hue = ((gn - bn) / delta) % 6
        elif maximum == gn:
            hue = (bn - rn) / delta + 2
        else:
            hue = (rn - gn) / delta + 4
        hue *= 60.0
        if hue < 0:
            hue += 360.0
        out[offset] = (hue / 360.0) * 255.0
        out[offset + 1] = 0.0 if maximum == 0 else (delta / maximum) * 255.0
        out[offset + 2] = maximum * 255.0
    return out


def score_pair(previous: Sequence[float], current: Sequence[float]) -> float:
    """HSV 三通道加权绝对差，0–255。"""

    if not previous or not current:
        return 0.0
    total = 0.0
    count = min(len(previous), len(current)) // 3
    for index in range(count):
        base = index * 3
        dh = abs(current[base] - previous[base])
        hue_diff = min(dh, 255.0 - dh)
        hue_weight = min(current[base + 1], previous[base + 1]) / 255.0
        total += (
            hue_diff * hue_weight
            + abs(current[base + 1] - previous[base + 1])
            + abs(current[base + 2] - previous[base + 2])
        )
    return total / max(1, count * 3)


def build_samples(frames: Iterable[tuple[float, bytes]]) -> list[FrameSample]:
    samples: list[FrameSample] = []
    previous = None
    for timestamp, raw in frames:
        hsv = rgb_to_hsv(raw)
        score = score_pair(previous, hsv) if previous is not None else 0.0
        samples.append(FrameSample(float(timestamp), hsv, score))
        previous = hsv
    return samples


def _thin_keyframes(items: list[Keyframe], limit: int) -> list[Keyframe]:
    if len(items) <= limit:
        return items
    cuts = [item for item in items if item.via == "cut"]
    if len(cuts) >= limit:
        step = len(cuts) / limit
        return [cuts[min(len(cuts) - 1, int(index * step))] for index in range(limit)]
    chosen: list[Keyframe] = list(cuts)
    remaining = [item for item in items if item.via != "cut"]
    need = limit - len(chosen)
    if need > 0 and remaining:
        step = max(1, len(remaining) // need)
        chosen.extend(remaining[::step][:need])
    return sorted(chosen, key=lambda item: item.time)


def _fill_keyframes(
    items: list[Keyframe], duration: float, limit: int
) -> list[Keyframe]:
    if len(items) >= limit or duration <= 0:
        return items
    occupied = [item.time for item in items]
    for index in range(limit - len(items)):
        ratio = (index + 1) / (limit - len(items) + 1)
        timestamp = duration * (0.05 + 0.9 * ratio)
        if all(abs(timestamp - old) > 1.0 for old in occupied):
            items.append(Keyframe(timestamp, 0.0, "uniform"))
            occupied.append(timestamp)
    return sorted(items, key=lambda item: item.time)


def select_keyframes(
    samples: Sequence[FrameSample],
    duration: float,
    config: EnhancedConfig,
) -> list[Keyframe]:
    """切点 + 积分 + 静止兜底 + 相似去重。"""

    if not samples:
        return []
    count = max(1, int(config.frame_count))
    scores = [float(item.score) for item in samples]
    need = REF_SCORE * max(1, int(config.sample_fps)) * max(
        0.1, float(config.integral_seconds)
    )
    selected: list[Keyframe] = []
    last_cut = -1e9
    last_keep = -1e9
    last_hsv = None
    integral = 0.0

    for index, sample in enumerate(samples):
        previous = scores[index - 1] if index > 0 else 0.0
        following = scores[index + 1] if index + 1 < len(scores) else 0.0
        cut = (
            sample.score >= float(config.cut_abs)
            and sample.score
            > float(config.cut_spike) * max(1.0, previous, following)
            and sample.time - last_cut >= float(config.cut_min_gap)
        )
        reason = ""
        if index == 0:
            reason = "first"
        elif cut:
            reason = "cut"
        else:
            integral += sample.score
            if integral >= need:
                reason = "mark"
            elif sample.time - last_keep >= float(config.silent_floor_seconds):
                reason = "floor"

        if not reason:
            continue
        if reason not in ("cut", "first", "floor") and last_hsv is not None:
            if score_pair(last_hsv, sample.hsv) < float(config.dup_min):
                continue
        selected.append(Keyframe(sample.time, sample.score, reason))
        last_hsv = sample.hsv
        last_keep = sample.time
        integral = 0.0
        if reason == "cut":
            last_cut = sample.time

    selected = _thin_keyframes(selected, count)
    selected = _fill_keyframes(selected, duration, count)
    return _thin_keyframes(selected, count)


def select_keyframes_from_stream(
    client,
    stream_url: str,
    duration: float,
    config: EnhancedConfig,
) -> list[Keyframe]:
    """从 B站视频流低分辨率采样并选出关键帧。"""

    max_seconds = min(
        max(1, int(duration or config.max_analysis_seconds)),
        max(1, int(config.max_analysis_seconds)),
    )
    frames = client.iter_lowres_frames(
        stream_url,
        fps=max(1, int(config.sample_fps)),
        max_seconds=max_seconds,
        width=SCAN_W,
        height=SCAN_H,
    )
    samples = build_samples(frames)
    return select_keyframes(samples, float(max_seconds), config)


def assign_tiers(
    times: Sequence[float],
    window_seconds: float = 2.0,
) -> list[int]:
    """按入选帧的局部密度分配 tier 1–8。"""

    ordered = sorted(float(t) for t in times)
    window = max(0.5, float(window_seconds))
    # 16:9 画布上的 16:9 单元格可看作方形格；N 帧至少需要
    # ceil(sqrt(N)) 档，否则 DP 会因一箱装不下而提前截断。
    minimum_tier = max(1, int(math.ceil(math.sqrt(max(1, len(ordered))))))
    tiers: list[int] = []
    for timestamp in ordered:
        density = (
            sum(1 for other in ordered if timestamp - window < other <= timestamp)
            / window
        )
        level = 1 + sum(density >= threshold for threshold in LEVEL_THRESHOLDS)
        tiers.append(max(minimum_tier, min(8, level)))
    return tiers


def _bounds(tier: int, grow: Sequence[int] = DEFAULT_GROW) -> tuple[float, float]:
    if tier == FREE:
        return UNIT / 24.0, UNIT / 2.0
    lower = UNIT / (tier + 1)
    upper = UNIT / (tier - 1) if tier >= 3 and tier in grow else UNIT / tier
    return lower, upper


_ROW_CACHE: dict[tuple, list[dict]] = {}


def _row_options_raw(
    tiers: Sequence[int],
    grow: Sequence[int] = DEFAULT_GROW,
    stretch: float = 0.2,
    fill_rows: bool = True,
) -> list[dict]:
    sizes = [UNIT / 4.0 if tier == FREE else UNIT / tier for tier in tiers]
    lows = [_bounds(tier, grow)[0] for tier in tiers]
    highs = [_bounds(tier, grow)[1] for tier in tiers]
    if sum(lows) > UNIT + 1e-9:
        return []
    out: list[dict] = []
    if sum(sizes) <= UNIT + 1e-9:
        out.append(
            {
                "c": max(sizes),
                "A": sum(value * value for value in sizes),
                "s": list(sizes),
            }
        )
    c_min = max(lows)
    if any(abs(lows[index] - sizes[index]) > 1e-9 for index in range(len(tiers))):
        out.append(
            {
                "c": c_min,
                "A": sum(value * value for value in lows),
                "s": list(lows),
            }
        )
    if not fill_rows:
        return out

    if sum(highs) < UNIT - 1e-9:
        fitted = list(highs)
    else:
        low = 0.0
        high = max(highs)
        for _ in range(24):
            middle = (low + high) / 2.0
            total = sum(
                min(max(middle, lows[index]), highs[index])
                for index in range(len(tiers))
            )
            if total < UNIT:
                low = middle
            else:
                high = middle
        fitted = [
            min(max(high, lows[index]), highs[index])
            for index in range(len(tiers))
        ]
        total = sum(fitted)
        if total > UNIT:
            fitted = [value * UNIT / total for value in fitted]

    row_height = max(fitted)
    area = sum(value * value for value in fitted)
    if not out or any(
        abs(item["c"] - row_height) > 1e-9 or abs(item["A"] - area) > 1e-9
        for item in out
    ):
        out.append({"c": row_height, "A": area, "s": fitted})

    if stretch > 0 and len(fitted) > 1:
        widest = max(fitted)
        narrowest = min(fitted)
        if widest <= narrowest * ((1 + stretch) / (1 - stretch)) + 1e-9:
            height = widest / (1 + stretch)
            area = height * sum(fitted)
            if not any(
                abs(item["c"] - height) < 1e-9
                and abs(item["A"] - area) < 1e-9
                for item in out
            ):
                out.append({"c": height, "A": area, "s": list(fitted), "flat": True})
    return out


def row_options(
    tiers: Sequence[int],
    grow: Sequence[int] = DEFAULT_GROW,
    stretch: float = 0.2,
    fill_rows: bool = True,
) -> list[dict]:
    key = (tuple(int(t) for t in tiers), tuple(grow), bool(stretch > 0.15), fill_rows)
    if key in _ROW_CACHE:
        return _ROW_CACHE[key]
    if len(_ROW_CACHE) > 20000:
        _ROW_CACHE.clear()
    _ROW_CACHE[key] = _row_options_raw(tiers, grow, stretch, fill_rows)
    return _ROW_CACHE[key]


def _precompute(
    tiers: Sequence[int],
    grow: Sequence[int] = DEFAULT_GROW,
    stretch: float = 0.2,
    fill_rows: bool = True,
) -> list[list[list[dict]]]:
    count = len(tiers)
    options: list[list[list[dict]]] = [[] for _ in range(count)]
    for index in range(count):
        for length in range(1, 9):
            if index + length > count:
                break
            rows = row_options(
                tiers[index : index + length], grow, stretch, fill_rows
            )
            if not rows:
                break
            options[index].append(rows)
    return options


def solve(
    tiers: Sequence[int],
    grow: Sequence[int] = DEFAULT_GROW,
    mu: float = 1.0,
    stretch: float = 0.2,
    bin_cost: float = 1.02,
    fill_rows: bool = True,
) -> dict:
    """完整 DP：按行装箱，返回归一化格子。"""

    count = len(tiers)
    if not count:
        return {"bins": 0, "fill": 0.0, "cells": [], "area": 0.0}
    options = _precompute(tiers, grow, stretch, fill_rows)
    capacity = UNIT
    bin_area = UNIT * UNIT
    close = bin_area * float(bin_cost)
    rows = [dict() for _ in range(count + 1)]
    rows[0][0] = (0.0, 0.0, None)

    for index in range(count):
        current = rows[index]
        if not current:
            continue
        best_close = -math.inf
        best_area = 0.0
        close_height = None
        for height, (value, area, _back) in current.items():
            candidate = value - close
            if candidate > best_close:
                best_close = candidate
                best_area = area
                close_height = height
        if close_height is not None and 0 not in current:
            current[0] = (best_close, best_area, {"close": close_height})

        for height, (value, area, _back) in list(current.items()):
            for length in range(1, len(options[index]) + 1):
                target = rows[index + length]
                for option in options[index][length - 1]:
                    row_height = int(round(option["c"]))
                    new_height = height + row_height
                    new_value = value + mu * option["A"]
                    if new_height > capacity:
                        new_value -= close
                        new_height = row_height
                    old = target.get(new_height)
                    if old is None or new_value > old[0]:
                        target[new_height] = (
                            new_value,
                            area + option["A"],
                            {
                                "i": index,
                                "C": height,
                                "s": list(option["s"]),
                                "flat": bool(option.get("flat")),
                                "c": option["c"],
                            },
                        )

    best_value = -math.inf
    best_height = None
    for height, (value, _area, _back) in rows[count].items():
        candidate = value - close
        if candidate > best_value:
            best_value = candidate
            best_height = height

    selected_rows: list[dict] = []
    index = count
    height = best_height
    while index > 0 and height is not None:
        state = rows[index].get(height)
        if not state:
            break
        back = state[2]
        if back is None:
            break
        if "close" in back:
            height = back["close"]
            continue
        selected_rows.append(back)
        index = back["i"]
        height = back["C"]
    selected_rows.reverse()

    cells: list[PackCell] = []
    bin_height = 0.0
    bin_index = 0
    for row in selected_rows:
        sizes = row["s"]
        row_height = row["c"] if row.get("flat") else max(sizes)
        normalized_height = row_height / UNIT
        if bin_height + normalized_height > 1 + 1e-9:
            bin_height = 0.0
            bin_index += 1
        x = 0.0
        for offset, size in enumerate(sizes):
            tier = int(tiers[row["i"] + offset])
            cells.append(
                PackCell(
                    x=x / UNIT,
                    y=bin_height,
                    w=size / UNIT,
                    h=(row_height if row.get("flat") else size) / UNIT,
                    tier=tier,
                    seq=len(cells),
                    bin=bin_index,
                )
            )
            x += size
        bin_height += normalized_height

    bins = max((cell.bin for cell in cells), default=-1) + 1
    area = sum(cell.w * cell.h for cell in cells)
    return {
        "bins": bins,
        "fill": area / bins if bins else 0.0,
        "cells": cells,
        "area": area,
    }


def split_one_bin(
    tiers: Sequence[int],
    **options,
) -> list[list[int]]:
    """切成每段都只占一张图的 tier 序列。"""

    segments: list[list[int]] = []
    current: list[int] = []
    for tier in tiers:
        candidate = current + [int(tier)]
        if current and solve(candidate, **options)["bins"] > 1:
            segments.append(current)
            current = [int(tier)]
        else:
            current = candidate
    if current:
        segments.append(current)
    return segments


@dataclass
class SheetFrame:
    time: float
    path: Path
    tier: int


@dataclass
class SheetLayout:
    sheet: Path
    frames: list[SheetFrame] = field(default_factory=list)
    cells: list[dict] = field(default_factory=list)


def to_rects(
    cells: Sequence[PackCell],
    width: int,
    height: int,
    gutter: int = 0,
) -> list[dict]:
    rects = []
    for index, cell in enumerate(cells):
        rects.append(
            {
                "x": cell.x,
                "y": cell.y,
                "w": cell.w,
                "h": cell.h,
                "tier": cell.tier,
                "index": index + 1,
                "px": max(0, int(round(cell.x * width)) + gutter),
                "py": max(0, int(round(cell.y * height)) + gutter),
                "pw": max(1, int(round(cell.w * width)) - gutter * 2),
                "ph": max(1, int(round(cell.h * height)) - gutter * 2),
            }
        )
    return rects


def compose_sheet(
    frames: Sequence[SheetFrame],
    cells: Sequence[PackCell],
    output: Path,
    width: int = 1280,
    height: int = 720,
    gutter: int = 4,
) -> SheetLayout:
    """把帧按 DP 格子铺进 16:9 画布。"""

    canvas = Image.new("RGB", (width, height), (18, 18, 18))
    draw = ImageDraw.Draw(canvas)
    rects = to_rects(cells, width, height, gutter)
    layout_cells: list[dict] = []
    for index, (frame, rect) in enumerate(zip(frames, rects)):
        if index >= len(cells):
            break
        try:
            image = Image.open(frame.path).convert("RGB")
        except Exception:
            continue
        box_width = max(1, rect["pw"])
        box_height = max(1, rect["ph"])
        image.thumbnail((box_width, box_height))
        x = rect["px"] + (box_width - image.width) // 2
        y = rect["py"] + (box_height - image.height) // 2
        canvas.paste(image, (x, y))
        label = f"{index + 1} {_fmt_time(frame.time)}"
        draw.rectangle(
            [rect["px"], rect["py"], rect["px"] + 86, rect["py"] + 18],
            fill=(0, 0, 0),
        )
        draw.text((rect["px"] + 3, rect["py"] + 3), label, fill=(255, 230, 80))
        layout_cells.append(
            {
                "index": index + 1,
                "time": round(frame.time, 2),
                "tier": int(frame.tier),
                "x": rect["px"],
                "y": rect["py"],
                "w": rect["pw"],
                "h": rect["ph"],
            }
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=90)
    return SheetLayout(output, list(frames), layout_cells)


def _fmt_time(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, sec = divmod(total, 60)
    return f"{minutes:02d}:{sec:02d}"
