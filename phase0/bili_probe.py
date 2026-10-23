"""Phase 0 验证：B 站视频信息 / 字幕 / 评论 / 高能进度条 / 取流截帧。

用法：
    python phase0/bili_probe.py                # 自动从热门挑一个短视频
    python phase0/bili_probe.py BV1xxxxxx      # 指定 BV
可选环境变量：BILI_SESSDATA（登录态，AI 字幕/完整评论可能需要）
"""

from __future__ import annotations

import json
import os
import subprocess
import gzip
import re
import sys
import time
import urllib.parse
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from wbi import UA, get_json, get_wbi_keys, sign_url  # noqa: E402

OUT_ROOT = HERE / "out"
HEADERS = {"User-Agent": UA, "Referer": "https://www.bilibili.com/"}
sessdata = os.environ.get("BILI_SESSDATA", "").strip()
if sessdata:
    HEADERS["Cookie"] = f"SESSDATA={sessdata}"


def pick_bvid() -> str:
    data = get_json(
        "https://api.bilibili.com/x/web-interface/popular?ps=20&pn=1", headers=HEADERS
    )
    for item in data.get("data", {}).get("list", []):
        duration = int(item.get("duration") or 0)
        if 60 <= duration <= 600 and item.get("bvid"):
            return item["bvid"]
    raise RuntimeError("热门列表里没找到合适的短视频")


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def pick_stream(play: dict) -> tuple[str, int]:
    data = play.get("data") or {}
    dash = data.get("dash") or {}
    videos = [
        item
        for item in dash.get("video") or []
        if item.get("baseUrl") or item.get("base_url")
    ]
    if videos:
        videos.sort(key=lambda item: int(item.get("height") or 0))
        chosen = next(
            (v for v in videos if int(v.get("height") or 0) >= 360), videos[-1]
        )
        return (
            chosen.get("baseUrl") or chosen.get("base_url"),
            int(chosen.get("height") or 0),
        )
    durl = [item for item in data.get("durl") or [] if item.get("url")]
    if durl:
        return durl[0]["url"], 0
    raise RuntimeError("playurl 未返回可用视频流")


def extract_frame(url: str, seconds: float, out: Path, height: int = 480) -> float:
    started = time.time()
    headers = (
        f"Referer: https://www.bilibili.com/\r\n"
        f"User-Agent: {UA}\r\n"
    )
    cmd = [
        ffmpeg_exe(),
        "-hide_banner",
        "-loglevel",
        "error",
        "-headers",
        headers,
        "-ss",
        f"{seconds:.1f}",
        "-i",
        url,
        "-frames:v",
        "1",
        "-vf",
        f"scale=-2:{height}",
        "-q:v",
        "3",
        "-y",
        str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=60)
    return time.time() - started


def make_contact_sheet(frames: list[Path], out: Path, cols: int = 4, rows: int = 3):
    from PIL import Image, ImageDraw

    if not frames:
        return None
    cell_w, cell_h = 320, 180
    sheet = Image.new("RGB", (cell_w * cols, cell_h * rows), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(frames[: cols * rows]):
        try:
            img = Image.open(path).convert("RGB")
        except Exception:
            continue
        img.thumbnail((cell_w, cell_h))
        x = (index % cols) * cell_w
        y = (index // cols) * cell_h
        sheet.paste(img, (x, y))
        draw.text((x + 6, y + 6), f"{index + 1:02d}", fill=(255, 255, 0))
    sheet.save(out, quality=85)
    return out


def main() -> int:
    bvid = sys.argv[1] if len(sys.argv) > 1 else pick_bvid()
    print("BV:", bvid)
    out_dir = OUT_ROOT / bvid
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"bvid": bvid, "frames": [], "timings": {}}

    t0 = time.time()
    view = get_json(
        f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", headers=HEADERS
    )
    report["timings"]["view"] = round(time.time() - t0, 2)
    if view.get("code") != 0:
        print("view failed:", view.get("code"), view.get("message"))
        return 1
    data = view["data"]
    pages = data.get("pages") or []
    cid = pages[0]["cid"] if pages else data.get("cid")
    aid = data.get("aid")
    duration = int(data.get("duration") or 0)
    report.update(
        {
            "title": data.get("title"),
            "owner": data.get("owner", {}).get("name"),
            "duration": duration,
            "cid": cid,
            "aid": aid,
            "pages": len(pages),
            "desc_len": len(data.get("desc") or ""),
        }
    )
    print(f"标题: {data.get('title')} | UP: {data.get('owner', {}).get('name')} | 时长: {duration}s | 分P: {len(pages)}")

    # 热点来源 1：弹幕密度（pbp 接口已 404，改用弹幕 XML 自己统计）
    try:
        import urllib.request

        t0 = time.time()
        req = urllib.request.Request(
            f"https://api.bilibili.com/x/v1/dm/list.so?oid={cid}", headers=HEADERS
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
            encoding = resp.headers.get("Content-Encoding", "")
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        elif encoding == "deflate" or raw[:1] != b"<":
            try:
                raw = zlib.decompress(raw)
            except Exception:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        text = raw.decode("utf-8", "replace")
        times = []
        for item in re.findall(r'<d p="([^"]+)"', text):
            try:
                times.append(float(item.split(",")[0]))
            except Exception:
                pass
        report["timings"]["danmaku_xml"] = round(time.time() - t0, 2)
        step = max(1, duration // 60)
        hist: dict[int, int] = {}
        for value in times:
            hist[int(value // step)] = hist.get(int(value // step), 0) + 1
        top = sorted(hist.items(), key=lambda kv: -kv[1])[:8]
        report["danmaku"] = {
            "count": len(times),
            "step_sec": step,
            "top_bins": [
                {"t": bin_index * step, "count": count}
                for bin_index, count in top
            ],
        }
        print(
            f"弹幕密度: {len(times)} 条 | step={step}s | 峰值时间点: "
            + ", ".join(f"{b * step}s({c})" for b, c in top)
        )
    except Exception as exc:
        report["danmaku"] = {"error": str(exc)}
        print("弹幕密度失败:", exc)

    # WBI
    try:
        t0 = time.time()
        img_key, sub_key = get_wbi_keys()
        report["timings"]["wbi_nav"] = round(time.time() - t0, 2)
        print("WBI keys:", img_key[:6] + "...", sub_key[:6] + "...")
    except Exception as exc:
        print("WBI key 获取失败:", exc)
        return 1

    # 字幕
    try:
        t0 = time.time()
        url = sign_url(
            "https://api.bilibili.com/x/player/wbi/v2",
            {"bvid": bvid, "cid": cid},
            img_key,
            sub_key,
        )
        player = get_json(url, headers=HEADERS)
        report["timings"]["player_v2"] = round(time.time() - t0, 2)
        report["view_points"] = len(
            (player.get("data") or {}).get("view_points") or []
        )
        subtitles = ((player.get("data") or {}).get("subtitle") or {}).get(
            "subtitles"
        ) or []
        report["subtitle"] = {
            "code": player.get("code"),
            "count": len(subtitles),
            "langs": [s.get("lan") for s in subtitles],
        }
        print(
            f"高能看点: {report['view_points']} 个 | 字幕: code={player.get('code')} "
            f"count={len(subtitles)} langs={[s.get('lan') for s in subtitles]}"
        )
        if subtitles:
            sub_url = subtitles[0].get("subtitle_url") or ""
            if sub_url.startswith("//"):
                sub_url = "https:" + sub_url
            if sub_url:
                t0 = time.time()
                payload = get_json(sub_url, headers=HEADERS)
                report["timings"]["subtitle_download"] = round(time.time() - t0, 2)
                body = payload.get("body") or []
                report["subtitle"]["lines"] = len(body)
                report["subtitle"]["sample"] = " ".join(
                    str(line.get("content") or "") for line in body[:3]
                )[:300]
                print(f"字幕行数: {len(body)} | 样例: {report['subtitle']['sample'][:120]}")
    except Exception as exc:
        report["subtitle"] = {"error": str(exc)}
        print("字幕失败:", exc)

    # 评论（旧接口，游客可用性更高）
    try:
        t0 = time.time()
        reply = get_json(
            f"https://api.bilibili.com/x/v2/reply?type=1&oid={aid}&pn=1&ps=20&sort=2",
            headers=HEADERS,
        )
        report["timings"]["comments"] = round(time.time() - t0, 2)
        replies = ((reply.get("data") or {}).get("replies") or [])
        report["comments"] = {"code": reply.get("code"), "count": len(replies)}
        print(f"评论: code={reply.get('code')} count={len(replies)}")
        if replies:
            report["comments"]["sample"] = str(replies[0].get("content", {}).get("message") or "")[:200]
    except Exception as exc:
        report["comments"] = {"error": str(exc)}
        print("评论失败:", exc)

    # 取流
    try:
        t0 = time.time()
        url = sign_url(
            "https://api.bilibili.com/x/player/wbi/playurl",
            {"bvid": bvid, "cid": cid, "qn": 32, "fnval": 16, "fourk": 1},
            img_key,
            sub_key,
        )
        play = get_json(url, headers=HEADERS)
        report["timings"]["playurl"] = round(time.time() - t0, 2)
        stream_url, height = pick_stream(play)
        report["stream"] = {"height": height, "code": play.get("code")}
        print(f"取流: code={play.get('code')} height={height}p")
    except Exception as exc:
        print("取流失败:", exc)
        report["stream"] = {"error": str(exc)}
        (out_dir / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 1

    # 均匀截 12 帧（Phase 0 先验证可行性；选点算法 Phase 1 再做）
    count = 12
    points = [
        duration * (0.05 + 0.9 * index / (count - 1)) for index in range(count)
    ]
    extracted = []
    for index, seconds in enumerate(points, start=1):
        out = frames_dir / f"frame_{index:02d}_{int(seconds)}s.jpg"
        try:
            elapsed = extract_frame(stream_url, seconds, out)
            size_kb = out.stat().st_size / 1024 if out.exists() else 0
            extracted.append(out)
            report["frames"].append(
                {"index": index, "t": round(seconds, 1), "file": out.name, "kb": round(size_kb, 1), "sec": round(elapsed, 2)}
            )
            print(f"  帧 {index:02d} t={seconds:5.1f}s  {elapsed:4.2f}s  {size_kb:6.1f}KB")
        except Exception as exc:
            report["frames"].append({"index": index, "t": round(seconds, 1), "error": str(exc)})
            print(f"  帧 {index:02d} 失败: {exc}")

    sheet = make_contact_sheet(extracted, out_dir / "contact_sheet.jpg")
    report["contact_sheet"] = str(sheet) if sheet else None
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n输出目录: {out_dir}")
    print("报告:", out_dir / "report.json")
    if sheet:
        print("联系图:", sheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
