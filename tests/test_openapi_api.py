# -*- coding: utf-8 -*-
"""四期 4.5 开放平台 —— API 测试（密钥、开放 API、Webhook 管理）。"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.fixture
def openapi_env(tmp_path, monkeypatch):
    """把开放平台数据库隔离到 tmp，并重置管理器单例。

    必要性：conftest 的 client 夹具会触发 lifespan，若沿用真实路径，
    测试会在仓库 data/openapi.db 里留下密钥与投递记录（同类错误犯过一次）。
    """
    from src.config import config as _cfg
    from src.openapi import keys as keys_mod
    from src.openapi import webhook as wh_mod

    monkeypatch.setattr(_cfg.paths, "openapi_db", str(tmp_path / "openapi.db"))
    monkeypatch.setattr(_cfg.openapi, "webhook_backoff", 0.05)
    monkeypatch.setattr(_cfg.openapi, "webhook_max_attempts", 3)
    monkeypatch.setattr(keys_mod, "_manager", None)
    monkeypatch.setattr(wh_mod, "_manager", None)
    yield
    keys_mod._manager = None
    wh_mod._manager = None


def start_server(always_fail: bool = False):
    state = {"attempts": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            state["attempts"] += 1
            length = int(self.headers.get("Content-Length") or 0)
            self.rfile.read(length)
            self.send_response(500 if always_fail else 200)
            self.end_headers()

        def log_message(self, *args):
            return

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state, "http://127.0.0.1:%d/hook" % srv.server_address[1]


class TestApiKeyEndpoints:
    def test_admin_required(self, client, auth_headers, openapi_env):
        assert client.get("/api/openapi/keys").status_code in (401, 403)

    def test_create_list_revoke(self, client, auth_headers, openapi_env):
        r = client.post("/api/openapi/keys", headers=auth_headers,
                        json={"name": "第三方集成", "scopes": ["languages", "tasks"]})
        assert r.status_code == 200, r.text
        body = r.json()
        secret = body["secret"]
        key_id = body["key"]["key_id"]
        assert secret.startswith("subai_") and "notice" in body

        listed = client.get("/api/openapi/keys", headers=auth_headers).json()
        assert listed["keys"][0]["prefix"].endswith("****")
        assert secret not in str(listed)

        # 开放 API 用该密钥可访问 languages（有权限）
        ok = client.get("/api/open/v1/languages", headers={"X-API-Key": secret})
        assert ok.status_code == 200, ok.text
        # 但没有 translate 权限
        denied = client.post("/api/open/v1/translate", headers={"X-API-Key": secret},
                             json={"texts": ["hi"], "target": "zh"})
        assert denied.status_code == 403, denied.text

        # 调用统计已记一笔
        usage = client.get("/api/openapi/usage", headers=auth_headers).json()["daily"]
        assert usage and usage[0]["calls"] >= 1

        assert client.delete("/api/openapi/keys/" + key_id, headers=auth_headers).status_code == 200
        assert client.get("/api/open/v1/me", headers={"X-API-Key": secret}).status_code == 401

    def test_unknown_key_rejected(self, client, openapi_env):
        assert client.get("/api/open/v1/me", headers={"X-API-Key": "subai_nope"}).status_code == 401
        assert client.get("/api/open/v1/me").status_code == 401

    def test_usage_on_missing_task_counts_error(self, client, auth_headers, openapi_env):
        secret = client.post("/api/openapi/keys", headers=auth_headers,
                             json={"name": "任务查询", "scopes": ["tasks"]}).json()["secret"]
        r = client.get("/api/open/v1/tasks/does-not-exist", headers={"X-API-Key": secret})
        assert r.status_code == 404
        keys = client.get("/api/openapi/keys", headers=auth_headers).json()["keys"]
        assert keys[0]["call_count"] == 1 and keys[0]["error_count"] == 1


class TestWebhookEndpoints:
    def test_admin_required(self, client, auth_headers, openapi_env):
        assert client.get("/api/openapi/webhooks").status_code in (401, 403)

    def test_create_bad_url(self, client, auth_headers, openapi_env):
        r = client.post("/api/openapi/webhooks", headers=auth_headers, json={"url": "ftp://x"})
        assert r.status_code == 400, r.text

    def test_create_test_and_deliveries(self, client, auth_headers, openapi_env):
        srv, state, url = start_server()
        try:
            created = client.post("/api/openapi/webhooks", headers=auth_headers,
                                  json={"url": url, "events": ["webhook.test", "task.completed"]})
            assert created.status_code == 200, created.text
            hook = created.json()["webhook"]
            wid = hook["webhook_id"]
            assert hook["secret"] and created.json()["secret"] == hook["secret"]

            tested = client.post("/api/openapi/webhooks/%s/test" % wid, headers=auth_headers)
            assert tested.status_code == 200, tested.text
            deliveries = tested.json()["deliveries"]
            assert deliveries and deliveries[0]["status"] == "success", deliveries
            assert deliveries[0]["attempts"] == 1
            assert state["attempts"] == 1

            listed = client.get("/api/openapi/webhooks", headers=auth_headers).json()
            assert listed["webhooks"][0]["webhook_id"] == wid
            assert listed["webhooks"][0]["secret"].endswith("****")   # 列表脱敏
            assert listed["stats"]["success"] >= 1

            detail = client.get("/api/openapi/webhooks/%s/deliveries" % wid,
                                headers=auth_headers).json()["deliveries"]
            assert detail and detail[0]["event"] == "webhook.test"

            assert client.post("/api/openapi/webhooks/%s/disable" % wid,
                               headers=auth_headers).json()["enabled"] is False
            assert client.delete("/api/openapi/webhooks/%s" % wid,
                                 headers=auth_headers).status_code == 200
            assert client.get("/api/openapi/webhooks/%s/deliveries" % wid,
                              headers=auth_headers).status_code == 200
        finally:
            srv.shutdown()

    def test_stats_endpoint(self, client, auth_headers, openapi_env):
        r = client.get("/api/openapi/stats", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "keys" in body and "webhooks" in body and "task.completed" in body["events"]

