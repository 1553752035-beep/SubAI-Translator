# -*- coding: utf-8 -*-
"""四期深化：Webhook 持久化兜底（重启后重投）测试。"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.openapi.webhook import WebhookManager


def run(coro):
    return asyncio.run(coro)


def start_server(fail_first: int = 0):
    state = {"attempts": 0, "bodies": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            state["attempts"] += 1
            length = int(self.headers.get("Content-Length") or 0)
            state["bodies"].append(self.rfile.read(length))
            code = 500 if state["attempts"] <= fail_first else 200
            self.send_response(code)
            self.end_headers()

        def log_message(self, *args):
            return

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, state, "http://127.0.0.1:%d/hook" % srv.server_address[1]


@pytest.fixture
def manager(tmp_path, monkeypatch):
    from src.config import config as _cfg
    monkeypatch.setattr(_cfg.openapi, "webhook_max_attempts", 3)
    monkeypatch.setattr(_cfg.openapi, "webhook_backoff", 0.02)
    monkeypatch.setattr(_cfg.openapi, "webhook_timeout", 5.0)
    return WebhookManager(db_path=str(tmp_path / "openapi.db"))


class TestDurableQueue:
    def test_resume_pending_redelivers(self, manager):
        srv, state, url = start_server()
        try:
            async def scenario():
                hook, _ = await manager.add(url, events=["task.completed"])
                # 模拟"进程退出前没投完"：只建记录不投递
                did = await manager._create_delivery(hook.webhook_id, "task.completed", {"task_id": "x"})
                before = await manager.deliveries(hook.webhook_id)
                assert before[0]["status"] == "pending"
                # 立刻恢复（older_than=0 让刚创建的也能被捞起来）
                n = await manager.resume_pending(older_than=0.0)
                assert n == 1
                await manager.wait_pending(timeout=10)
                after = await manager.deliveries(hook.webhook_id)
                assert after[0]["status"] == "success", after
                stats = await manager.stats()
                assert stats["stale_pending"] == 0
                return did
            run(scenario())
            assert state["attempts"] == 1
            body = json.loads(state["bodies"][0])
            assert body["data"]["task_id"] == "x"
        finally:
            srv.shutdown()

    def test_attempt_budget_persists_across_restart(self, manager):
        """重试预算跨重启累计：不允许每次重启都白送 3 次尝试。"""
        srv, state, url = start_server(fail_first=99)   # 永远失败
        try:
            async def scenario():
                hook, _ = await manager.add(url, events=["task.completed"])
                await manager.dispatch("task.completed", {"task_id": "t"}, background=False)
                first = (await manager.deliveries(hook.webhook_id))[0]
                assert first["status"] == "failed" and first["attempts"] == 3
                # 模拟进程重启后巡检把它当成 pending 捞起来
                con = sqlite3.connect(manager.db_path)
                con.execute("UPDATE webhook_deliveries SET status = 'pending' WHERE delivery_id = ?",
                            (first["delivery_id"],))
                con.commit(); con.close()
                resumed = await manager.resume_pending(older_than=0.0)
                await manager.wait_pending(timeout=10)
                second = (await manager.deliveries(hook.webhook_id))[0]
                return first, resumed, second
            first, resumed, second = run(scenario())
            # 预算已用尽 -> 不会被再次投递（resume 时已被 attempts < max 过滤掉）
            assert resumed == 0
            assert second["attempts"] == first["attempts"] == 3
            assert state["attempts"] == 3          # 服务端总共只收到 3 次，没有白送
        finally:
            srv.shutdown()

    def test_manual_retry_resets_budget(self, manager):
        srv, state, url = start_server(fail_first=1)
        try:
            async def scenario():
                hook, _ = await manager.add(url, events=["task.completed"])
                await manager.dispatch("task.completed", {"task_id": "m"}, background=False)
                delivered = (await manager.deliveries(hook.webhook_id))[0]
                assert delivered["status"] == "success" and delivered["attempts"] == 2
                result = await manager.retry_delivery(delivered["delivery_id"])
                assert result["status"] == "success"
                rows = await manager.deliveries(hook.webhook_id)
                assert rows[0]["attempts"] == 1     # 手动重投会重置预算
                with pytest.raises(KeyError):
                    await manager.retry_delivery("dl_missing")
                return True
            assert run(scenario()) is True
            assert state["attempts"] == 3
        finally:
            srv.shutdown()

    def test_disabled_webhook_not_resumed(self, manager):
        srv, state, url = start_server()
        try:
            async def scenario():
                hook, _ = await manager.add(url, events=["task.completed"])
                await manager._create_delivery(hook.webhook_id, "task.completed", {})
                await manager.set_enabled(hook.webhook_id, False)
                return await manager.resume_pending(older_than=0.0)
            assert run(scenario()) == 0
            assert state["attempts"] == 0
        finally:
            srv.shutdown()
