# -*- coding: utf-8 -*-
"""
SubAI Translator —— 翻译端点连通性测试
========================================

覆盖 src/llm.py 的 test_endpoint：未配置、缺 Key、/models 命中、
/models 失败后回退 chat、非法模式。全部使用 mock，不产生真实网络请求。
"""
from __future__ import annotations

import pytest

from src import llm as llm_module
from src.config import config


class TestTestEndpoint:
    def test_missing_url_is_unconfigured(self, monkeypatch):
        monkeypatch.setattr(config.llm, "local_url", "")
        r = llm_module.test_endpoint("local")
        assert r["configured"] is False
        assert r["reachable"] is False
        assert "未配置" in r["detail"]

    def test_cloud_without_key_is_unconfigured(self, monkeypatch):
        monkeypatch.setattr(config.llm, "cloud_url", "https://example.invalid/v1/chat/completions")
        monkeypatch.setattr(config.llm, "cloud_api_key", "")
        r = llm_module.test_endpoint("cloud")
        assert r["configured"] is False
        assert "API Key" in r["detail"]

    def test_reachable_via_models(self, monkeypatch):
        class Ok:
            status_code = 200

        monkeypatch.setattr(config.llm, "local_url", "http://127.0.0.1:9/v1/chat/completions")
        monkeypatch.setattr(llm_module.httpx, "get", lambda *a, **k: Ok())
        r = llm_module.test_endpoint("local", chat_fallback=False)
        assert r["reachable"] is True
        assert r["method"] == "models"
        assert r["elapsed_ms"] >= 0

    def test_falls_back_to_chat_when_models_missing(self, monkeypatch):
        class NotFound:
            status_code = 404

        class Ok:
            status_code = 200

        monkeypatch.setattr(config.llm, "local_url", "http://127.0.0.1:9/v1/chat/completions")
        monkeypatch.setattr(llm_module.httpx, "get", lambda *a, **k: NotFound())
        monkeypatch.setattr(llm_module.httpx, "post", lambda *a, **k: Ok())
        r = llm_module.test_endpoint("local")
        assert r["reachable"] is True
        assert r["method"] == "chat"

    def test_both_probes_fail_reports_both(self, monkeypatch):
        def boom(*a, **k):
            raise ConnectionError("refused")

        monkeypatch.setattr(config.llm, "local_url", "http://127.0.0.1:9/v1/chat/completions")
        monkeypatch.setattr(llm_module.httpx, "get", boom)
        monkeypatch.setattr(llm_module.httpx, "post", boom)
        r = llm_module.test_endpoint("local")
        assert r["reachable"] is False
        assert "models:" in r["detail"] and "chat:" in r["detail"]

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            llm_module.test_endpoint("bogus")
