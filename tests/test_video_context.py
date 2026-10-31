# -*- coding: utf-8 -*-
"""五期 P0：翻译前语境摘要 —— 采样预算 / key 联动 / 降级 / API 契约"""
import json
import pytest
import src.pipeline as pl


def _long_texts(n=60):
    return ["这是语音识别测试，欢迎使用人工智能视频字幕翻译软件，今天天气很好。"] * n


def test_sample_budget_respects_max_chars():
    """采样按 max_chars 分配预算（不是先按比例再截断）：输出不超预算，且首尾都在。"""
    text = "开头标记。" + "".join("中间内容%d。" % i for i in range(3000)) + "结尾标记。"
    out = pl._sample_text(text, 2000)
    assert len(out) <= 2000 + 200, "采样超预算，实际 %d" % len(out)
    assert out.startswith("开头标记。"), "丢了开头"
    assert out.endswith("结尾标记。"), "丢了结尾"
    assert "…" in out, "没有采样分隔符"


def test_sample_short_text_untouched():
    assert pl._sample_text("短文本。", 2000) == "短文本。"


def test_key_changes_when_summary_changes(monkeypatch):
    """摘要内容变（tone / terms）→ key 必须变，否则缓存会继续命中旧译文。"""
    texts = _long_texts()
    keys = []
    for payload in (
        {"content_type": "游戏解说", "tone": "激情", "speakers": ["威龙"], "terms": []},
        {"content_type": "游戏解说", "tone": "平静", "speakers": ["威龙"], "terms": []},
        {"content_type": "游戏解说", "tone": "激情", "speakers": ["威龙"],
         "terms": [{"src": "三角洲行动", "suggested": "Delta Force"}]},
    ):
        monkeypatch.setattr(pl, "_call_llm", lambda p, t, _d=payload: json.dumps(_d, ensure_ascii=False))
        ctx = pl.build_video_context(texts, "en")
        assert ctx is not None
        keys.append(ctx["key"])
    assert len(set(keys)) == 3, "key 未随摘要变化：%s" % keys


def test_key_stable_for_same_summary(monkeypatch):
    texts = _long_texts()
    payload = {"content_type": "教程", "tone": "平静", "speakers": [], "terms": []}
    monkeypatch.setattr(pl, "_call_llm", lambda p, t: json.dumps(payload, ensure_ascii=False))
    assert pl.build_video_context(texts, "en")["key"] == pl.build_video_context(texts, "en")["key"]


def test_short_video_skips_without_calling_llm(monkeypatch):
    calls = {"n": 0}

    def _boom(p, t):
        calls["n"] += 1
        return "{}"

    monkeypatch.setattr(pl, "_call_llm", _boom)
    assert pl.build_video_context(["短", "句"], "en") is None
    assert calls["n"] == 0, "短片不应调用 LLM"


def test_llm_failure_degrades(monkeypatch):
    def _boom(p, t):
        raise RuntimeError("timeout")

    monkeypatch.setattr(pl, "_call_llm", _boom)
    assert pl.build_video_context(_long_texts(), "en") is None


def test_bad_json_degrades(monkeypatch):
    monkeypatch.setattr(pl, "_call_llm", lambda p, t: "抱歉我无法完成")
    assert pl.build_video_context(_long_texts(), "en") is None


def test_task_response_model_has_context():
    """API 契约：任务响应模型必须带 context（否则摘要落库了接口也看不到）。"""
    from src.api.server import TaskStatusResponse
    assert "context" in TaskStatusResponse.model_fields
