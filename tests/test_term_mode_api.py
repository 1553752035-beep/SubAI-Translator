# -*- coding: utf-8 -*-
"""术语模式设置接口测试（GET /api/translation/settings、POST /api/translation/term-mode）"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_API_TESTS"),
    reason="需要 RUN_API_TESTS=1 才执行 API 集成测试",
)


class TestTranslationSettings:
    def test_requires_auth(self, client):
        assert client.get("/api/translation/settings").status_code == 401

    def test_returns_current_mode_and_options(self, client, auth_headers, monkeypatch):
        from src.config import config
        monkeypatch.setattr(config.term, "mode", "strict")
        r = client.get("/api/translation/settings", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["term_mode"] == "strict"
        assert {o["value"] for o in body["available"]} == {"strict", "hint"}
        assert all(o["label"] and o["description"] for o in body["available"])

    def test_switch_mode_and_rejects_invalid(self, client, auth_headers, monkeypatch):
        from src.config import config
        # 该端点会 persist_env 写 .env：测试里必须拦截，
        # 否则会污染开发者本机配置（且让后续测试在错误的默认模式下运行）。
        import src.api.server as server_mod
        monkeypatch.setattr(server_mod, "persist_env", lambda updates: None)
        monkeypatch.setattr(config.term, "mode", "strict")

        bad = client.post("/api/translation/term-mode", headers=auth_headers, json={"mode": "bogus"})
        assert bad.status_code == 400

        ok = client.post("/api/translation/term-mode", headers=auth_headers, json={"mode": "hint"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["term_mode"] == "hint"
        # 立即生效：再读设置应为 hint
        assert client.get("/api/translation/settings", headers=auth_headers).json()["term_mode"] == "hint"

    def test_switch_requires_admin(self, client):
        client.post("/api/auth/register", json={"username": "normal-user", "password": "pass123"})
        r = client.post("/api/auth/login", json={"username": "normal-user", "password": "pass123"})
        headers = {"Authorization": "Bearer " + r.json()["access_token"]}
        resp = client.post("/api/translation/term-mode", headers=headers, json={"mode": "hint"})
        assert resp.status_code == 403
        # 普通用户可以读设置
        assert client.get("/api/translation/settings", headers=headers).status_code == 200
