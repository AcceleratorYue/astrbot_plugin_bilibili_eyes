"""音频转写与 ASR 文本切句。

只依赖 AstrBot 已配置的 STT Provider，不直接绑定某一家 ASR 服务。
Provider 的 ``get_text`` 返回整段文本，这里负责清洗、断句和近似时间轴。
"""

from __future__ import annotations

import re
from pathlib import Path

# 静音/BGM 段常见的 ASR 幻觉；不作为真实台词。
ASR_HALLUCINATIONS = (
    "请不吝点赞",
    "订阅我的频道",
    "谢谢观看",
    "优酷独家播出",
    "爱奇艺独家",
    "字幕由",
    "未经著作权人",
    "请点赞投币",
    "欢迎在评论区留言",
    "敬请关注",
    "thank you for watching",
    "subtitles by",
    "please subscribe",
)

ASR_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")
ASR_REPEAT_CHAR_RE = re.compile(r"(.)\1{5,}")
ASR_REPEAT_WORD_RE = re.compile(r"(.{2,4})\1{4,}")


class AudioTranscriberError(Exception):
    """音频转写失败；reason 用于上层转成用户可读提示。"""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}")


def clean_asr_text(text: str, max_chars: int = 6000) -> str:
    """清理 ASR 原始文本，保留自然标点。"""

    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    for phrase in ASR_HALLUCINATIONS:
        cleaned = re.sub(re.escape(phrase), "", cleaned, flags=re.IGNORECASE)
    # 抑制“啊啊啊啊”“对对对对”这类复读，只留少量。
    cleaned = ASR_REPEAT_CHAR_RE.sub(r"\1\1", cleaned)
    cleaned = ASR_REPEAT_WORD_RE.sub(r"\1\1", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned[:max_chars].strip()


def text_to_subtitles(
    text: str,
    duration: float,
    max_segments: int = 240,
) -> list[tuple[float, str]]:
    """把整段 ASR 文本切成近似时间轴。

    内置 STT Provider 只返回整段文本，无法提供精确逐句时间戳。
    这里按字符数在“实际转录时长”内分摊，时间戳仅用于选帧和排序，
    不代表精确对齐。
    """

    cleaned = clean_asr_text(text)
    if not cleaned:
        return []

    raw_segments = [
        item.strip() for item in ASR_SENTENCE_RE.findall(cleaned) if item.strip()
    ]
    # 没有标点时按逗号/较长片段兜底，避免整段只生成一个巨型字幕。
    if len(raw_segments) <= 1:
        raw_segments = [
            item.strip() for item in re.split(r"[，,、]\s*", cleaned) if item.strip()
        ]
    segments = [item for item in raw_segments if len(item) >= 2]
    if not segments:
        segments = [cleaned]
    if len(segments) > max_segments:
        segments = segments[:max_segments]

    total_seconds = max(0.0, float(duration or 0.0))
    if total_seconds <= 0:
        return [(0.0, item) for item in segments]

    total_chars = sum(len(item) for item in segments)
    cursor = 0.0
    result: list[tuple[float, str]] = []
    for index, item in enumerate(segments):
        if index == len(segments) - 1:
            end = total_seconds
        else:
            share = len(item) / max(1, total_chars)
            end = min(total_seconds, cursor + max(0.5, share * total_seconds))
        start = min(cursor, total_seconds)
        if end <= start:
            end = min(total_seconds, start + 0.5)
        result.append((round(start, 2), item))
        cursor = end

    if result and result[-1][0] >= total_seconds:
        result[-1] = (max(0.0, total_seconds - 0.1), result[-1][1])
    return result


class AudioTranscriber:
    """AstrBot STT Provider 的轻量适配器。"""

    def __init__(self, provider=None, max_chars: int = 6000):
        self.provider = provider
        self.max_chars = max_chars

    async def transcribe(
        self,
        audio_path: Path,
        duration: float = 0.0,
    ) -> list[tuple[float, str]]:
        if self.provider is None:
            raise AudioTranscriberError("no_provider", "没有可用的 STT Provider")
        path = Path(audio_path)
        if not path.exists() or path.stat().st_size <= 0:
            raise AudioTranscriberError("empty_audio", "音频文件为空")
        try:
            text = await self.provider.get_text(str(path))
        except Exception as exc:
            raise AudioTranscriberError("provider_error", str(exc)) from exc
        cleaned = clean_asr_text(str(text or ""), self.max_chars)
        if not cleaned:
            raise AudioTranscriberError("empty_text", "STT 没有返回文本")
        return text_to_subtitles(cleaned, duration)
