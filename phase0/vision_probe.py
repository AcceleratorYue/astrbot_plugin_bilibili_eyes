"""Phase 0 验证：deepseek-flash 原生视觉 + 12 帧的耗时 / token / 输出质量。

用法：
    python phase0/vision_probe.py <frames_dir>
    python phase0/vision_probe.py            # 自动找最新的 out/<bvid>/frames
"""

from __future__ import annotations

import base64
import glob
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def load_provider() -> tuple[str, str, str]:
    paths = glob.glob(r"D:\QQbot\astrbot\data\config\abconf_*.json")
    if not paths:
        raise RuntimeError("找不到 abconf 配置")
    cfg = json.load(open(paths[0], encoding="utf-8-sig"))
    sources = {item.get("id"): item for item in cfg.get("provider_sources", [])}
    providers = {item.get("id"): item for item in cfg.get("provider", [])}
    source = sources.get("deepseek_source") or next(iter(sources.values()))
    provider = providers.get("deepseek") or next(iter(providers.values()))
    key = source.get("key")
    if isinstance(key, (list, tuple)):
        key = key[0] if key else None
    if not key:
        raise RuntimeError("provider source 里没有 key")
    return key, source.get("api_base", "https://api.deepseek.com/v1"), provider.get("model", "deepseek-flash")


def find_frames_dir() -> Path:
    candidates = sorted(
        (Path(p) for p in glob.glob(str(ROOT / "phase0" / "out" / "*" / "frames"))),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        raise RuntimeError("还没有截帧结果，先运行 bili_probe.py")
    return candidates[-1]


def image_part(path: Path) -> dict:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{data}", "detail": "auto"},
    }


SYSTEM_PROMPT = (
    "你是一个视频画面观察器。只陈述你在画面中能确认看到的内容，"
    "不评价好坏、不推测动机、不脑补画面里没有的东西。"
    "输出中文，条目化，尽量具体（人物/物体/文字/界面/动作/场景）。"
    "看不清就写‘看不清’。"
)

USER_PROMPT = (
    "这是一段 B 站视频按时间顺序截取的画面（按编号 01..N，等间隔选取）。"
    "请输出：\n"
    "1) 视频类型/场景的客观判断；\n"
    "2) 每个画面编号的可见内容（一句到两句）；\n"
    "3) 画面中出现的可读文字（逐条摘录）；\n"
    "4) 整体不确定项。"
)


def call(key: str, api_base: str, model: str, frames: list[Path], label: str) -> dict:
    content: list[dict] = [{"type": "text", "text": USER_PROMPT}]
    for index, path in enumerate(frames, start=1):
        content.append({"type": "text", "text": f"画面 {index:02d}："})
        content.append(image_part(path))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        "temperature": 0.2,
        "max_tokens": 6000,
        "reasoning_effort": "low",
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        return {"label": label, "error": f"HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return {"label": label, "error": str(exc)}

    elapsed = time.time() - started
    usage = data.get("usage") or {}
    message = ((data.get("choices") or [{}])[0].get("message") or {})
    text = message.get("content") or ""
    result = {
        "label": label,
        "images": len(frames),
        "latency_sec": round(elapsed, 2),
        "usage": usage,
        "finish_reason": ((data.get("choices") or [{}])[0]).get("finish_reason"),
        "text": text,
    }
    safe = dict(result)
    safe["text"] = text[:1200]
    print(f"\n=== {label} ===")
    print(f"images={result['images']} latency={result['latency_sec']}s usage={usage}")
    print("预览:", text[:500].replace("\n", " "))
    return result


def main() -> int:
    key, api_base, model = load_provider()
    frames_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else find_frames_dir()
    frames = sorted(frames_dir.glob("*.jpg"))[:12]
    if not frames:
        print("没有帧文件")
        return 1

    results = []
    results.append(call(key, api_base, model, frames, f"12 帧原图 ({len(frames)})"))

    sheet = frames_dir.parent / "contact_sheet.jpg"
    if sheet.exists():
        results.append(call(key, api_base, model, [sheet], "联系图 4x3"))

    out_dir = frames_dir.parent
    (out_dir / "vision_report.json").write_text(
        json.dumps({"model": model, "frames": str(frames_dir), "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n报告:", out_dir / "vision_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
