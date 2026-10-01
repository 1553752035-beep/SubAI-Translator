# -*- coding: utf-8 -*-
"""四期 4.5 开放平台 —— API 密钥与 Webhook 单元测试。"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.openapi.keys import ApiKeyManager
from src.openapi.webhook import EVENTS, WebhookManager, sign, verify


def run(coro):
    """在同步测试里跑协程（不引入 pytest-asyncio 依赖）。"""
    return asyncio.run(coro)


@pytest.fixture
def keys(tmp_path):
    return ApiKeyManager(db_path=str(tmp_path / "openapi.db"))


@pytest.fixture
def hooks(tmp_path, monkeypatch):
    from src.config import config as _cfg
    monkeypatch.setattr(_cfg.openapi, "webhook_max_attempts", 4)
    monkeypatch.setattr(_cfg.openapi, "webhook_timeout", 5.0)
    monkeypatch.setattr(_cfg.openapi, "webhook_backoff", 0.05)   # 测试要快
    return WebhookManager(db_path=str(tmp_path / "openapi.db"))


def start_server(fail_times: int = 0, always_fail: bool = False):
    """起一个本地回调服务：前 fail_times 次返回 500，之后返回 200。"""
    state = {"attempts": 0, "signatures": [], "bodies": [], "events": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            state["attempts"] += 1
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            state["bodies"].append(body)
            state["signatures"].append(self.headers.get("X-SubAI-Signature"))
            state["events"].append(self.headers.get("X-SubAI-Event"))
            if always_fail or state["attempts"] <= fail_times:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b"fail")
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):  # 静音
            return

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:%d/hook" % srv.server_address[1]
    return srv, state, url


class TestApiKeys:
    def test_create_verify_and_stats(self, keys):
        async def scenario():
            secret, key = await keys.create("测试密钥", scopes=["translate"])
            assert secret.startswith("subai_"), secret
            assert key.key_id.startswith("key_")
            # 明文只在创建时返回；库里只有哈希
            con = sqlite3.connect(keys.db_path)
            rows = con.execute("SELECT key_hash FROM api_keys").fetchall()
            con.close()
            assert secret not in {r[0] for r in rows}
            assert len(rows[0][0]) == 64   # sha256 hex
            # 校验通过
            found = await keys.verify(secret)
            assert found is not None and found.key_id == key.key_id
            assert found.scopes == ["translate"]
            # 错误密钥不通过
            assert await keys.verify("subai_wrong") is None
            assert await keys.verify("") is None
            # 调用统计
            await keys.record_call(key.key_id, ok=True)
            await keys.record_call(key.key_id, ok=True)
            await keys.record_call(key.key_id, ok=False)
            got = await keys.get(key.key_id)
            assert (got.call_count, got.error_count) == (3, 1)
            assert got.success_rate == pytest.approx(0.6667, abs=1e-3)
            assert got.last_used_at is not None
            daily = await keys.daily(key_id=key.key_id)
            assert daily and daily[0]["calls"] == 3 and daily[0]["errors"] == 1
            st = await keys.stats()
            assert st["keys"] == 1 and st["calls"] == 3 and st["errors"] == 1
            return key
        run(scenario())

    def test_disable_and_revoke(self, keys):
        async def scenario():
            secret, key = await keys.create("待吊销")
            assert (await keys.verify(secret)) is not None
            assert await keys.set_enabled(key.key_id, False) is True
            assert (await keys.verify(secret)) is None      # 停用即不可用
            assert await keys.set_enabled(key.key_id, True) is True
            assert (await keys.verify(secret)) is not None
            assert await keys.revoke(key.key_id) is True
            assert (await keys.verify(secret)) is None      # 吊销后永久失效
            listed = await keys.list()
            assert listed and listed[0].enabled is False
        run(scenario())

    def test_to_dict_masks_prefix(self, keys):
        async def scenario():
            secret, key = await keys.create("脱敏")
            d = key.to_dict()
            assert d["prefix"].endswith("****")
            assert secret not in json.dumps(d)
            return d
        run(scenario())


class TestWebhookSignature:
    def test_sign_and_verify(self):
        body = b'{"a": 1}'
        sig = sign("s3cret", body)
        assert verify("s3cret", body, sig) is True
        assert verify("s3cret", body, "sha256=" + sig) is True
        assert verify("s3cret", body, "deadbeef") is False
        assert verify("other", body, sig) is False
        assert verify("s3cret", body, "") is False


class TestWebhookDelivery:
    def test_retry_until_success_and_signature(self, hooks):
        srv, state, url = start_server(fail_times=2)
        try:
            async def scenario():
                hook, secret = await hooks.add(url, events=["task.completed"])
                ids = await hooks.dispatch("task.completed", {"task_id": "t1"}, background=False)
                assert len(ids) == 1
                result = await hooks.deliver(ids[0]) if False else None
                return hook, secret, ids, result
            hook, secret, ids, _ = run(scenario())
            # dispatch(background=False) 已同步投递完毕
            deliveries = run(hooks.deliveries(hook.webhook_id))
            assert len(deliveries) == 1
            d = deliveries[0]
            assert d["status"] == "success", d
            assert d["attempts"] == 3, d          # 前两次 500，第三次成功
            assert state["attempts"] == 3
            # 签名必须能被接收方用同一密钥验证
            assert verify(secret, state["bodies"][-1], state["signatures"][-1]) is True
            assert state["events"][-1] == "task.completed"
            payload = json.loads(state["bodies"][-1])
            assert payload["event"] == "task.completed"
            assert payload["data"]["task_id"] == "t1"
            st = run(hooks.stats())
            assert st["deliveries"] == 1 and st["success"] == 1
            assert st["success_rate"] == 1.0
        finally:
            srv.shutdown()

    def test_failure_after_all_attempts(self, hooks):
        srv, state, url = start_server(always_fail=True)
        try:
            async def scenario():
                hook, _ = await hooks.add(url, events=["task.failed"])
                await hooks.dispatch("task.failed", {"task_id": "t2"}, background=False)
                deliveries = await hooks.deliveries(hook.webhook_id)
                stats = await hooks.stats()
                return hook, deliveries, stats
            hook, deliveries, stats = run(scenario())
            assert deliveries[0]["status"] == "failed"
            assert deliveries[0]["attempts"] == 4      # 用满重试次数
            assert state["attempts"] == 4
            assert stats["failed"] == 1 and stats["success_rate"] == 0.0
        finally:
            srv.shutdown()

    def test_event_filtering_and_lifecycle(self, hooks):
        srv, state, url = start_server()
        try:
            async def scenario():
                hook, _ = await hooks.add(url, events=["task.completed"])
                # 未订阅的事件不投递
                assert await hooks.dispatch("task.failed", {}, background=False) == []
                assert await hooks.dispatch("task.completed", {"ok": True}, background=False) != []
                listed = await hooks.list()
                assert listed and listed[0].webhook_id == hook.webhook_id
                # 内部持有真实密钥（签名要用），对外 to_dict 才脱敏
                assert listed[0].secret and not listed[0].secret.endswith("****")
                assert listed[0].to_dict()["secret"].endswith("****")
                assert await hooks.set_enabled(hook.webhook_id, False) is True
                assert await hooks.dispatch("task.completed", {}, background=False) == []
                assert await hooks.remove(hook.webhook_id) is True
                assert await hooks.get(hook.webhook_id) is None
                assert await hooks.deliveries(hook.webhook_id) == []   # 级联清理
                return True
            assert run(scenario()) is True
            assert state["attempts"] == 1
        finally:
            srv.shutdown()

    def test_reject_bad_url(self, hooks):
        async def scenario():
            with pytest.raises(ValueError):
                await hooks.add("ftp://example.com/hook")
            with pytest.raises(ValueError):
                await hooks.add("")
        run(scenario())

    def test_events_constant(self):
        assert "task.completed" in EVENTS and "task.failed" in EVENTS

