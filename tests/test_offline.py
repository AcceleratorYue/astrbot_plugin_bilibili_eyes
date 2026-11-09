"""Phase 1 离线自测：解析 / 选帧 / 缓存 / 提示词 / schema。"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from array import array
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
import eyes_enhanced as ee  # noqa: E402
import eyes_extreme as ex  # noqa: E402
import eyes_ocr as eo  # noqa: E402
import eyes_auth as ea  # noqa: E402
import eyes_subagent as sa  # noqa: E402
import eyes_transcript as et  # noqa: E402


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
    assert "当前对话角色原本的身份和语气" in main_prompt
    assert "先用一两句给出真实反应" in main_prompt
    assert "避免汇报腔" in main_prompt and "不强行积极" in main_prompt
    assert "不要主动报视频时长" in main_prompt and "不编造" in main_prompt
    assert "鲸鲸" not in main_prompt
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

    core, other = sa.split_note_sections(
        "<video_core_notes>核心故事</video_core_notes>\n"
        "<video_other_notes>评论区原文</video_other_notes>"
    )
    assert core == "核心故事" and other == "评论区原文"
    bundle = sa.format_note_bundle(core, other)
    assert "<video_core_notes>" in bundle and "<video_other_notes>" in bundle
    split_prompt = sa.build_main_model_prompt(
        bundle, template="核心：{core_digest}\n其他：{other_digest}"
    )
    assert "核心：核心故事" in split_prompt and "其他：评论区原文" in split_prompt
    assert "旧笔记" in sa.build_main_model_prompt("旧笔记")

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
        cache.set("BV1", 1, "增强笔记", variant="enhanced")
        assert cache.get("BV1", 1) == "笔记一"
        assert cache.get("BV1", 1, variant="enhanced") == "增强笔记"
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

    client.http.wbi_url = lambda path, params: "https://example.invalid/playurl"
    client.http.get_json = lambda *args, **kwargs: {
        "code": 0,
        "data": {
            "dash": {
                "video": [{"baseUrl": "https://example.invalid/v", "height": 480}],
                "audio": [
                    {"baseUrl": "https://example.invalid/high", "bandwidth": 128000},
                    {"baseUrl": "https://example.invalid/low", "bandwidth": 64000},
                ],
            }
        },
    }
    streams = client.get_stream_info("BV1mock", 200)
    assert streams.video_url.endswith("/v")
    assert streams.audio_url.endswith("/low")
    assert client.get_playurl("BV1mock", 200)[0].endswith("/v")
    print("✅ HTTP mock：视频 stat / 置顶评论 / 音频流解析")


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


def test_audio_transcriber() -> None:
    class FakeProvider:
        async def get_text(self, path: str) -> str:
            assert Path(path).exists()
            return "请不吝点赞。第一句台词。第二句台词！"

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "a.mp3"
        audio.write_bytes(b"fake-audio")
        subs = asyncio.run(
            eyes_audio.AudioTranscriber(FakeProvider()).transcribe(
                audio, duration=12
            )
        )
    assert subs and subs[0][0] == 0
    assert "请不吝点赞" not in "".join(text for _t, text in subs)
    assert 0 <= subs[-1][0] <= 12
    assert "第一句台词" in "".join(text for _t, text in subs)
    assert eyes_audio.text_to_subtitles("", 10) == []
    print("✅ ASR：文本清洗 / 断句 / 近似时间轴")


def test_audio_pipeline() -> None:
    import main as plugin_main

    class FakeProvider:
        async def get_text(self, path: str) -> str:
            return "第一句。第二句！"

    class FakeContext:
        def get_all_stt_providers(self):
            return [FakeProvider()]

        async def get_using_stt_provider_async(self, umo=None):
            return FakeProvider()

    class FakeClient:
        def __init__(self):
            self.extract_args = None
            self.starts = []

        def get_stream_info(self, bvid, cid):
            return bc.StreamInfo(
                video_url="https://example.com/v.mp4",
                audio_url="https://example.com/a.m4s",
                height=480,
            )

        def extract_audio(
            self, url, path, max_seconds, max_mb, start_seconds=0
        ):
            self.extract_args = (url, max_seconds, max_mb, start_seconds)
            self.starts.append(start_seconds)
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"fake-audio")
            return True

    with tempfile.TemporaryDirectory() as tmp:
        plugin = object.__new__(plugin_main.BilibiliEyesPlugin)
        plugin._config = {
            **plugin_main.DEFAULT_OPTIONS,
            "audio_transcription_enabled": True,
            "include_subtitle": True,
            "cache_enabled": False,
        }
        plugin.context = FakeContext()
        fake_client = FakeClient()
        plugin._client = lambda: fake_client
        plugin._data_dir = lambda: Path(tmp)

        async def run(func, *args):
            return func(*args)

        plugin._run = run
        video = bc.VideoInfo(
            bvid="BV1asr",
            aid=1,
            cid=2,
            page=1,
            page_count=1,
            title="ASR 测试",
            up_name="UP",
            up_uid=1,
            duration=30,
            desc="",
        )
        material = bc.Material(video=video)
        job = SimpleNamespace(stage="")
        event = SimpleNamespace(unified_msg_origin="test:GroupMessage:1")
        asyncio.run(plugin._transcribe_audio_if_needed(material, event, job))
        assert material.subtitle_source == "asr"
        assert material.subtitles
        assert fake_client.extract_args[1] == 30
        assert job.stage.startswith("音频转录")
        assert not (Path(tmp) / "cache").exists() or not list(
            (Path(tmp) / "cache").glob("*.mp3")
        )

        plugin._config["audio_transcription_mode"] = "always"
        material_with_subtitle = bc.Material(video=video)
        material_with_subtitle.subtitles = [(0.0, "官方字幕")]
        asyncio.run(
            plugin._transcribe_audio_if_needed(
                material_with_subtitle, event, SimpleNamespace(stage="")
            )
        )
        assert material_with_subtitle.subtitles == [(0.0, "官方字幕")]
        assert material_with_subtitle.asr_subtitles
        assert material_with_subtitle.subtitle_source == "official"
        assert any("常开" in item for item in material_with_subtitle.warnings)

        plugin._config["audio_transcription_mode"] = "no_subtitle"
        skipped = bc.Material(video=video)
        skipped.subtitles = [(0.0, "官方字幕")]
        asyncio.run(
            plugin._transcribe_audio_if_needed(
                skipped, event, SimpleNamespace(stage="")
            )
        )
        assert skipped.asr_subtitles == []
        assert skipped.subtitles == [(0.0, "官方字幕")]

        long_video = bc.VideoInfo(
            bvid="BV1asrlong",
            aid=1,
            cid=2,
            page=1,
            page_count=1,
            title="ASR 分块测试",
            up_name="UP",
            up_uid=1,
            duration=700,
            desc="",
        )
        before = len(fake_client.starts)
        plugin._config["audio_transcription_max_seconds"] = 600
        long_material = bc.Material(video=long_video)
        asyncio.run(
            plugin._transcribe_audio_if_needed(
                long_material, event, SimpleNamespace(stage="")
            )
        )
        assert fake_client.starts[before:] == [0, 300]
        assert long_material.subtitles
    print("✅ ASR：无字幕接入 / 常开补充 / 默认跳过 / 长音频分块")


def test_enhanced_core() -> None:
    from PIL import Image

    cfg = ee.EnhancedConfig(
        frame_count=4,
        sample_fps=2,
        cut_abs=12,
        cut_spike=2.5,
        integral_seconds=100,
        silent_floor_seconds=1000,
    )
    samples = [
        ee.FrameSample(
            float(index),
            array("f", [float(index * 40), 100.0, 100.0]),
            score,
        )
        for index, score in enumerate([0.0, 50.0, 0.0, 0.0])
    ]
    keys = ee.select_keyframes(samples, 20, cfg)
    assert keys and keys[0].time == 0
    assert any(item.via == "cut" for item in keys)
    assert len(keys) == 4

    times = [float(index * 10) for index in range(24)]
    tiers = ee.assign_tiers(times)
    plan = ee.solve(tiers, bin_cost=1000)
    assert plan["bins"] == 1
    assert len(plan["cells"]) == 24
    rects = ee.to_rects(plan["cells"], 1280, 720, 4)
    assert len(rects) == 24
    assert all(rect["pw"] > 0 and rect["ph"] > 0 for rect in rects)
    for left in range(len(rects)):
        for right in range(left + 1, len(rects)):
            a, b = rects[left], rects[right]
            overlap_x = min(a["px"] + a["pw"], b["px"] + b["pw"]) - max(
                a["px"], b["px"]
            )
            overlap_y = min(a["py"] + a["ph"], b["py"] + b["ph"]) - max(
                a["py"], b["py"]
            )
            assert overlap_x <= 0 or overlap_y <= 0

    with tempfile.TemporaryDirectory() as tmp:
        frames = []
        for index in range(4):
            path = Path(tmp) / f"f{index}.jpg"
            Image.new("RGB", (64, 36), (index * 50, 40, 80)).save(path)
            frames.append(ee.SheetFrame(index * 2.0, path, 4))
        cells = ee.solve([4, 4, 4, 4], bin_cost=1000)["cells"]
        layout = ee.compose_sheet(
            frames, cells, Path(tmp) / "sheet.jpg", 640, 360, 4
        )
        assert layout.sheet.exists()
        assert len(layout.cells) == 4
    print("✅ 增强模式：变化选帧 / DP 单箱 / 16:9 拼图")


def test_enhanced_pipeline() -> None:
    import main as plugin_main
    from PIL import Image

    class FakeClient:
        def get_stream_info(self, bvid, cid):
            return bc.StreamInfo(
                video_url="https://example.invalid/video",
                audio_url="",
                height=480,
            )

        def iter_lowres_frames(
            self, url, fps=2, max_seconds=1200, width=64, height=36
        ):
            for index in range(48):
                color = (index * 5) % 256
                raw = bytes([color, (index * 11) % 256, 80]) * (width * height)
                yield index / fps, raw

        def extract_frames(
            self, url, timestamps, out_dir, height=480, max_mb=3
        ):
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            pairs = []
            for index, timestamp in enumerate(timestamps):
                path = out_dir / f"frame_{index:02d}.jpg"
                Image.new("RGB", (320, 180), (index * 20 % 255, 40, 90)).save(path)
                pairs.append((path, timestamp))
            return pairs

    with tempfile.TemporaryDirectory() as tmp:
        plugin = object.__new__(plugin_main.BilibiliEyesPlugin)
        plugin._config = {
            **plugin_main.DEFAULT_OPTIONS,
            "enhanced_mode": True,
            "enhanced_frame_count": 24,
            "enhanced_sample_fps": 2,
            "enhanced_max_analysis_seconds": 120,
            "enhanced_fallback_to_normal": False,
            "cache_enabled": False,
        }
        plugin._active = {}
        plugin._client = lambda: FakeClient()
        plugin._data_dir = lambda: Path(tmp)

        async def run(func, *args):
            return func(*args)

        plugin._run = run
        video = bc.VideoInfo(
            bvid="BV1enh",
            aid=1,
            cid=2,
            page=1,
            page_count=1,
            title="增强测试",
            up_name="UP",
            up_uid=1,
            duration=24,
            desc="",
        )
        material = bc.Material(video=video)
        event = SimpleNamespace(unified_msg_origin="test:GroupMessage:1")
        asyncio.run(plugin._fill_frames_enhanced(material, event))
        assert material.enhanced_sheet
        assert material.frames and Path(material.frames[0]).exists()
        assert material.frame_layout
        assert len(material.frame_layout) <= 24
        prompt = sa.build_material_prompt(material)
        assert "连续拼图组" in prompt and "格 " in prompt
        assert all(Path(path).exists() for path in material.frames)
    print("✅ 增强模式：端到端假流 / 多张拼图 / layout / 提示词")


def test_extreme_pipeline() -> None:
    import main as plugin_main
    from PIL import Image

    class FakeClient:
        def get_stream_info(self, bvid, cid):
            return bc.StreamInfo(
                video_url="https://example.invalid/video",
                audio_url="",
                height=480,
            )

        def iter_lowres_frames(
            self, url, fps=2, max_seconds=1200, width=64, height=36
        ):
            for index in range(48):
                color = (index * 7) % 256
                raw = bytes([color, (index * 13) % 256, 90]) * (width * height)
                yield index / fps, raw

        def extract_frames(
            self, url, timestamps, out_dir, height=480, max_mb=3
        ):
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            pairs = []
            for index, timestamp in enumerate(timestamps):
                path = out_dir / f"extreme_{index:02d}.jpg"
                Image.new("RGB", (320, 180), (index * 17 % 255, 60, 100)).save(path)
                pairs.append((path, timestamp))
            return pairs

    with tempfile.TemporaryDirectory() as tmp:
        plugin = object.__new__(plugin_main.BilibiliEyesPlugin)
        plugin._config = {
            **plugin_main.DEFAULT_OPTIONS,
            "video_mode": "extreme",
            "extreme_max_frames": 12,
            "extreme_max_sheets": 3,
            "extreme_readability": "scene",
            "extreme_sample_fps": 2,
            "enhanced_sample_fps": 2,
            "enhanced_max_analysis_seconds": 120,
            "cache_enabled": False,
        }
        plugin._active = {}
        plugin._client = lambda: FakeClient()
        plugin._data_dir = lambda: Path(tmp)

        async def run(func, *args):
            return func(*args)

        plugin._run = run
        video = bc.VideoInfo(
            bvid="BV1ext",
            aid=1,
            cid=2,
            page=1,
            page_count=1,
            title="极致测试",
            up_name="UP",
            up_uid=1,
            duration=24,
            desc="",
        )
        material = bc.Material(video=video)
        event = SimpleNamespace(unified_msg_origin="test:GroupMessage:1")
        asyncio.run(plugin._fill_frames_extreme(material, event))
        assert material.frames and material.frame_layout
        assert material.frame_plan
        assert material.frame_plan["mode"] == "extreme"
        assert all("from" in item and "to" in item for item in material.frame_layout)
        assert all("readability" in item for item in material.frame_layout)
        prompt = sa.build_material_prompt(material)
        assert "动态帧预算" in prompt and "区间" in prompt
        assert all(Path(path).exists() for path in material.frames)
    print("✅ 极致模式：端到端假流 / 动态帧 / 区间元数据 / 提示词")


def test_extreme_planner() -> None:
    def material_for(duration: int, text: str = "", cuts: int = 4):
        video = bc.VideoInfo(
            bvid="BV1extreme",
            aid=1,
            cid=2,
            page=1,
            page_count=1,
            title="极致测试",
            up_name="UP",
            up_uid=1,
            duration=duration,
            desc="",
        )
        material = bc.Material(video=video)
        if text:
            material.subtitles = [
                (index * max(1.0, duration / 8), text)
                for index in range(8)
            ]
        keyframes = [
            SimpleNamespace(
                time=index * duration / max(1, cuts),
                score=30.0 if index % 2 == 0 else 6.0,
                via="cut" if index % 2 == 0 else "mark",
            )
            for index in range(cuts)
        ]
        return material, keyframes

    short, short_keys = material_for(10, cuts=2)
    short_plan = ex.plan_frames(short, short_keys, max_frames=24, max_sheets=4)
    assert 4 <= short_plan.target_frames <= 8
    assert short_plan.actual_frames == 0

    long_material, long_keys = material_for(1800, cuts=12)
    long_plan = ex.plan_frames(long_material, long_keys, max_frames=48, max_sheets=8)
    assert long_plan.target_frames > 24

    text_material, text_keys = material_for(
        76, text="这是一段信息量很高的官方字幕内容，包含人物对白和剧情推进。", cuts=8
    )
    text_plan = ex.plan_frames(text_material, text_keys, max_frames=48, max_sheets=8)
    plain_material, plain_keys = material_for(76, cuts=8)
    plain_plan = ex.plan_frames(plain_material, plain_keys, max_frames=48, max_sheets=8)
    assert text_plan.text.score > 0
    assert text_plan.target_frames <= plain_plan.target_frames

    text_material.comments = [
        SimpleNamespace(content="评论原文" * 20) for _ in range(8)
    ]
    text_plan.actual_frames = 12
    budget = ex.estimate_note_budget(text_material, text_plan)
    assert 1500 <= budget.core_chars <= 9000
    assert 800 <= budget.other_chars <= 3500
    assert budget.total_chars == budget.core_chars + budget.other_chars
    assert ex.readability_capacity("text") < ex.readability_capacity("scene")
    layout = ex.plan_sheet_layout("scene", 1200000)
    assert layout["capacity"] >= 6
    assert layout["width"] <= 1280 and layout["width"] * layout["height"] <= 1200000
    low_layout = ex.plan_sheet_layout("scene", 200000)
    assert low_layout["capacity"] < layout["capacity"]
    scene_rows = ex.plan_scene_times(text_material, text_keys, 12, 76)
    assert 1 <= len(scene_rows) <= 12
    assert all(row["from"] <= row["time"] <= row["to"] for row in scene_rows)
    groups = ex.candidate_groups(text_keys, 76)
    assert groups and all(group["times"] for group in groups)

    # 无切点/长静态视频：均匀补齐 keyframes，且场景分配必须覆盖全时段。
    uniform = ee._fill_keyframes(
        [ee.Keyframe(0.0, 0.0, "first")], 182.0, 12
    )
    assert uniform and max(item.time for item in uniform) <= 182.0
    static_material = SimpleNamespace(
        video=SimpleNamespace(duration=182),
        subtitles=[],
        asr_subtitles=[],
    )
    sparse_keys = [ee.Keyframe(0.0, 0.0, "first"), ee.Keyframe(11.0, 16.0, "cut")]
    sparse_rows = ex.plan_scene_times(static_material, sparse_keys, 15, 182.0)
    assert len(sparse_rows) == 15
    assert max(row["time"] for row in sparse_rows) > 150.0
    print("✅ 极致模式：动态帧预算 / 文本画像 / 笔记预算 / 像素布局 / 场景分配")


def test_compression_and_candidate_times() -> None:
    class FakeContext:
        def __init__(self):
            self.calls = []

        async def llm_generate(self, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(
                completion_text=(
                    "<video_core_notes>压缩后的核心故事</video_core_notes>"
                    "<video_other_notes>压缩后的评论区原文</video_other_notes>"
                )
            )

    context = FakeContext()
    result = asyncio.run(
        sa.compress_digest(
            context,
            "provider",
            "核心" * 100,
            "评论" * 100,
            20,
            10,
        )
    )
    assert "压缩后的核心故事" in result
    assert "压缩后的评论区原文" in result
    assert context.calls and context.calls[0]["image_urls"] == []
    groups = ex.candidate_groups(
        [SimpleNamespace(time=10.0, via="cut", score=1)], 30
    )
    assert groups[0]["times"] and groups[0]["times"][0] > 10.0
    print("✅ 极致超预算：二次压缩 / 候选帧避开切点")


def test_embedded_ocr_and_asr_quality() -> None:
    class FakeFrames:
        def iter_subtitle_frames(self, *args, **kwargs):
            # 前 5 秒画面/字幕相同，模拟 1fps 下同一句字幕被跳帧采样。
            same = b"x" * (960 * 320 * 3)
            for index in range(9):
                raw = same if index < 5 else bytes([(index * 73 + 20) % 256]) * (960 * 320 * 3)
                yield float(index), raw

    class FakeEngine:
        def __init__(self):
            self.calls = 0

        def recognize(self, image):
            self.calls += 1
            if self.calls <= 4:
                return [("这就是问题所在", 0.92, 0)]
            return [("That is the problem", 0.91, 0)]

    config = eo.OcrConfig(enabled=True, fps=1, min_confidence=0.6, min_coverage=0.1)
    result = eo.extract_embedded_subtitles(
        FakeFrames(), "https://example.invalid/v", 8.0, config, engine=FakeEngine()
    )
    assert result.tracks and result.tracks[0].origin == "ocr"
    assert result.tracks[0].lines
    assert result.coverage > 0.3
    assert result.tracks[0].lines[0][1]

    ok, reason = eo.evaluate_asr_quality(["why?", "why?", "why?", "why?"])
    assert not ok and reason in ("high_repetition", "filler_heavy")
    ok, _ = eo.evaluate_asr_quality(["这是完整的一句话", "第二句有实际内容", "第三句也正常"])
    assert ok
    import main as plugin_main

    plugin = object.__new__(plugin_main.BilibiliEyesPlugin)
    plugin._config = {
        **plugin_main.DEFAULT_OPTIONS,
        "ocr_subtitle_enabled": True,
        "ocr_subtitle_priority": "after_ai",
    }
    ai_track = bc.SubtitleTrack("zh", "中文", [(0.0, "AI")], origin="ai", is_ai=True)
    human_track = bc.SubtitleTrack("zh", "中文", [(0.0, "人工")], origin="official")
    assert plugin._should_try_ocr([]) is True
    assert plugin._should_try_ocr([ai_track]) is False
    assert plugin._should_try_ocr([human_track]) is False
    plugin._config["ocr_subtitle_priority"] = "before_ai"
    assert plugin._should_try_ocr([ai_track]) is True
    print("✅ 内嵌 OCR：采样/去重/置信度 / ASR 幻觉质量门")


def test_video_mode() -> None:
    import main as plugin_main

    plugin = object.__new__(plugin_main.BilibiliEyesPlugin)
    base = {**plugin_main.DEFAULT_OPTIONS, "enhanced_mode": False}
    plugin._config = {**base, "video_mode": "auto"}
    assert plugin._video_mode() == "normal"
    plugin._config["enhanced_mode"] = True
    assert plugin._video_mode() == "enhanced"
    plugin._config["video_mode"] = "extreme"
    assert plugin._video_mode() == "extreme"
    assert plugin._cache_variant() == "extreme"
    print("✅ 三模式：auto/legacy/enhanced/extreme 选择")


def test_bilingual_subtitle_tracks() -> None:
    class FakeHTTP:
        def __init__(self):
            self.body = {
                "zh": {"body": [{"from": 0, "content": "第一句中文"}, {"from": 1.2, "content": "第二句中文"}]},
                "en": {"body": [{"from": 0, "content": "First English line"}, {"from": 1.2, "content": "Second English line"}]},
                "ai": {"body": [{"from": 0, "content": "AI 中文"}]},
            }

        def absolute(self, url):
            return url

        def get_json(self, url, timeout=0):
            return self.body[url]

    client = bc.BiliClient(interval=0)
    client.http = FakeHTTP()
    player = {
        "subtitle": {
            "subtitles": [
                {"lan": "zh-Hans", "lan_doc": "中文（简体）", "subtitle_url": "zh"},
                {"lan": "ai-zh", "lan_doc": "中文（AI）", "subtitle_url": "ai", "ai_type": 1},
                {"lan": "en-US", "lan_doc": "English", "subtitle_url": "en"},
            ]
        }
    }
    tracks = client.get_subtitle_tracks(
        player, ["zh-Hans", "zh", "ai-zh", "en"], ["en", "en-US"]
    )
    assert [track.lang for track in tracks] == ["zh-Hans", "en-US"]
    assert tracks[0].role == "primary" and tracks[1].role == "secondary"
    assert tracks[0].lines[0][1] == "第一句中文"
    assert tracks[1].lines[0][1] == "First English line"

    only_primary = client.get_subtitle_tracks(
        player, ["zh-Hans"], [], dual=False
    )
    assert len(only_primary) == 1

    english_primary = client.get_subtitle_tracks(
        player, ["en-US"], ["en"], dual=True
    )
    assert [track.lang for track in english_primary] == ["en-US", "zh-Hans"]

    single = bc.BiliClient(interval=0)
    single.http = FakeHTTP()
    one_track_player = {
        "subtitle": {
            "subtitles": [
                {
                    "lan": "en-US",
                    "lan_doc": "English",
                    "subtitle_url": "en",
                }
            ]
        }
    }
    single_track = single.get_subtitle_tracks(one_track_player, ["en"], [], dual=True)
    assert len(single_track) == 1

    with tempfile.TemporaryDirectory() as tmp:
        store = et.TranscriptStore(Path(tmp), ttl_hours=1, max_entries=5)
        assert store.save(
            "BV1dual",
            1,
            "双语测试",
            30,
            tracks[0].lines,
            [],
            "available",
            "absent",
            tracks=[
                {
                    "lang": "zh-Hans",
                    "lang_doc": "中文（简体）",
                    "role": "primary",
                    "lines": tracks[0].lines,
                },
                {
                    "lang": "en-US",
                    "lang_doc": "English",
                    "role": "secondary",
                    "lines": tracks[1].lines,
                },
            ],
        )
        loaded = store.load("BV1dual", 1)
        assert loaded and len(loaded["tracks"]) == 2
        assert loaded["official_secondary"][0][1] == "First English line"
        result = et.search(loaded, query="English line", lang="en")
        text = et.format_result(loaded, result)
        assert "官方辅轨·English" in text and "First English line" in text

    video = bc.VideoInfo(
        bvid="BV1dual", aid=1, cid=2, page=1, page_count=1,
        title="双语测试", up_name="UP", up_uid=1, duration=30, desc="",
    )
    material = bc.Material(video=video)
    material.subtitles = tracks[0].lines
    material.secondary_subtitles = tracks[1].lines
    material.subtitle_lang = tracks[0].lang
    material.subtitle_lang_doc = tracks[0].lang_doc
    material.secondary_lang = tracks[1].lang
    material.secondary_lang_doc = tracks[1].lang_doc
    material.subtitle_tracks = tracks
    prompt = sa.build_material_prompt(material)
    assert "双语字幕" in prompt and "中文（简体）" in prompt and "English" in prompt
    assert "First English line" in prompt
    print("✅ 双语字幕：主辅轨选择 / 不同语系 / 原文检索 / 提示词")


def test_transcript_direct_read() -> None:
    import main as plugin_main

    official = [(0.0, "第一句官方字幕"), (12.0, "本体已经接入用户钱包")]
    asr = [(0.0, "第一句 ASR"), (12.5, "本体已经接入用户钱包啦")]
    with tempfile.TemporaryDirectory() as tmp:
        store = et.TranscriptStore(Path(tmp), ttl_hours=1, max_entries=5)
        assert store.save(
            "BV1read", 1, "回读测试", 30, official, asr, "available", "available", "fp"
        )
        loaded = store.load("BV1read", 1)
        assert loaded and loaded["official"] and loaded["asr"]
        result = et.search(loaded, query="钱包", max_lines=10)
        text = et.format_result(loaded, result)
        assert "官方字幕" in text and "ASR（约）" in text
        assert "本体已经接入用户钱包" in text

        video = bc.VideoInfo(
            bvid="BV1read",
            aid=1,
            cid=2,
            page=1,
            page_count=1,
            title="回读测试",
            up_name="UP",
            up_uid=1,
            duration=30,
            desc="",
        )
        material = bc.Material(video=video)
        material.subtitles = official
        material.asr_subtitles = asr
        material.official_status = "available"
        material.asr_status = "available"
        plugin = object.__new__(plugin_main.BilibiliEyesPlugin)
        plugin._config = {**plugin_main.DEFAULT_OPTIONS, "enabled": True}
        plugin._materials = eyes_cache.MaterialStore(60, 2)
        plugin._session_materials = {
            "test:GroupMessage:1": {
                "kind": "video",
                "bvid": "BV1read",
                "page": 1,
            }
        }
        plugin._transcripts = store
        plugin._data_dir = lambda: Path(tmp)
        event = SimpleNamespace(unified_msg_origin="test:GroupMessage:1")
        plugin._materials.put(event.unified_msg_origin, material, "digest")
        answer = asyncio.run(
            plugin.tool_transcript(event, query="钱包", max_lines="5")
        )
        text = answer.content[0].text
        assert "官方字幕" in text and "ASR（约）" in text
        assert "本体已经接入用户钱包" in text

        # 内存材料清掉后，仍能从磁盘原文缓存读取。
        plugin._materials.drop(event.unified_msg_origin)
        answer = asyncio.run(
            plugin.tool_transcript(event, query="钱包", max_lines="5")
        )
        assert "本体已经接入用户钱包" in answer.content[0].text
    print("✅ 原文直读：缓存落盘 / 关键词 / 来源标注 / 子代理旁路")


def test_config_grouping() -> None:
    import main as plugin_main

    class FakeConfig(dict):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.saved = 0

        def save_config(self):
            self.saved += 1

    plugin = object.__new__(plugin_main.BilibiliEyesPlugin)
    plugin._config = {
        "enabled": False,
        "vision": {"video_mode": "extreme"},
        "extreme": {"extreme_max_frames": 24},
    }
    assert plugin._opt("enabled") is False
    assert plugin._opt("video_mode") == "extreme"
    assert plugin._opt("extreme_max_frames") == 24
    assert plugin._opt("frame_count") == plugin_main.DEFAULT_OPTIONS["frame_count"]

    flat = FakeConfig(
        {
            "enabled": False,
            "video_mode": "extreme",
            "extreme_max_frames": 24,
        }
    )
    plugin._config = flat
    plugin._migrate_grouped_config()
    assert flat["basic"]["enabled"] is False
    assert flat["vision"]["video_mode"] == "extreme"
    assert flat["extreme"]["extreme_max_frames"] == 24
    assert flat["runtime"]["_grouped_config_migrated"] is True
    assert flat.saved == 1
    assert plugin._opt("video_mode") == "extreme"
    print("✅ 配置分组：分组优先 / 扁平回退 / 自动迁移")


def test_auth_and_settings_spec() -> None:
    from plugin_api import settings_spec

    with tempfile.TemporaryDirectory() as tmp:
        manager = ea.CredentialManager(Path(tmp))
        assert not manager.has_valid_credential()
        manager.save({"sessdata": "abc123", "bili_jct": "j", "refresh_token": "r"})
        assert manager.get_sessdata() == "abc123"
        assert manager.summary()["present"] is True
        assert manager.summary()["sessdata_tail"].endswith("c123")
        manager.clear()
        assert not manager.has_valid_credential()

    assert len(settings_spec.GROUPS) >= 10
    assert "sessdata" in settings_spec.FIELDS
    clean, errors = settings_spec.validate_values(
        {"video_mode": "extreme", "ocr_subtitle_enabled": False, "group_whitelist": "a,b"}
    )
    assert not errors and clean["video_mode"] == "extreme"
    assert clean["ocr_subtitle_enabled"] is False
    assert clean["group_whitelist"] == ["a", "b"]
    _, errors = settings_spec.validate_values({"not_a_field": 1})
    assert errors
    print("✅ WebUI：扫码凭据管理 / 设置字段规格")


def test_web_api_registration_and_cache_listing() -> None:
    from plugin_api import PluginWebApi

    class FakeContext:
        def __init__(self):
            self.registered_web_apis = []

        def register_web_api(self, route, handler, methods, description):
            self.registered_web_apis.append((route, handler, tuple(methods)))

    plugin = SimpleNamespace(context=FakeContext())
    service = PluginWebApi(plugin)
    service.register()
    routes = [item[0] for item in plugin.context.registered_web_apis]
    assert "/astrbot_plugin_bilibili_eyes/overview" in routes
    assert "/astrbot_plugin_bilibili_eyes/transcript" in routes
    assert "/astrbot_plugin_bilibili_eyes/status" in routes
    assert "/astrbot_plugin_bilibili_eyes/settings" in routes
    assert "/astrbot_plugin_bilibili_eyes/login/qr" in routes
    service.unregister()
    assert not plugin.context.registered_web_apis

    with tempfile.TemporaryDirectory() as tmp:
        cache = eyes_cache.NoteCache(Path(tmp), ttl_hours=1, max_entries=10)
        cache.set(
            "BV1web", 1, "<video_core_notes>核心</video_core_notes>",
            {"title": "WebUI 测试", "mode": "extreme", "frames": 7}, "",
        )
        records = cache.list_records()
        assert records and records[0]["bvid"] == "BV1web"
        record = cache.get_record("BV1web", 1)
        assert record and record["digest"] and record["meta"]["mode"] == "extreme"
    print("✅ WebUI：API 注册 / 笔记列表 / 详情读取")


def test_schema() -> None:
    grouped = json.loads(
        (PLUGIN_DIR / "_conf_schema.json").read_text(encoding="utf-8")
    )
    assert "basic" in grouped and "vision" in grouped and "extreme" in grouped
    assert all(
        isinstance(item, dict) and item.get("type") == "object"
        for item in grouped.values()
    )
    schema = {}
    for group in grouped.values():
        schema.update(group.get("items") or {})
    required = {
        "enabled",
        "nl_trigger_enabled",
        "injection_guard",
        "quota_exempt_admins",
        "quota_exempt_users",
        "sessdata",
        "vision_provider_id",
        "frame_count",
        "frames_per_sheet",
        "digest_max_chars",
        "digest_other_max_chars",
        "wait_notice_template",
        "cache_ttl_hours",
        "audio_transcription_enabled",
        "audio_transcription_mode",
        "audio_transcription_provider_id",
        "audio_transcription_max_seconds",
        "audio_transcription_chunk_seconds",
        "audio_transcription_max_mb",
        "audio_transcription_timeout",
        "enhanced_mode",
        "enhanced_frame_count",
        "enhanced_digest_max_chars",
        "enhanced_other_max_chars",
        "enhanced_subagent_timeout",
        "enhanced_fallback_to_normal",
        "enhanced_frames_per_sheet",
        "extreme_max_frames",
        "extreme_max_sheets",
        "extreme_pixel_budget",
        "extreme_max_analysis_seconds",
        "extreme_readability",
        "extreme_note_core_max",
        "extreme_note_other_max",
        "transcript_ttl_hours",
        "transcript_max_entries",
    }
    assert required <= set(schema), required - set(schema)
    assert schema["frame_count"]["default"] == 12
    assert schema["nl_trigger_enabled"]["default"] is True
    assert schema["audio_transcription_mode"]["default"] == "no_subtitle"
    assert schema["audio_transcription_chunk_seconds"]["default"] == 300
    assert schema["enhanced_mode"]["default"] is False
    assert schema["enhanced_frame_count"]["default"] == 24
    assert schema["digest_max_chars"]["default"] == 2000
    assert schema["digest_other_max_chars"]["default"] == 1000
    assert schema["enhanced_digest_max_chars"]["default"] == 4500
    assert schema["enhanced_other_max_chars"]["default"] == 1500
    assert schema["frames_per_sheet"]["default"] == 6
    assert schema["enhanced_frames_per_sheet"]["default"] == 6
    assert schema["video_mode"]["default"] == "auto"
    assert schema["extreme_max_frames"]["default"] == 48
    assert schema["extreme_max_sheets"]["default"] == 8
    assert schema["extreme_pixel_budget"]["default"] == 1200000
    assert schema["extreme_max_analysis_seconds"]["default"] == 3600
    assert schema["extreme_readability"]["default"] == "scene"
    meta = (PLUGIN_DIR / "metadata.yaml").read_text(encoding="utf-8")
    assert "name: astrbot_plugin_bilibili_eyes" in meta
    assert "display_name: B站之眼" in meta
    assert "version: 0.13.2" in meta
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
    test_audio_transcriber()
    test_audio_pipeline()
    test_enhanced_core()
    test_enhanced_pipeline()
    test_extreme_pipeline()
    test_extreme_planner()
    test_compression_and_candidate_times()
    test_video_mode()
    test_bilingual_subtitle_tracks()
    test_embedded_ocr_and_asr_quality()
    test_transcript_direct_read()
    test_config_grouping()
    test_web_api_registration_and_cache_listing()
    test_auth_and_settings_spec()
    test_schema()
    print("\n全部离线测试通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
