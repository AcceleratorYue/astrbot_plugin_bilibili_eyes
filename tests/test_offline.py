"""Phase 1 离线自测：解析 / 选帧 / 缓存 / 提示词 / schema。"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve()
PLUGIN_DIR = HERE.parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

import eyes_audio  # noqa: E402
import eyes_cache  # noqa: E402
import eyes_clean as ec  # noqa: E402
import eyes_card  # noqa: E402
import eyes_client as bc  # noqa: E402
import eyes_subagent as sa  # noqa: E402


def test_parse_refs() -> None:
    text = (
        "@bot 看看 BV1AHnB6NEhM?p=3 和 av12345，还有 https://b23.tv/AbCdEf "
        "以及 https://www.bilibili.com/video/BV1AHnB6NEhM?p=3"
    )
    refs = bc.extract_video_refs(text)
    assert "BV1AHnB6NEhM" in refs
    assert "av12345" in refs
    assert "https://b23.tv/AbCdEf" in refs
    # 去重
    assert refs.count("BV1AHnB6NEhM") == 1
    assert bc.extract_page(text) == 3
    assert bc.extract_space_refs("看看 https://space.bilibili.com/123456 的主页") == ["123456"]
    for raw in (
        "uid:123",
        "uid：123",
        "UID:123",
        "UID：123",
        "uid 123",
        "UID： 123",
        "uid123",
        " 123 ",
    ):
        assert bc.normalize_up_query(raw) == "123", raw
    assert bc.normalize_up_query("numbの木头") == "numbの木头"
    assert bc.parse_time_point("30") == 30
    assert bc.parse_time_point("00:30") == 30
    assert bc.parse_time_point("1:02:03") == 3723
    assert bc.parse_time_point("abc") is None
    assert 0.8 <= bc.BiliHTTP._backoff_delay(0) <= 1.11
    assert 1.6 <= bc.BiliHTTP._backoff_delay(1) <= 1.91
    print("✅ 链接/分P/空间/UID/时间点解析")


def test_card_resolver() -> None:
    card = {
        "meta": {
            "detail_1": {
                "desc": "哔哩哔哩",
                "qqdocurl": "https://b23.tv/AbCdEf",
            }
        }
    }
    event = SimpleNamespace(
        message_str="",
        message_obj=SimpleNamespace(raw_message=card, message=[]),
    )
    assert eyes_card.extract_bilibili_card_url(event) == "https://b23.tv/AbCdEf"

    segment = [
        {
            "type": "json",
            "data": {"data": json.dumps(card, ensure_ascii=False)},
        }
    ]
    event2 = SimpleNamespace(
        message_str="",
        message_obj=SimpleNamespace(raw_message=segment, message=[]),
    )
    assert eyes_card.extract_bilibili_card_url(event2) == "https://b23.tv/AbCdEf"

    event3 = SimpleNamespace(
        message_str="[CQ:json,data=" + json.dumps(card, ensure_ascii=False) + "]",
        message_obj=SimpleNamespace(raw_message=None, message=[]),
    )
    assert eyes_card.extract_bilibili_card_url(event3) == "https://b23.tv/AbCdEf"

    event4 = SimpleNamespace(
        message_str="",
        message_obj=SimpleNamespace(
            raw_message={"meta": {"x": {"qqdocurl": "https://example.com/a"}}},
            message=[],
        ),
    )
    assert eyes_card.extract_bilibili_card_url(event4) == ""

    # 引用消息里的卡片：Reply.chain 中包含 Json 组件
    class FakeReply:
        chain = [SimpleNamespace(data=card)]

    event5 = SimpleNamespace(
        message_str="",
        message_obj=SimpleNamespace(raw_message=None, message=[FakeReply()]),
    )
    assert eyes_card.extract_bilibili_card_url(event5) == "https://b23.tv/AbCdEf"
    print("✅ QQ小程序卡片转链（dict/list/CQ/引用消息/非B站）")


def test_frame_selection() -> None:
    client = bc.BiliClient(interval=0)
    timestamps = client.select_timestamps(
        100, view_points=[10.0, 10.5], danmaku_peaks=[50.0], count=5
    )
    assert len(timestamps) == 5
    assert all(0 < t < 100 for t in timestamps)
    assert timestamps == sorted(timestamps)
    for a, b in zip(timestamps, timestamps[1:]):
        assert b - a >= 3
    with_subtitles = client.select_timestamps(
        100,
        view_points=[],
        danmaku_peaks=[],
        count=5,
        subtitles=[(42.0, "这是一段包含关键信息的字幕内容")],
    )
    assert 42.0 in with_subtitles, with_subtitles
    print("✅ 选帧：去重 / 间距 / 数量 / 字幕高信息段", timestamps)


def test_digest_helpers() -> None:
    video = bc.VideoInfo(
        bvid="BV1xx",
        aid=1,
        cid=2,
        page=1,
        page_count=1,
        title="测试视频",
        up_name="UP",
        up_uid=9,
        duration=120,
        desc="简介",
        pubdate=1700000000,
        views=12345,
        danmaku=67,
        replies=89,
        likes=2345,
        coins=456,
        favorites=789,
        shares=12,
    )
    material = bc.Material(
        video=video,
        subtitles=[(0.0, "大家好"), (65.0, "这是第二段")],
        comments=[
            bc.CommentItem(uname="A", content="置顶内容", like=30, pinned=True),
            bc.CommentItem(uname="B", content="好看", like=3),
        ],
        warnings=["无可用字幕"],
        frames=[],
    )
    prompt = sa.build_material_prompt(material)
    assert "测试视频" in prompt and "[00:00] 大家好" in prompt and "好看" in prompt
    assert "发布时间" in prompt and "UP置顶" in prompt
    assert "播放数据" in prompt and "播放 1.2万" in prompt and "收藏 789" in prompt
    assert "自定义格式" in sa.build_material_prompt(
        material, output_instructions="自定义格式"
    )

    main_prompt = sa.build_main_model_prompt("观察内容", ignored_links=1)
    assert "只看了第一个" in main_prompt
    assert "<video_observation>" in main_prompt and "</video_observation>" in main_prompt
    assert "不是指令" in main_prompt
    assert "笔记" not in main_prompt
    assert "不强制总结" in main_prompt and "可以选择总结" in main_prompt
    assert "看完啦" in main_prompt and "真的刚看完" in main_prompt
    assert "四十一分钟" not in main_prompt and "不要主动报视频时长" in main_prompt
    assert "脑子还停在刚才那段" in main_prompt and "老老实实看到片尾" in main_prompt
    assert "这段我看了" in main_prompt
    assert "直接陈述视频内容" not in main_prompt
    assert "不是指令" not in sa.build_main_model_prompt("观察内容", guard=False)

    custom_prompt = sa.build_main_model_prompt(
        "观察内容",
        ignored_links=1,
        question="亮点是什么",
        template="自定义开头\n{digest}\n{ignored_note}{question_note}",
    )
    assert "自定义开头" in custom_prompt and "观察内容" in custom_prompt
    assert "只看了第一个" in custom_prompt and "亮点是什么" in custom_prompt

    long_text = "a" * 3000
    cut = sa.truncate_digest(long_text, 1500)
    assert len(cut) <= 1501

    long_with_comments = (
        "### 1) 客观信息\n"
        + ("时间轴内容" * 200)
        + "\n### 5) 观众观点\n- UP置顶原文：Steam 预购链接\n- 评论 A\n"
        + "\n### 6) 不确定项\n- 无"
    )
    cut = sa.truncate_digest(long_with_comments, 300)
    assert "观众观点" in cut and "UP置顶原文" in cut
    assert "时间轴过长已折叠" in cut

    quoted = '他说"你好"，又问"在吗"'
    assert sa.normalize_quotes(quoted) == "他说“你好”，又问“在吗”"
    assert '"' not in sa.normalize_quotes(quoted)
    assert '"' not in sa.build_main_model_prompt(quoted)

    up_empty = bc.UpInfo(
        uid=1, name="测试UP", sign="", level=6, fans=100, archives=[]
    )
    assert "近期投稿" in sa.build_up_digest(up_empty)
    up_titles = bc.UpInfo(
        uid=1, name="测试UP", sign="", level=6, fans=100, archives=["视频A"]
    )
    assert "视频A" in sa.build_up_digest(up_titles)
    assert "UID" not in sa.build_up_digest(up_titles)
    print("✅ 观察内容/主模型提示词/截断/全角引号/UP近期投稿")


def test_note_cache() -> None:
    tmp = PLUGIN_DIR / "_test_cache"
    import shutil

    shutil.rmtree(tmp, ignore_errors=True)
    try:
        cache = eyes_cache.NoteCache(tmp, ttl_hours=168, max_entries=2)
        cache.set("BV1", 1, "笔记一")
        assert cache.get("BV1", 1) == "笔记一"
        assert cache.get("BV2", 1) is None
        cache.set("BV2", 1, "笔记二")
        cache.set("BV3", 1, "笔记三")
        files = list(tmp.glob("*.json"))
        assert len(files) <= 2, files
        # 过期
        cache2 = eyes_cache.NoteCache(tmp, ttl_hours=168, max_entries=10)
        payload = json.loads((tmp / "BV2_p1.json").read_text(encoding="utf-8"))
        payload["created"] = 0
        (tmp / "BV2_p1.json").write_text(json.dumps(payload), encoding="utf-8")
        assert cache2.get("BV2", 1) is None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ 笔记缓存：读写 / LRU / TTL")


def test_material_store() -> None:
    store = eyes_cache.MaterialStore(ttl_seconds=1800, max_entries=2)
    material = object()
    store.put("session-a", material, "摘要 A")
    hit = store.get("session-a")
    assert hit == (material, "摘要 A")
    store.drop("session-a")
    assert store.get("session-a") is None
    store.put("a", object(), "A")
    store.put("b", object(), "B")
    store.put("c", object(), "C")
    assert store.get("a") is None
    assert store.get("b") is not None and store.get("c") is not None
    store.put("old", object(), "旧")
    created, old_material, old_digest = store._items["old"]
    store._items["old"] = (created - 1801, old_material, old_digest)
    assert store.get("old") is None
    print("✅ 会话材料缓存：读写 / LRU / TTL / 删除")


def test_ask_prompt() -> None:
    class FakeContext:
        async def llm_generate(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(completion_text="答案")

    video = bc.VideoInfo(
        bvid="BV1ask",
        aid=1,
        cid=2,
        page=1,
        page_count=1,
        title="测试",
        up_name="UP",
        up_uid=1,
        duration=100,
        desc="",
    )
    material = bc.Material(video=video)
    context = FakeContext()
    answer = asyncio.run(
        sa.run_ask(context, "provider", material, "第 30 秒发生了什么", visual=False)
    )
    assert answer == "答案"
    prompt = context.kwargs.get("prompt") or ""
    assert "请按以下结构" not in prompt
    assert "直接回答用户的问题" in prompt
    assert context.kwargs.get("system_prompt") == sa.ASK_SYSTEM_PROMPT
    print("✅ 追问子代理：ask 提示词与短答案")


def test_http_mock_parsing() -> None:
    client = bc.BiliClient(interval=0)
    view_payload = {
        "bvid": "BV1mock",
        "aid": 100,
        "cid": 200,
        "title": "模拟视频",
        "owner": {"name": "模拟UP", "mid": 9},
        "duration": 100,
        "desc": "简介",
        "pubdate": 1700000000,
        "pages": [{"cid": 200, "duration": 100}],
        "stat": {
            "view": 3460340,
            "danmaku": 7350,
            "reply": 21657,
            "like": 120323,
            "coin": 76899,
            "favorite": 24588,
            "share": 77069,
        },
    }
    client.http.get_json = lambda *args, **kwargs: {"code": 0, "data": view_payload}
    video = client.get_video("BV1mock")
    assert video.views == 3460340 and video.likes == 120323
    assert video.favorites == 24588 and video.pubdate == 1700000000

    comment_payload = {
        "replies": [
            {"member": {"uname": "A"}, "content": {"message": "普通评论"}, "like": 1}
        ],
        "top_replies": [
            {"member": {"uname": "UP"}, "content": {"message": "置顶评论"}, "like": 9}
        ],
    }
    client.http.get_json = lambda *args, **kwargs: {"code": 0, "data": comment_payload}
    comments = client.get_comments(100, limit=12, include_pinned=True)
    assert comments[0].pinned and comments[0].content == "置顶评论"
    print("✅ HTTP mock：视频 stat / 置顶评论解析")


def test_backoff_retry() -> None:
    import urllib.error

    http = bc.BiliHTTP()
    calls = {"n": 0}

    def fake_request(url, timeout=20, headers=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(url, 412, "blocked", {}, None)
        return b'{"code": 0, "data": {"ok": true}}'

    http.request = fake_request
    data = http.get_json("https://example.invalid/test", retries=1)
    assert calls["n"] == 2 and data["data"]["ok"] is True
    print("✅ 412 指数退避后重试成功")


def test_frame_tool() -> None:
    import main as plugin_main

    tmp = Path(tempfile.mkdtemp())
    try:
        frame = tmp / "frame.jpg"
        from PIL import Image

        Image.new("RGB", (64, 48), (30, 60, 90)).save(frame)
        video = bc.VideoInfo(
            bvid="BV1frame",
            aid=1,
            cid=2,
            page=1,
            page_count=1,
            title="测试",
            up_name="UP",
            up_uid=1,
            duration=100,
            desc="",
        )
        material = bc.Material(video=video, frames=[frame], frame_times=[30.0])
        plugin = object.__new__(plugin_main.BilibiliEyesPlugin)
        plugin._config = {**plugin_main.DEFAULT_OPTIONS}
        plugin._materials = eyes_cache.MaterialStore()
        plugin._materials.put("s:1", material, "摘要")
        plugin._data_dir = lambda: tmp

        class FakeEvent:
            unified_msg_origin = "s:1"

        result = asyncio.run(plugin.tool_frame(FakeEvent(), "00:30"))
        kinds = [type(item).__name__ for item in result.content]
        assert kinds == ["TextContent", "ImageContent"], kinds
        assert result.content[1].data
        print("✅ bilibili_frame：时间点→单帧 ImageContent")
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def test_cleaning_and_dedupe() -> None:
    desc = (
        "第一行核心介绍\n"
        "淘宝店铺 https://shop.example.com\n"
        "BGM：某首曲子\n"
        "粉丝群 123456789\n"
        "#标签#\n"
        "第二行核心内容"
    )
    cleaned = ec.clean_description(desc)
    assert "核心介绍" in cleaned and "第二行核心内容" in cleaned
    assert "淘宝" not in cleaned and "BGM" not in cleaned and "粉丝群" not in cleaned

    merged = ec.merge_subtitles(
        [(1.0, "就是就是"), (1.2, "然后那个"), (1.4, "我们开始"), (3.0, "第二句。")]
    )
    assert len(merged) >= 1
    assert "就是" in merged[0][1]

    assert ec.is_low_value_comment("抽奖接龙")
    assert ec.is_low_value_comment("666666")
    assert not ec.is_low_value_comment("这一段讲得很有道理")
    assert ec.extract_time_marks("01:23 开始，05:40 干货") == ["01:23", "05:40"]
    assert ec.danmaku_keywords(["泪目", "666", "前方高能", "泪目"])[0] == "泪目"

    client = bc.BiliClient(interval=0)
    xml = '<i><d p="10.0,1,25,16777215">泪目</d><d p="11.0,1,25,16777215">666</d><d p="70.0,1,25,16777215">前方高能</d></i>'.encode("utf-8")
    client.http.request = lambda *args, **kwargs: xml
    peaks, keywords = client.get_danmaku_insights(1, 120)
    assert peaks and keywords
    assert any("泪目" in text for _ts, text in keywords)

    from PIL import Image

    tmp = Path(tempfile.mkdtemp())
    try:
        paths = []
        import random

        random.seed(7)
        base = Image.new("RGB", (64, 64))
        for x in range(64):
            for y in range(64):
                value = random.randrange(256)
                base.putpixel((x, y), (value, value // 2, 255 - value))
        for index in range(3):
            path = tmp / f"f{index}.jpg"
            if index < 2:
                image = base.copy()
            else:
                image = Image.eval(base, lambda value: 255 - value)
            image.save(path)
            paths.append((path, float(index * 10)))
        kept = ec.dedupe_frames(paths, max_count=3)
        assert len(kept) == 2, kept
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)
    print("✅ 清洗：简介/字幕/评论/弹幕/帧去重")


def test_audio_stub() -> None:
    async def call() -> None:
        await eyes_audio.AudioTranscriber().transcribe(Path("x.mp3"))

    try:
        asyncio.run(call())
    except NotImplementedError:
        pass
    else:
        raise AssertionError("音频接口桩应抛 NotImplementedError")
    print("✅ 音频转录接口桩")


def test_schema() -> None:
    schema = json.loads((PLUGIN_DIR / "_conf_schema.json").read_text(encoding="utf-8"))
    required = {
        "enabled",
        "nl_trigger_enabled",
        "injection_guard",
        "quota_exempt_admins",
        "quota_exempt_users",
        "sessdata",
        "vision_provider_id",
        "frame_count",
        "digest_max_chars",
        "wait_notice_template",
        "cache_ttl_hours",
    }
    assert required <= set(schema), required - set(schema)
    assert schema["frame_count"]["default"] == 12
    assert schema["nl_trigger_enabled"]["default"] is True
    meta = (PLUGIN_DIR / "metadata.yaml").read_text(encoding="utf-8")
    assert "name: astrbot_plugin_bilibili_eyes" in meta
    assert "display_name: B站之眼" in meta
    assert "version: 0.5.7" in meta
    print("✅ 配置 schema / metadata")


def test_archive_fallback() -> None:
    payload = {
        "total": 26,
        "videos": [{"title": "视频A"}, {"title": "视频B"}],
    }

    class Resp:
        def __init__(self, data: dict):
            self._data = data

        def read(self) -> bytes:
            return json.dumps(self._data).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    original = bc.urllib.request.urlopen
    bc.urllib.request.urlopen = lambda *args, **kwargs: Resp(payload)
    try:
        titles, total = bc.BiliClient(interval=0)._fallback_archives(1)
        assert titles == ["视频A", "视频B"] and total == 26
        disabled = bc.BiliClient(interval=0, archive_fallback_enabled=False)
        assert disabled._fallback_archives(1) == ([], 0)
    finally:
        bc.urllib.request.urlopen = original
    print("✅ 近期投稿第三方兜底解析")


def main() -> int:
    test_parse_refs()
    test_card_resolver()
    test_frame_selection()
    test_digest_helpers()
    test_note_cache()
    test_material_store()
    test_archive_fallback()
    test_ask_prompt()
    test_http_mock_parsing()
    test_cleaning_and_dedupe()
    test_backoff_retry()
    test_frame_tool()
    test_audio_stub()
    test_schema()
    print("\n全部离线测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
