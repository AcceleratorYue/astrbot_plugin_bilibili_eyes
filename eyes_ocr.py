"""内嵌画面字幕 OCR。

只依赖 ffmpeg 与可选的 RapidOCR；OCR 失败时由主流程回退 ASR。
"""

from __future__ import annotations

import difflib
import io
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from PIL import Image

import eyes_client as bc


@dataclass
class OcrConfig:
    enabled: bool = True
    mode: str = "auto"
    fps: int = 1
    min_confidence: float = 0.6
    region: str = "auto"
    engine: str = "auto"
    max_seconds: int = 1200
    min_coverage: float = 0.15
    frame_width: int = 960
    frame_height: int = 320
    max_samples: int = 120
    time_budget: float = 60.0


@dataclass
class OcrResult:
    tracks: list[bc.SubtitleTrack] = field(default_factory=list)
    status: str = "unknown"
    coverage: float = 0.0
    warnings: list[str] = field(default_factory=list)
    elapsed: float = 0.0

    @property
    def usable(self) -> bool:
        return self.status in ("available", "partial") and bool(self.tracks)


def _clean_lines(lines: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for item in lines or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if text:
            result.append(text)
    return result


def _cjk_ratio(text: str) -> float:
    text = str(text or "")
    if not text:
        return 0.0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    letters = len(re.findall(r"[A-Za-z]", text))
    return cjk / max(1, cjk + letters)


def _split_bilingual(text: str) -> tuple[str, str | None]:
    """把上下两行的中英硬字幕拆成主/辅文本；单行混合则保持原样。"""

    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return str(text or "").strip(), None
    cjk = [line for line in lines if _cjk_ratio(line) >= 0.3]
    latin = [line for line in lines if _cjk_ratio(line) < 0.3]
    if len(cjk) == 1 and len(latin) == 1 and len(lines) == 2:
        return cjk[0], latin[0]
    return " ".join(lines), None


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, str(a or ""), str(b or "")).ratio()


def _looks_same(previous: bytes, current: bytes) -> bool:
    if not previous or len(previous) != len(current):
        return False
    step = max(1, len(current) // 250)
    left = previous[::step]
    right = current[::step]
    if not left:
        return False
    diff = sum(abs(a - b) for a, b in zip(left, right)) / len(left)
    return diff < 8.0


class RapidOcrEngine:
    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        self.engine = RapidOCR()

    def recognize(self, image: Image.Image) -> list[tuple[str, float, float]]:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        result, _ = self.engine(buffer.getvalue())
        lines: list[tuple[str, float, float]] = []
        for item in result or []:
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            box, content, score = item[0], str(item[1] or ""), item[2]
            text = re.sub(r"\s+", " ", content).strip()
            if not text:
                continue
            y = 0.0
            try:
                y = float(box[0][1])
            except Exception:
                pass
            try:
                confidence = float(score)
            except Exception:
                confidence = 0.0
            lines.append((text, confidence, y))
        lines.sort(key=lambda item: item[2])
        return lines


def _make_engine(name: str):
    value = str(name or "auto").strip().lower()
    if value in ("auto", "rapidocr", "rapidocr_onnxruntime"):
        return RapidOcrEngine()
    raise RuntimeError(f"不支持的 OCR 引擎：{name}")


def evaluate_asr_quality(lines: Iterable[Any]) -> tuple[bool, str]:
    """识别 ASR 常见幻觉；返回 (是否可用, 原因)。"""

    texts = [str(item).strip() for item in lines or [] if str(item).strip()]
    if not texts:
        return False, "empty"
    if len(texts) < 3:
        return True, ""
    unique_ratio = len(set(texts)) / len(texts)
    avg_chars = sum(len(text) for text in texts) / len(texts)
    if unique_ratio < 0.55 and avg_chars < 3.0:
        return False, "high_repetition"
    filler = 0
    for text in texts:
        lowered = text.lower().strip(" ?!！？.,，。")
        if lowered in {"why", "what", "huh", "嗯", "啊", "哦", "呃", "what?", "why?"}:
            filler += 1
    if filler / max(1, len(texts)) > 0.35:
        return False, "filler_heavy"
    if avg_chars < 2.0:
        return False, "too_short"
    return True, ""


def _frame_lines(
    engine: Any,
    raw: bytes,
    width: int,
    height: int,
    min_confidence: float,
) -> tuple[str, float]:
    image = Image.frombytes("RGB", (int(width), int(height)), raw)
    lines = [
        (text, confidence, y)
        for text, confidence, y in engine.recognize(image)
        if confidence >= min_confidence
        and not (len(text) < 3 and confidence < 0.8)
    ]
    if not lines:
        return "", 0.0
    text = "\n".join(item[0] for item in lines)
    confidence = sum(item[1] for item in lines) / len(lines)
    return text, confidence


def extract_embedded_subtitles(
    client: Any,
    stream_url: str,
    duration: float,
    config: OcrConfig,
    engine: Any | None = None,
) -> OcrResult:
    """按采样帧 OCR 内嵌字幕；返回可直接放入 Material 的轨道。"""

    started = time.monotonic()
    if not config.enabled:
        return OcrResult(status="disabled", warnings=["内嵌字幕 OCR 未启用"])
    if not stream_url:
        return OcrResult(status="failed", warnings=["没有视频流，无法 OCR"])
    try:
        engine = engine or _make_engine(config.engine)
    except Exception as exc:
        return OcrResult(
            status="unavailable",
            warnings=[f"OCR 引擎不可用：{type(exc).__name__}；请安装 rapidocr_onnxruntime"],
            elapsed=round(time.monotonic() - started, 2),
        )

    fps = max(1, min(4, int(config.fps or 1)))
    width = max(320, int(config.frame_width or 960))
    height = max(120, int(config.frame_height or 320))
    duration_value = max(1.0, float(duration or 1.0))
    # 长视频不要按 1fps 处理全部帧，否则会超过 AstrBot 工具 300s 超时。
    # 在不改变总时长的前提下降低采样密度，最多处理 max_samples 帧。
    step = max(
        1.0 / fps,
        duration_value / max(20, int(config.max_samples or 120)),
    )
    frames = client.iter_subtitle_frames(
        stream_url,
        duration,
        fps=fps,
        region=config.region or "auto",
        max_seconds=max(30, int(config.max_seconds or 1200)),
        width=width,
        height=height,
        step=step,
    )
    groups: list[dict] = []
    previous_raw = b""
    frame_count = 0
    text_seconds = 0.0
    warnings: list[str] = []
    timed_out = False
    for stamp, raw in frames:
        if time.monotonic() - started >= max(20.0, float(config.time_budget or 60.0)):
            timed_out = True
            break
        frame_count += 1
        if _looks_same(previous_raw, raw):
            # 画面没有变化说明字幕也没有变化；延长最后一条字幕的持续时间，
            # 不能因为跳帧而把稳定字幕丢掉。
            if groups:
                groups[-1]["end"] = max(
                    float(groups[-1]["end"]),
                    float(stamp) + 1.0 / max(1, fps),
                )
            continue
        previous_raw = raw
        try:
            text, confidence = _frame_lines(
                engine, raw, width, height, float(config.min_confidence)
            )
        except Exception:
            continue
        if not text:
            continue
        text_seconds += 1.0 / max(1, fps)
        if (
            groups
            and float(stamp) - float(groups[-1]["end"]) <= max(2.0, 2.0 / fps)
            and _similar(groups[-1]["text"], text) >= 0.82
        ):
            group = groups[-1]
            group["end"] = float(stamp) + 1.0 / max(1, fps)
            group["hits"] = int(group.get("hits", 1)) + 1
            if confidence >= group["confidence"]:
                group["text"] = text
                group["confidence"] = confidence
        else:
            groups.append(
                {
                    "start": float(stamp),
                    "end": float(stamp) + 1.0 / max(1, fps),
                    "text": text,
                    "confidence": confidence,
                    "hits": 1,
                }
            )

    usable_groups = [
        group
        for group in groups
        if group["end"] - group["start"] >= 1.2
        and group["confidence"] >= float(config.min_confidence)
    ]
    if not usable_groups:
        return OcrResult(
            status="empty" if frame_count else "failed",
            warnings=warnings + ["没有识别到稳定的内嵌字幕"],
            elapsed=round(time.monotonic() - started, 2),
        )

    coverage = min(
        1.0,
        sum(max(0.0, group["end"] - group["start"]) for group in usable_groups)
        / max(1.0, float(duration or 1)),
    )
    primary_lines: list[tuple[float, str]] = []
    secondary_lines: list[tuple[float, str]] = []
    bilingual_pairs = 0
    for group in usable_groups:
        primary, secondary = _split_bilingual(group["text"])
        primary_lines.append((round(group["start"], 2), primary))
        if secondary:
            secondary_lines.append((round(group["start"], 2), secondary))
            bilingual_pairs += 1
    tracks = [
        bc.SubtitleTrack(
            lang="",
            lang_doc="内嵌字幕 OCR",
            lines=primary_lines,
            role="primary",
            origin="ocr",
            bilingual=bilingual_pairs > 0,
            confidence=sum(group["confidence"] for group in usable_groups)
            / len(usable_groups),
        )
    ]
    if len(secondary_lines) >= max(1, len(usable_groups) // 2):
        tracks.append(
            bc.SubtitleTrack(
                lang="",
                lang_doc="内嵌字幕 OCR（辅）",
                lines=secondary_lines,
                role="secondary",
                origin="ocr",
                confidence=tracks[0].confidence,
            )
        )
    enough = coverage >= float(config.min_coverage)
    status = "partial" if enough and timed_out else ("available" if enough else "low_coverage")
    if timed_out and enough:
        warnings.append(f"内嵌字幕 OCR 达到时间预算，已返回前段结果（覆盖 {coverage:.0%}）")
    if not enough:
        warnings.append(
            f"内嵌字幕 OCR 覆盖率仅 {coverage:.0%}，将回退 ASR/无字幕"
        )
    if frame_count == 0:
        warnings.append("OCR 没有取到视频帧")
    return OcrResult(
        tracks=tracks,
        status=status,
        coverage=coverage,
        warnings=warnings,
        elapsed=round(time.monotonic() - started, 2),
    )
