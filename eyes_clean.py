"""B 站素材清洗：简介、字幕、评论、弹幕与帧去重。

目标是减少“垃圾上下文”和重复画面，让子代理看到的是高信息密度的材料。
"""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterable

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.I)
QQ_RE = re.compile(r"(?:QQ|qq)\s*[:：]?\s*\d{5,12}|群号?\s*[:：]?\s*\d{5,12}")
HASHTAG_ONLY_RE = re.compile(r"^(?:#\S+#[\s,，、]*)+$")
SENTENCE_END = "。！？!?；;…"
DESC_JUNK = (
    "淘宝",
    "天猫",
    "拼多多",
    "粉丝群",
    "交流群",
    "QQ群",
    "qq群",
    "群号",
    "商务合作",
    "商务",
    "邮箱",
    "BGM",
    "bgm",
    "配乐",
    "侵权",
    "免责声明",
    "转载",
    "公众号",
    "一键三连",
    "点赞投币",
    "关注我",
)
COMMENT_JUNK = (
    "抽奖",
    "接龙",
    "互赞",
    "互粉",
    "打卡",
    "签到",
    "复制",
    "领红包",
    "助力",
)
DANMAKU_JUNK = {
    "666",
    "6666",
    "66666",
    "888",
    "8888",
    "999",
    "hhh",
    "hhhh",
    "哈哈",
    "哈哈哈",
    "哈哈哈哈",
    "打卡",
    "签到",
    "来了",
    "前排",
}
TIMESTAMP_RE = re.compile(r"(?<!\d)(\d{1,2}):([0-5]\d)(?!\d)")
STOPWORDS = {
    "这个",
    "那个",
    "什么",
    "就是",
    "然后",
    "真的",
    "可以",
    "没有",
    "一个",
    "我们",
    "你们",
    "他们",
    "感觉",
    "视频",
    "up",
    "UP",
    "主播",
    "这里",
    "那里",
}


def _meaningful(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text.strip(" -—_·•\t")


def clean_description(text: str, max_lines: int = 5, max_chars: int = 600) -> str:
    """去掉简介里的链接/联系方式/BGM/免责声明，只保留核心描述。"""

    kept: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = _meaningful(URL_RE.sub("", raw_line))
        line = _meaningful(EMAIL_RE.sub("", line))
        if not line:
            continue
        if HASHTAG_ONLY_RE.fullmatch(line):
            continue
        if QQ_RE.search(line):
            continue
        if any(keyword in line for keyword in DESC_JUNK):
            continue
        if len(line) <= 1:
            continue
        kept.append(line)
        if len(kept) >= max_lines:
            break
    if not kept:
        return ""
    return _meaningful("\n".join(kept))[:max_chars]


def _clean_subtitle_text(text: str) -> str:
    value = _meaningful(text)
    value = re.sub(r"([就是然后那个这个嗯啊呃])\1{1,}", r"\1", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip("，。；;、, ")


def merge_subtitles(
    lines: Iterable[tuple[float, str]],
    max_gap: float = 0.8,
    max_chars: int = 160,
) -> list[tuple[float, str]]:
    """把 ASR/字幕的 1~2 秒碎片按标点和静音间隔合并。"""

    ordered: list[tuple[float, str]] = []
    for timestamp, text in lines or []:
        value = _clean_subtitle_text(text)
        if value:
            ordered.append((float(timestamp), value))
    ordered.sort(key=lambda item: item[0])
    merged: list[tuple[float, str]] = []
    for timestamp, text in ordered:
        if merged:
            previous_time, previous_text = merged[-1]
            gap = timestamp - previous_time
            if (
                gap <= max_gap
                and previous_text[-1] not in SENTENCE_END
                and len(previous_text) + len(text) <= max_chars
            ):
                merged[-1] = (previous_time, f"{previous_text} {text}".strip())
                continue
        merged.append((timestamp, text))
    return merged


def subtitle_highlights(
    lines: Iterable[tuple[float, str]], limit: int = 5
) -> list[tuple[float, str]]:
    """按字数、问号和转折词挑高信息字幕段。"""

    ranked: list[tuple[int, float, str]] = []
    for timestamp, text in lines or []:
        value = _clean_subtitle_text(text)
        if len(value) < 6:
            continue
        score = len(value)
        if any(word in value for word in ("？", "?", "但是", "其实", "不过", "关键", "因为", "所以")):
            score += 20
        ranked.append((score, float(timestamp), value))
    ranked.sort(key=lambda item: (-item[0], item[2]))
    return [(timestamp, text) for _score, timestamp, text in ranked[: max(1, limit)]]


def is_low_value_comment(text: str) -> bool:
    value = _meaningful(text)
    if len(value) < 2:
        return True
    if any(keyword in value for keyword in COMMENT_JUNK):
        return True
    plain = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if len(plain) < 2:
        return True
    if len(set(plain)) <= 2 and len(plain) <= 8:
        return True
    return False


def extract_time_marks(text: str, limit: int = 3) -> list[str]:
    marks = [f"{int(hour):02d}:{minute}" for hour, minute in TIMESTAMP_RE.findall(text or "")]
    return list(dict.fromkeys(marks))[:limit]


def is_low_value_danmaku(text: str) -> bool:
    value = _meaningful(html.unescape(text))
    if not value or value.lower() in DANMAKU_JUNK:
        return True
    plain = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    if len(plain) <= 1:
        return True
    if plain.isdigit() and len(plain) <= 4:
        return True
    if len(set(plain)) <= 1 and len(plain) <= 6:
        return True
    return False


def danmaku_keywords(texts: Iterable[str], limit: int = 6) -> list[str]:
    counts: dict[str, int] = {}
    for raw in texts or []:
        value = _meaningful(html.unescape(str(raw)))
        if is_low_value_danmaku(value):
            continue
        plain = re.sub(r"[^\w\u4e00-\u9fff]+", " ", value).strip()
        if not plain:
            continue
        for token in plain.split():
            if len(token) < 2 or len(token) > 12 or token in STOPWORDS:
                continue
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _count in ranked[: max(1, limit)]]


def dhash(path: str | Path, hash_size: int = 8) -> int:
    """64 位 dHash；失败返回 -1。"""

    try:
        from PIL import Image

        image = Image.open(path).convert("L").resize((hash_size + 1, hash_size))
        pixels = list(image.getdata())
        bits = 0
        index = 0
        for row in range(hash_size):
            for column in range(hash_size):
                left = pixels[row * (hash_size + 1) + column]
                right = pixels[row * (hash_size + 1) + column + 1]
                bits |= (1 if left > right else 0) << index
                index += 1
        return bits
    except Exception:
        return -1


def hamming_distance(first: int, second: int) -> int:
    return bin(first ^ second).count("1")


def dedupe_frames(
    pairs: Iterable[tuple[Path, float]], max_count: int = 12, threshold: int = 6
) -> list[tuple[Path, float]]:
    """按 dHash 去掉近似重复帧；保留时间顺序。"""

    kept: list[tuple[Path, float]] = []
    hashes: list[int] = []
    for path, timestamp in sorted(pairs or [], key=lambda item: item[1]):
        digest = dhash(path)
        if digest >= 0 and any(
            hamming_distance(digest, existing) <= threshold for existing in hashes
        ):
            continue
        kept.append((path, timestamp))
        if digest >= 0:
            hashes.append(digest)
        if len(kept) >= max_count:
            break
    return kept
