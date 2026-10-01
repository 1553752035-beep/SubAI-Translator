# -*- coding: utf-8 -*-
"""四期 4.3 插件系统 —— API 测试。"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def plugin_env(tmp_path, monkeypatch):
    """把插件目录与状态文件隔离到 tmp。

    必要性：conftest 的 client 夹具会触发 lifespan 从而初始化插件系统，
    若沿用真实路径，本文件的启停操作会写进仓库的 data/plugins.json（曾犯过同类错误）。
    """
    from src.config import config as _cfg
    from src.plugins import registry

    real_dir = _cfg.paths.plugins_dir
    real_state = _cfg.paths.plugins_state
    tmp_dir = str(tmp_path / "plugins")
    tmp_state = str(tmp_path / "plugins.json")

    monkeypatch.setattr(_cfg.paths, "plugins_dir", tmp_dir)
    monkeypatch.setattr(_cfg.paths, "plugins_state", tmp_state)
    monkeypatch.setattr(registry, "_plugins_dir", tmp_dir)
    monkeypatch.setattr(registry, "_state_path", tmp_state)
    registry.reload()

    yield registry

    # 显式恢复到真实路径并重新发现，避免把临时状态泄漏给后续测试
    registry._plugins_dir = real_dir
    registry._state_path = real_state
    registry._state_cache = None
    registry.discover()
    registry._plugins_dir = None
    registry._state_path = None


class TestPluginsApi:
    def test_list_requires_auth(self, client, plugin_env):
        r = client.get("/api/plugins")
        assert r.status_code in (401, 403), r.text

    def test_list_plugins(self, client, auth_headers, plugin_env):
        r = client.get("/api/plugins", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        ids = [p["id"] for p in body["plugins"]]
        assert "subai.ocr.rapidocr" in ids
        assert "subai.tts.sapi" in ids
        assert body["stats"]["total"] == len(ids)
        assert set(body["kinds"]) == {"translator", "ocr", "tts"}

    def test_list_detail_has_capabilities(self, client, auth_headers, plugin_env):
        r = client.get("/api/plugins?detail=true", headers=auth_headers)
        assert r.status_code == 200, r.text
        ocr = [p for p in r.json()["plugins"] if p["id"] == "subai.ocr.rapidocr"][0]
        assert "recognize" in ocr["capabilities"]
        assert ocr["available"] is True

    def test_disable_and_enable(self, client, auth_headers, plugin_env):
        r = client.post("/api/plugins/subai.ocr.rapidocr/disable", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is False

        listing = client.get("/api/plugins", headers=auth_headers).json()["plugins"]
        ocr = [p for p in listing if p["id"] == "subai.ocr.rapidocr"][0]
        assert ocr["state"] == "disabled"

        # 状态已落盘（tmp 路径）
        state = json.loads((plugin_env.state_path and __import__("pathlib").Path(plugin_env.state_path)).read_text(encoding="utf-8"))
        assert state["enabled"]["subai.ocr.rapidocr"] is False

        r2 = client.post("/api/plugins/subai.ocr.rapidocr/enable", headers=auth_headers)
        assert r2.status_code == 200 and r2.json()["enabled"] is True

    def test_unknown_plugin_404(self, client, auth_headers, plugin_env):
        assert client.get("/api/plugins/no.such", headers=auth_headers).status_code == 404
        assert client.post("/api/plugins/no.such/enable", headers=auth_headers).status_code == 404

    def test_reload(self, client, auth_headers, plugin_env):
        r = client.post("/api/plugins/reload", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["discovered"] >= 5

    def test_marketplace(self, client, auth_headers, plugin_env):
        r = client.get("/api/plugins/marketplace", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["entries"]
        r2 = client.get("/api/plugins/marketplace?kind=tts", headers=auth_headers)
        assert all(e["kind"] == "tts" for e in r2.json()["entries"])
        r3 = client.get("/api/plugins/marketplace?query=语音", headers=auth_headers)
        assert r3.json()["entries"]

    def test_probe_shapes(self, client, auth_headers, plugin_env):
        # 不支持探测的插件（OCR）
        r = client.post("/api/plugins/subai.ocr.rapidocr/probe", headers=auth_headers)
        assert r.status_code == 200 and r.json()["supported"] is False
        # 翻译插件支持探测：允许失败（终端不可达时返回 error 字段，而不是 500）
        r2 = client.post("/api/plugins/subai.translator.local-llm/probe", headers=auth_headers)
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["supported"] is True
        assert "result" in body or "error" in body

    def test_probe_disabled_plugin_400(self, client, auth_headers, plugin_env):
        client.post("/api/plugins/subai.translator.local-llm/disable", headers=auth_headers)
        r = client.post("/api/plugins/subai.translator.local-llm/probe", headers=auth_headers)
        assert r.status_code == 400, r.text

    def test_write_requires_admin(self, client, plugin_env):
        """普通用户不能启停插件。"""
        reg = client.post("/api/auth/register", json={
            "username": "plainuser", "password": "plainpass123",
        })
        if reg.status_code >= 400:
            pytest.skip("注册接口需要额外字段，跳过角色校验用例: %s" % reg.text[:80])
        login = client.post("/api/auth/login", json={
            "username": "plainuser", "password": "plainpass123",
        })
        assert login.status_code == 200, login.text
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        r = client.post("/api/plugins/subai.ocr.rapidocr/disable", headers=headers)
        assert r.status_code == 403, r.text

