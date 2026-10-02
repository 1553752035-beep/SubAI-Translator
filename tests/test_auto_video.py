# -*- coding: utf-8 -*-
"""五期：任务完成后自动出片（软字幕/硬字幕）的单元测试。"""
from __future__ import annotations

import asyncio

from src.api.server import _output_label, _pick_subtitle, _produce_video, _unique_path
from src.pipeline import is_no_translate


def run(coro):
    return asyncio.run(coro)


class TestUniquePath:
    def test_free_path_untouched(self, tmp_path):
        p = str(tmp_path / "a.mkv")
        assert _unique_path(p) == p

    def test_appends_suffix_when_exists(self, tmp_path):
        p = str(tmp_path / "a.mkv")
        open(p, "w").close()
        assert _unique_path(p) == str(tmp_path / "a_1.mkv")
        open(str(tmp_path / "a_1.mkv"), "w").close()
        assert _unique_path(p) == str(tmp_path / "a_2.mkv")


class TestPickSubtitle:
    def test_prefers_target_language(self):
        files = ["/x/demo.source.srt", "/x/demo.bilingual.srt", "/x/demo.en.srt"]
        assert _pick_subtitle(files, "en") == "/x/demo.en.srt"

    def test_falls_back_to_bilingual_then_source(self):
        assert _pick_subtitle(["/x/demo.source.srt", "/x/demo.bilingual.srt"], "en") == "/x/demo.bilingual.srt"
        assert _pick_subtitle(["/x/demo.source.srt"], "en") == "/x/demo.source.srt"

    def test_ignores_non_subtitle_files(self):
        assert _pick_subtitle(["/x/demo.en.json", "/x/demo.mp4"], "en") == ""


class TestOutputLabel:
    def test_uses_chinese_name(self):
        assert _output_label("zh") == "中文"
        assert _output_label("en") == "英语"

    def test_original_when_not_translating(self):
        assert _output_label("none") == "原文"
        assert _output_label("original") == "原文"
        assert _output_label("") == "原文"

    def test_unknown_code_returned_as_is(self):
        assert _output_label("xx-unknown") == "xx-unknown"


class TestProduceVideo:
    def test_none_mode_does_nothing(self, tmp_path):
        video = tmp_path / "demo.mp4"
        video.write_bytes(b"x")
        assert run(_produce_video("t1", str(video), ["/x/demo.en.srt"], "en", "none")) == []

    def test_no_subtitle_does_nothing(self, tmp_path):
        video = tmp_path / "demo.mp4"
        video.write_bytes(b"x")
        assert run(_produce_video("t1", str(video), ["/x/demo.en.json"], "en", "soft")) == []

class TestNoTranslate:
    """五期：不翻译只识别 —— 目标语言的写法判定（界面第 2 个入口靠它）。"""

    def test_recognizes_no_translate_words(self):
        for word in ("none", "original", "source", "off", "no", "NONE", " original "):
            assert is_no_translate(word) is True, word

    def test_normal_languages_are_translated(self):
        for word in ("zh", "en", "English", "日本語", ""):
            assert is_no_translate(word) is False, word

    def test_no_translate_output_filename_and_subtitle_pick(self):
        # 不翻译时产物是 <stem>.source.srt，成品名用「原文」
        files = ["/x/demo.source.srt"]
        assert _pick_subtitle(files, "none") == "/x/demo.source.srt"
        assert _output_label("none") == "原文"
