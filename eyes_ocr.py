"""内嵌画面字幕 OCR。

只依赖 ffmpeg 与可选的 RapidOCR；OCR 失败时由主流程回退 ASR。
"""

from __future__ import annotations

import bisect
import difflib
import io
import platform
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    time_budget: float = 150.0
    # 字幕区域变化检测 + 边界二分
    change_detection: bool = True
    scan_fps: int = 4
    scan_width: int = 320
    scan_height: int = 120
    change_threshold: float = 12.0
    cluster_gap: float = 1.0
    safety_interval: float = 12.0
    boundary_search: bool = True
    # 并行/GPU 尝试
    workers: int = 2
    use_gpu: str = "auto"


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
    def __init__(self, backend: str = "cpu") -> None:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore

        kwargs: dict[str, Any] = {}
        if backend == "cuda":
            kwargs = {
                "Det.use_cuda": True,
                "Cls.use_cuda": True,
                "Rec.use_cuda": True,
            }
        elif backend == "dml":
            kwargs = {
                "Det.use_dml": True,
                "Cls.use_dml": True,
                "Rec.use_dml": True,
            }
        try:
            self.engine = RapidOCR(**kwargs) if kwargs else RapidOCR()
        except Exception:
            # GPU/DML 初始化失败时退回 CPU，不能因为加速不可用导致 OCR 失败。
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


def _available_providers() -> list[str]:
    try:
        import onnxruntime as ort  # type: ignore

        return [str(item) for item in ort.get_available_providers()]
    except Exception:
        return []


def _resolve_ocr_backend(value: Any) -> str:
    """把 auto/gpu/dml/cpu 解析成 cuda/dml/cpu。

    DirectML 是 Windows 上的跨厂商方案，AMD/Intel 核显和独显都能走；
    CUDA 仅 NVIDIA。auto 顺序：CUDA > DirectML > CPU。
    """

    raw = str(value or "auto").strip().lower()
    providers = _available_providers()
    if raw in ("cpu", "0", "false", "no", "off"):
        return "cpu"
    if raw in ("cuda", "gpu", "1", "true", "yes", "on"):
        return "cuda" if "CUDAExecutionProvider" in providers else "cpu"
    if raw in ("dml", "directml", "amd", "intel"):
        return (
            "dml"
            if "DmlExecutionProvider" in providers and platform.system() == "Windows"
            else "cpu"
        )
    if "CUDAExecutionProvider" in providers:
        return "cuda"
    if (
        "DmlExecutionProvider" in providers
        and platform.system() == "Windows"
    ):
        return "dml"
    return "cpu"


def _make_engine(name: str, use_gpu: Any = "auto"):
    value = str(name or "auto").strip().lower()
    if value in ("auto", "rapidocr", "rapidocr_onnxruntime"):
        return RapidOcrEngine(backend=_resolve_ocr_backend(use_gpu))
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


def _extract_sampled(
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
        if time.monotonic() - started >= max(20.0, float(config.time_budget or 150.0)):
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

# ---------------------------------------------------------------------------
# 字幕区域变化检测 + 边界二分 + 并行 OCR
# ---------------------------------------------------------------------------

def _signature(raw: bytes, buckets: int = 384) -> bytes:
    if not raw:
        return b""
    step = max(1, len(raw) // max(1, buckets))
    return raw[::step]


def _signature_diff(left: bytes, right: bytes) -> float:
    if not left or not right:
        return 999.0
    size = min(len(left), len(right))
    if size <= 0:
        return 999.0
    return sum(abs(a - b) for a, b in zip(left[:size], right[:size])) / size


def _refine_boundary(
    signatures: list[tuple[float, bytes]], lo: int, hi: int
) -> float:
    """在 [lo, hi] 两帧之间二分找画面变化边界（时间精度约 1/scan_fps）。"""

    if hi <= lo:
        return signatures[max(0, lo)][0]
    if hi - lo == 1:
        return (signatures[lo][0] + signatures[hi][0]) / 2.0
    left = signatures[lo][1]
    right = signatures[hi][1]
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _signature_diff(left, signatures[mid][1]) <= _signature_diff(
            signatures[mid][1], right
        ):
            lo = mid
        else:
            hi = mid
    return (signatures[lo][0] + signatures[hi][0]) / 2.0


def _detect_targets(
    client: Any,
    stream_url: str,
    duration: float,
    config: OcrConfig,
    started: float,
) -> tuple[list[float], list[float], list[tuple[float, bytes]], bool]:
    """扫描全片找字幕区域变化点，返回候选 OCR 时间点、边界和签名时间轴。"""

    scan_fps = max(2, min(8, int(config.scan_fps or 4)))
    step = 1.0 / scan_fps
    scan_width = max(160, int(config.scan_width or 320))
    scan_height = max(60, int(config.scan_height or 120))
    signatures: list[tuple[float, bytes]] = []
    changes: list[tuple[float, int]] = []
    previous = b""
    for stamp, raw in client.iter_subtitle_frames(
        stream_url,
        duration,
        fps=scan_fps,
        region=config.region or "auto",
        max_seconds=max(30, int(config.max_seconds or 1200)),
        width=scan_width,
        height=scan_height,
        step=step,
    ):
        if time.monotonic() - started >= max(20.0, float(config.time_budget or 150.0)):
            break
        signature = _signature(raw)
        index = len(signatures)
        signatures.append((float(stamp), signature))
        if previous and _signature_diff(previous, signature) >= float(
            config.change_threshold or 12.0
        ):
            changes.append((float(stamp), index))
        previous = signature
    if not signatures:
        return [], [], [], False

    clusters: list[list[tuple[float, int]]] = []
    for stamp, index in changes:
        if (
            clusters
            and stamp - clusters[-1][-1][0] <= max(0.25, float(config.cluster_gap or 1.0))
        ):
            clusters[-1].append((stamp, index))
        else:
            clusters.append([(stamp, index)])

    boundaries: list[float] = []
    for cluster in clusters:
        first = max(0, cluster[0][1] - 1)
        last = min(len(signatures) - 1, cluster[-1][1] + 1)
        boundary = (
            _refine_boundary(signatures, first, last)
            if config.boundary_search
            else (signatures[first][0] + signatures[last][0]) / 2.0
        )
        if not boundaries or boundary - boundaries[-1] >= 0.5:
            boundaries.append(boundary)

    end_time = max(
        float(duration or 0.0),
        signatures[-1][0] + step if signatures else 0.0,
    )
    targets: list[float] = []
    spans = [0.0] + boundaries + [end_time]
    for left, right in zip(spans, spans[1:]):
        if right - left < 0.4:
            continue
        targets.append(min(right - 0.15, max(left + 0.15, left + 0.65)))
        if right - left >= 5.0:
            targets.append((left + right) / 2.0)
    interval = max(2.0, float(config.safety_interval or 12.0))
    safety = interval
    while safety < end_time:
        targets.append(safety)
        safety += interval

    targets = sorted(
        {
            round(min(end_time - 0.1, max(0.1, float(item))), 2)
            for item in targets
            if 0.1 < float(item) < end_time
        }
    )
    deduped: list[float] = []
    for item in targets:
        if not deduped or item - deduped[-1] >= 0.6:
            deduped.append(item)
    limited = deduped[: max(20, int(config.max_samples or 120))]
    return limited, boundaries, signatures, True


def _ocr_change_points(
    client: Any,
    stream_url: str,
    duration: float,
    config: OcrConfig,
    engine: Any | None,
) -> OcrResult:
    started = time.monotonic()
    targets, boundaries, _signatures, scanned = _detect_targets(
        client, stream_url, duration, config, started
    )
    if not scanned:
        return OcrResult(
            status="failed",
            warnings=["字幕区域扫描失败，没有取到视频帧"],
            elapsed=round(time.monotonic() - started, 2),
        )
    if not targets:
        return OcrResult(
            status="empty",
            warnings=["没有检测到字幕区域变化，也没有安全采样点"],
            elapsed=round(time.monotonic() - started, 2),
        )

    width = max(320, int(config.frame_width or 960))
    height = max(120, int(config.frame_height or 320))
    workers = 1 if engine is not None else max(1, min(4, int(config.workers or 2)))
    deadline = started + max(20.0, float(config.time_budget or 150.0))
    local = threading.local()

    def run_one(stamp: float) -> tuple[float, str, float]:
        raw = client.grab_subtitle_frame(
            stream_url,
            stamp,
            region=config.region or "auto",
            width=width,
            height=height,
        )
        if not raw:
            return stamp, "", 0.0
        current_engine = engine
        if current_engine is None:
            current_engine = getattr(local, "engine", None)
            if current_engine is None:
                current_engine = _make_engine(config.engine, config.use_gpu)
                local.engine = current_engine
        text, confidence = _frame_lines(
            current_engine, raw, width, height, float(config.min_confidence)
        )
        return stamp, text, confidence

    results: list[tuple[float, str, float]] = []
    timed_out = False
    if workers <= 1:
        for stamp in targets:
            if time.monotonic() >= deadline:
                timed_out = True
                break
            results.append(run_one(stamp))
    else:
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bili-ocr")
        futures = {executor.submit(run_one, stamp): stamp for stamp in targets}
        try:
            for future in as_completed(
                futures, timeout=max(1.0, deadline - time.monotonic())
            ):
                try:
                    results.append(future.result())
                except Exception:
                    continue
        except TimeoutError:
            timed_out = True
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    end_time = max(float(duration or 0.0), 0.1)
    intervals: dict[int, tuple[str, float]] = {}
    for stamp, text, confidence in results:
        if not text:
            continue
        index = bisect.bisect_right(boundaries, stamp)
        current = intervals.get(index)
        if current is None or confidence >= current[1]:
            intervals[index] = (text, confidence)

    spans = [0.0] + boundaries + [end_time]
    groups: list[dict] = []
    for index, (text, confidence) in sorted(intervals.items()):
        start = spans[index] if index < len(spans) else 0.0
        end = spans[index + 1] if index + 1 < len(spans) else end_time
        if end - start < 0.35:
            continue
        if (
            groups
            and _similar(groups[-1]["text"], text) >= 0.82
            and start - groups[-1]["end"] <= 1.0
        ):
            groups[-1]["end"] = end
            if confidence >= groups[-1]["confidence"]:
                groups[-1]["text"] = text
                groups[-1]["confidence"] = confidence
        else:
            groups.append(
                {
                    "start": max(0.0, start),
                    "end": min(end_time, end),
                    "text": text,
                    "confidence": confidence,
                    "hits": 1,
                }
            )

    usable_groups = [
        group
        for group in groups
        if group["end"] - group["start"] >= 0.35
        and group["confidence"] >= float(config.min_confidence)
    ]
    if not usable_groups:
        return OcrResult(
            status="empty",
            warnings=["字幕变化点 OCR 没有识别到稳定文本"],
            elapsed=round(time.monotonic() - started, 2),
        )

    coverage = min(
        1.0,
        sum(max(0.0, group["end"] - group["start"]) for group in usable_groups)
        / max(1.0, float(duration or 1.0)),
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
    confidence = sum(group["confidence"] for group in usable_groups) / len(
        usable_groups
    )
    tracks = [
        bc.SubtitleTrack(
            lang="",
            lang_doc="内嵌字幕 OCR",
            lines=primary_lines,
            role="primary",
            origin="ocr",
            bilingual=bilingual_pairs > 0,
            confidence=confidence,
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
                confidence=confidence,
            )
        )
    enough = coverage >= float(config.min_coverage)
    status = "partial" if enough and timed_out else (
        "available" if enough else "low_coverage"
    )
    warnings: list[str] = []
    if timed_out and enough:
        warnings.append(
            f"字幕变化检测达到时间预算，已返回部分结果（覆盖 {coverage:.0%}）"
        )
    if not enough:
        warnings.append(
            f"内嵌字幕 OCR 覆盖率仅 {coverage:.0%}，将回退 ASR/无字幕"
        )
    return OcrResult(
        tracks=tracks,
        status=status,
        coverage=coverage,
        warnings=warnings,
        elapsed=round(time.monotonic() - started, 2),
    )


def extract_embedded_subtitles(
    client: Any,
    stream_url: str,
    duration: float,
    config: OcrConfig,
    engine: Any | None = None,
) -> OcrResult:
    """优先使用字幕区域变化检测；不支持精确抓帧时回退旧采样路径。"""

    if not config.enabled:
        return OcrResult(status="disabled", warnings=["内嵌字幕 OCR 未启用"])
    if config.change_detection and hasattr(client, "grab_subtitle_frame"):
        try:
            return _ocr_change_points(client, stream_url, duration, config, engine)
        except Exception:
            # 新路径异常时保留旧路径兜底，不能因为实验性优化让整个观看失败。
            pass
    return _extract_sampled(client, stream_url, duration, config, engine=engine)
