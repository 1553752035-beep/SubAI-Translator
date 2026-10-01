# -*- coding: utf-8 -*-
"""四期 4.5 开放平台：Webhook 事件通知。

设计要点
1. **投递可追溯**：每次投递先落库（pending），成功/失败都更新状态与尝试次数，
   因此"回调成功率"是可核对的数字，而不是感觉。
2. **失败重试**：默认最多 4 次，退避 n*base 秒；只有 2xx 才算成功。
3. **签名可验证**：HMAC-SHA256 签名放在 X-SubAI-Signature，调用方用同一密钥校验，
   防止伪造回调（用法见 docs/API.md 与 SDK）。
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import aiosqlite
import httpx

from src.config import config

logger = logging.getLogger(__name__)

#: 支持的事件类型
EVENTS = ("task.completed", "task.failed", "task.cancelled", "key.created", "webhook.test")

SCHEMA = """
CREATE TABLE IF NOT EXISTS webhooks (
    webhook_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    secret TEXT NOT NULL,
    events TEXT DEFAULT '[]',
    enabled INTEGER DEFAULT 1,
    created_at REAL NOT NULL,
    last_status INTEGER,
    last_error TEXT,
    last_delivery_at REAL,
    success_count INTEGER DEFAULT 0,
    failure_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    webhook_id TEXT NOT NULL,
    event TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    http_status INTEGER,
    error TEXT,
    created_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_wh_deliveries ON webhook_deliveries(webhook_id, created_at DESC);
"""


def sign(secret: str, body: bytes) -> str:
    """计算 HMAC-SHA256 签名（十六进制）。"""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, signature: str) -> bool:
    """校验回调签名（constant-time）。"""
    if not signature:
        return False
    expected = sign(secret, body)
    got = signature.split("=", 1)[1] if signature.startswith("sha256=") else signature
    return hmac.compare_digest(expected, got)


@dataclass
class Webhook:
    webhook_id: str
    url: str
    secret: str
    events: list
    enabled: bool
    created_at: float
    last_status: Optional[int]
    last_error: Optional[str]
    last_delivery_at: Optional[float]
    success_count: int
    failure_count: int

    def to_dict(self, reveal_secret: bool = False) -> dict:
        return {
            "webhook_id": self.webhook_id,
            "url": self.url,
            "events": list(self.events),
            "enabled": self.enabled,
            "created_at": self.created_at,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "last_delivery_at": self.last_delivery_at,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "secret": self.secret if reveal_secret else (self.secret[:6] + "****"),
        }


class WebhookManager:
    """Webhook 注册与投递管理器。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or config.paths.resolve(config.paths.openapi_db)
        self._ready = False
        self._tasks: set = set()

    async def _ensure(self) -> None:
        if self._ready:
            return
        parent = os.path.dirname(os.path.abspath(self.db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA)
            await db.commit()
        self._ready = True

    # ---------------------------------------------------------------- 注册
    async def add(self, url: str, events: Optional[list] = None,
                  secret: Optional[str] = None) -> tuple:
        await self._ensure()
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("回调地址必须是 http(s) URL")
        events = [e for e in (events or list(EVENTS)) if e in EVENTS] or ["task.completed"]
        secret = secret or secrets.token_urlsafe(24)
        wid = "wh_" + uuid.uuid4().hex[:12]
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO webhooks (webhook_id, url, secret, events, enabled, created_at)"
                " VALUES (?, ?, ?, ?, 1, ?)",
                (wid, url, secret, json.dumps(events, ensure_ascii=False), now),
            )
            await db.commit()
        hook = Webhook(wid, url, secret, events, True, now, None, None, None, 0, 0)
        return hook, secret

    async def list(self) -> list:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM webhooks ORDER BY created_at DESC") as cur:
                rows = await cur.fetchall()
        return [self._row_to_hook(r) for r in rows]

    async def get(self, webhook_id: str) -> Optional[Webhook]:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM webhooks WHERE webhook_id = ?", (webhook_id,)) as cur:
                row = await cur.fetchone()
        return self._row_to_hook(row) if row else None

    async def set_enabled(self, webhook_id: str, enabled: bool) -> bool:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("UPDATE webhooks SET enabled = ? WHERE webhook_id = ?",
                                   (1 if enabled else 0, webhook_id))
            await db.commit()
        return bool(cur.rowcount)

    async def remove(self, webhook_id: str) -> bool:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("DELETE FROM webhooks WHERE webhook_id = ?", (webhook_id,))
            await db.execute("DELETE FROM webhook_deliveries WHERE webhook_id = ?", (webhook_id,))
            await db.commit()
        return bool(cur.rowcount)

    async def subscribers(self, event: str) -> list:
        return [hook for hook in await self.list() if hook.enabled and event in hook.events]

    # ---------------------------------------------------------------- 投递
    async def dispatch(self, event: str, payload: dict, background: bool = True) -> list:
        """向订阅了该事件的 Webhook 各投递一次；返回投递 id 列表。"""
        if event not in EVENTS:
            logger.warning("未知事件类型，仍按原样投递: %s", event)
        delivery_ids = []
        for hook in await self.subscribers(event):
            delivery_ids.append(await self._create_delivery(hook.webhook_id, event, payload))
        if background:
            for did in delivery_ids:
                task = asyncio.create_task(self.deliver(did))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        else:
            for did in delivery_ids:
                await self.deliver(did)
        return delivery_ids

    async def _create_delivery(self, webhook_id: str, event: str, payload: dict) -> str:
        await self._ensure()
        did = "dl_" + uuid.uuid4().hex[:12]
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO webhook_deliveries (delivery_id, webhook_id, event, payload, status, created_at)"
                " VALUES (?, ?, ?, ?, 'pending', ?)",
                (did, webhook_id, event, json.dumps(payload, ensure_ascii=False), time.time()),
            )
            await db.commit()
        return did

    async def deliver(self, delivery_id: str) -> dict:
        """执行一次投递（含重试与退避）；返回最终结果。"""
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM webhook_deliveries WHERE delivery_id = ?",
                                  (delivery_id,)) as cur:
                row = await cur.fetchone()
        if row is None:
            raise KeyError(delivery_id)
        hook = await self.get(row["webhook_id"])
        if hook is None:
            await self._finish(delivery_id, "failed", 0, 0, "Webhook 已删除")
            return {"delivery_id": delivery_id, "status": "failed", "error": "Webhook 已删除"}

        body = json.dumps({
            "event": row["event"],
            "delivery_id": delivery_id,
            "webhook_id": hook.webhook_id,
            "sent_at": time.time(),
            "data": json.loads(row["payload"] or "{}"),
        }, ensure_ascii=False).encode("utf-8")
        signature = "sha256=" + sign(hook.secret, body)
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-SubAI-Event": row["event"],
            "X-SubAI-Delivery": delivery_id,
            "X-SubAI-Signature": signature,
            "User-Agent": "SubAI-Translator-Webhook/1.0",
        }

        max_attempts = max(1, int(config.openapi.webhook_max_attempts))
        timeout = float(config.openapi.webhook_timeout)
        backoff = float(config.openapi.webhook_backoff)
        attempts = 0
        last_error = ""
        last_status = 0
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            while attempts < max_attempts:
                attempts += 1
                try:
                    resp = await client.post(hook.url, content=body, headers=headers)
                    last_status = resp.status_code
                    if 200 <= resp.status_code < 300:
                        await self._finish(delivery_id, "success", attempts, resp.status_code, "")
                        return {"delivery_id": delivery_id, "status": "success",
                                "attempts": attempts, "http_status": resp.status_code}
                    last_error = "HTTP %s" % resp.status_code
                except Exception as e:  # noqa: BLE001
                    last_error = repr(e)
                if attempts < max_attempts:
                    await asyncio.sleep(backoff * attempts)

        await self._finish(delivery_id, "failed", attempts, last_status, last_error)
        return {"delivery_id": delivery_id, "status": "failed",
                "attempts": attempts, "http_status": last_status, "error": last_error}

    async def _finish(self, delivery_id: str, status: str, attempts: int,
                      http_status: int, error: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE webhook_deliveries SET status = ?, attempts = ?, http_status = ?,"
                " error = ?, finished_at = ? WHERE delivery_id = ?",
                (status, attempts, http_status, error, time.time(), delivery_id),
            )
            col = "success_count" if status == "success" else "failure_count"
            await db.execute(
                "UPDATE webhooks SET %s = %s + 1, last_status = ?, last_error = ?,"
                " last_delivery_at = ? WHERE webhook_id = (SELECT webhook_id FROM webhook_deliveries"
                " WHERE delivery_id = ?)" % (col, col),
                (http_status, error, time.time(), delivery_id),
            )
            # 只保留最近 N 条投递记录
            limit = max(50, int(config.openapi.webhook_max_deliveries))
            await db.execute(
                "DELETE FROM webhook_deliveries WHERE delivery_id NOT IN ("
                " SELECT delivery_id FROM webhook_deliveries ORDER BY created_at DESC LIMIT ?)",
                (limit,),
            )
            await db.commit()

    async def deliveries(self, webhook_id: Optional[str] = None, limit: int = 50) -> list:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if webhook_id:
                sql = "SELECT * FROM webhook_deliveries WHERE webhook_id = ? ORDER BY created_at DESC LIMIT ?"
                args = (webhook_id, limit)
            else:
                sql = "SELECT * FROM webhook_deliveries ORDER BY created_at DESC LIMIT ?"
                args = (limit,)
            async with db.execute(sql, args) as cur:
                rows = await cur.fetchall()
        out = []
        for r in rows:
            item = dict(r)
            try:
                item["payload"] = json.loads(item.get("payload") or "{}")
            except Exception:  # noqa: BLE001
                pass
            out.append(item)
        return out

    async def stats(self) -> dict:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT status, COUNT(*) AS n FROM webhook_deliveries GROUP BY status"
            ) as cur:
                rows = await cur.fetchall()
            async with db.execute(
                "SELECT event, COUNT(*) AS n FROM webhook_deliveries GROUP BY event"
            ) as cur:
                by_event = {r["event"]: r["n"] for r in await cur.fetchall()}
        counts = {r["status"]: r["n"] for r in rows}
        success = counts.get("success", 0)
        failed = counts.get("failed", 0)
        pending = counts.get("pending", 0)
        finished = success + failed
        hooks = await self.list()
        return {
            "webhooks": len(hooks),
            "enabled": sum(1 for h in hooks if h.enabled),
            "deliveries": sum(counts.values()),
            "success": success,
            "failed": failed,
            "pending": pending,
            "success_rate": round(success / finished, 4) if finished else 1.0,
            "by_event": by_event,
        }

    async def wait_pending(self, timeout: float = 30.0) -> None:
        """等待所有后台投递结束（测试与优雅关闭用）。"""
        tasks = [t for t in list(self._tasks) if not t.done()]
        if not tasks:
            return
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout)
        except asyncio.TimeoutError:  # pragma: no cover
            logger.warning("等待 Webhook 投递超时")

    @staticmethod
    def _row_to_hook(row) -> Webhook:
        try:
            events = json.loads(row["events"] or "[]")
        except Exception:  # noqa: BLE001
            events = []
        return Webhook(
            webhook_id=row["webhook_id"],
            url=row["url"],
            secret=row["secret"],
            events=events,
            enabled=bool(row["enabled"]),
            created_at=row["created_at"],
            last_status=row["last_status"],
            last_error=row["last_error"],
            last_delivery_at=row["last_delivery_at"],
            success_count=row["success_count"] or 0,
            failure_count=row["failure_count"] or 0,
        )


_manager: Optional[WebhookManager] = None


def get_webhook_manager() -> WebhookManager:
    global _manager
    if _manager is None:
        _manager = WebhookManager()
    return _manager
