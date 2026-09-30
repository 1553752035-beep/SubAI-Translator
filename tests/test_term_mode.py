# -*- coding: utf-8 -*-
"""
SubAI Translator —— 术语模式测试（strict 强制锁定 / hint 软提示）
===================================================================

strict：占位符替换，译名强制一致（术语作定语时句式可能略生硬）；
hint  ：不改写原文，只把命中的术语作为"必须使用"的要求写进提示词。

两者都必须：整行精确命中直接采用术语译文、命中术语的行不读写缓存。
"""
from __future__ import annotations

import pytest

from src import pipeline
from src.config import config


TERMS = {"人工智能": "Artificial Intelligence", "视频": "video"}


class TestGlossaryHint:
    def test_empty(self):
        assert pipeline._glossary_hint({}) == ""

    def test_contains_pairs_and_longest_first(self):
        hint = pipeline._glossary_hint({"视频": "video", "人工智能": "AI"})
        assert "人工智能 = AI" in hint
        assert "视频 = video" in hint
        assert hint.index("人工智能") < hint.index("视频")     # 长词优先

    def test_default_mode_is_strict(self):
        assert config.term.mode == "strict"


class TestStrictMode:
    def test_prompt_uses_placeholder_not_glossary(self, monkeypatch):
        seen = {}

        def fake(prompt, target, **k):
            seen["prompt"] = prompt
            return "1. X"

        monkeypatch.setattr(pipeline, "_call_llm", fake)
        stats: dict = {}
        pipeline.translate(["欢迎使用人工智能"], "en", TERMS,
                           batch_size=10, use_cache=False, stats=stats, term_mode="strict")

        assert "[[T0]]" in seen["prompt"]
        assert "Required terminology" not in seen["prompt"]
        assert stats["terms"] == 1


class TestHintMode:
    def test_prompt_keeps_source_and_adds_glossary(self, monkeypatch):
        seen = {}

        def fake(prompt, target, **k):
            seen["prompt"] = prompt
            return "1. Welcome to Artificial Intelligence"

        monkeypatch.setattr(pipeline, "_call_llm", fake)
        stats: dict = {}
        out = pipeline.translate(["欢迎使用人工智能"], "en", TERMS,
                                 batch_size=10, use_cache=False, stats=stats, term_mode="hint")

        assert "欢迎使用人工智能" in seen["prompt"], "软提示不应改写原文"
        assert "[[T0]]" not in seen["prompt"]
        assert "Required terminology" in seen["prompt"]
        assert "人工智能 = Artificial Intelligence" in seen["prompt"]
        assert out == ["Welcome to Artificial Intelligence"]
        assert stats["terms"] == 1

    def test_only_matching_terms_are_injected(self, monkeypatch):
        seen = {}

        def fake(prompt, target, **k):
            seen["prompt"] = prompt
            return "1. hello"

        monkeypatch.setattr(pipeline, "_call_llm", fake)
        pipeline.translate(["这句只有视频"], "en", TERMS,
                           batch_size=10, use_cache=False, term_mode="hint")
        assert "视频 = video" in seen["prompt"]
        assert "人工智能" not in seen["prompt"], "未命中的术语不应出现在提示词里"

    def test_per_line_fallback_also_gets_glossary(self, monkeypatch):
        prompts = []

        def fake(prompt, target, **k):
            prompts.append(prompt)
            if "Translate each numbered" in prompt:
                return "(no numbering)"          # 强制退回逐行
            return "LINE"

        monkeypatch.setattr(pipeline, "_call_llm", fake)
        pipeline.translate(["含人工智能的句子"], "en", TERMS,
                           batch_size=1, use_cache=False, term_mode="hint")
        assert any("Required terminology" in p and "人工智能" in p for p in prompts)

    def test_exact_line_match_still_short_circuits(self, monkeypatch):
        calls = {"n": 0}

        def fake(prompt, target, **k):
            calls["n"] += 1
            return "X"

        monkeypatch.setattr(pipeline, "_call_llm", fake)
        stats: dict = {}
        out = pipeline.translate(["人工智能"], "en", TERMS,
                                 batch_size=10, use_cache=False, stats=stats, term_mode="hint")
        assert out == ["Artificial Intelligence"]
        assert calls["n"] == 0
        assert stats["terms"] == 1


class TestTermCacheIsolationInHintMode:
    def test_term_lines_do_not_use_cache(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config.cache, "db_path", str(tmp_path / "c.db"))
        monkeypatch.setattr(pipeline, "_call_llm", lambda text, target, **k: "OUT")

        pipeline.translate(["含人工智能的句子"], "en", TERMS, batch_size=1, term_mode="hint")
        stats: dict = {}
        pipeline.translate(["含人工智能的句子"], "en", TERMS, batch_size=1,
                           stats=stats, term_mode="hint")
        assert stats["cache_hits"] == 0, "软提示模式下术语行同样不应命中缓存"


class TestUnknownModeFallsBack:
    def test_unknown_mode_behaves_like_strict(self, monkeypatch):
        seen = {}

        def fake(prompt, target, **k):
            seen["prompt"] = prompt
            return "1. X"

        monkeypatch.setattr(pipeline, "_call_llm", fake)
        pipeline.translate(["欢迎使用人工智能"], "en", TERMS,
                           batch_size=10, use_cache=False, term_mode="bogus")
        assert "[[T0]]" in seen["prompt"]
