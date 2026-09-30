# -*- coding: utf-8 -*-
"""
SubAI Translator —— 术语库命中测试（v3.1.6）
==============================================

此前术语只在"整行恰好等于术语"时命中,真实字幕里几乎不可能命中。
现改为:整行精确命中直接用术语译文;句中命中用 [[T#]] 占位符保护再还原。
本文件锁定该行为,并验证"术语行不读写缓存"的正确性策略。
"""
from __future__ import annotations

from src import pipeline
from src.config import config


class TestProtectRestore:
    def test_substring_term_is_replaced(self):
        ptext, mapping = pipeline._protect_terms("欢迎使用人工智能视频字幕", {"人工智能": "AI"})
        assert "人工智能" not in ptext
        assert "[[T0]]" in ptext
        assert mapping["[[T0]]"] == "AI"

    def test_longest_term_wins(self):
        terms = {"人工": "MANUAL", "人工智能": "AI"}
        ptext, mapping = pipeline._protect_terms("人工智能很棒", terms)
        assert mapping["[[T0]]"] == "AI"          # 长词优先
        assert "MANUAL" not in mapping.values()

    def test_multiple_terms(self):
        ptext, mapping = pipeline._protect_terms("人工智能与机器学习", {"人工智能": "AI", "机器学习": "ML"})
        assert len(mapping) == 2
        assert "[[T0]]" in ptext and "[[T1]]" in ptext

    def test_no_match_is_identity(self):
        ptext, mapping = pipeline._protect_terms("普通句子", {"人工智能": "AI"})
        assert ptext == "普通句子" and mapping == {}

    def test_restore(self):
        _, mapping = pipeline._protect_terms("人工智能", {"人工智能": "AI"})
        assert pipeline._restore_terms("about [[T0]] here", mapping) == "about AI here"


class TestTermMatchingInTranslate:
    def test_exact_line_bypasses_llm(self, monkeypatch):
        calls = {"n": 0}

        def fake(text, target, **k):
            calls["n"] += 1
            return "LLM"

        monkeypatch.setattr(pipeline, "_call_llm", fake)
        stats: dict = {}
        out = pipeline.translate(["人工智能"], "en", {"人工智能": "AI"},
                                 batch_size=10, use_cache=False, stats=stats)
        assert out == ["AI"]
        assert calls["n"] == 0            # 整行命中，完全不走 LLM
        assert stats["terms"] == 1

    def test_substring_term_applied_and_restored(self, monkeypatch):
        def fake(text, target, **k):
            if "Translate each numbered" in text:
                return "(no numbering)"      # 强制退回逐行，路径更明确
            return "T:" + text               # 原样回显 -> 占位符保留

        monkeypatch.setattr(pipeline, "_call_llm", fake)
        stats: dict = {}
        out = pipeline.translate(["欢迎使用人工智能字幕"], "en", {"人工智能": "AI"},
                                 batch_size=1, use_cache=False, stats=stats)
        assert out == ["T:欢迎使用AI字幕"]
        assert stats["terms"] == 1
        assert stats["failed"] == 0

    def test_scoreboard_counts_term_lines(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_call_llm", lambda text, target, **k: "T:" + text)
        stats: dict = {}
        pipeline.translate(["人工智能", "含人工智能的句子", "普通句子"], "en",
                           {"人工智能": "AI"}, batch_size=1, use_cache=False, stats=stats)
        assert stats["terms"] == 2         # 1 整行 + 1 句中


class TestTermCacheIsolation:
    def test_term_lines_do_not_use_cache(self, monkeypatch, tmp_path):
        def fake(text, target, **k):
            if "Translate each numbered" in text:
                return "(no numbering)"
            return "T:" + text

        monkeypatch.setattr(config.cache, "db_path", str(tmp_path / "c.db"))
        monkeypatch.setattr(pipeline, "_call_llm", fake)
        terms = {"人工智能": "AI"}

        pipeline.translate(["欢迎人工智能"], "en", terms, batch_size=1)   # 第一次
        stats: dict = {}
        out = pipeline.translate(["欢迎人工智能"], "en", terms, batch_size=1, stats=stats)

        assert stats["cache_hits"] == 0, "术语行不应命中缓存（术语改动后必须重译）"
        assert out == ["T:欢迎AI"]

    def test_plain_lines_still_hit_cache(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config.cache, "db_path", str(tmp_path / "c.db"))
        monkeypatch.setattr(pipeline, "_call_llm", lambda text, target, **k: "X")

        pipeline.translate(["普通句子"], "en", {}, batch_size=1)
        stats: dict = {}
        out = pipeline.translate(["普通句子"], "en", {}, batch_size=1, stats=stats)

        assert stats["cache_hits"] == 1
        assert out == ["X"]
