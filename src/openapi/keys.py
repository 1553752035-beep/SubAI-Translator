# -*- coding: utf-8 -*-
"""四期 4.5 开放平台：API 密钥管理与调用统计。

安全约定（重要）
1. **只存哈希**：数据库里保存 sha256(secret)，明文只在创建时返回一次；
   即使库被拿走也无法还原密钥。
2. 校验用 **constant-time 比较**（hmac.compare_digest），避免时序侧信道。
3. 密钥带固定前缀（默认 subai_），日志/界面只展示前缀，便于脱敏。
"""
from __future__ import annotations

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

from src.config import config

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS api_keys (
    key_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    scopes TEXT DEFAULT '[]',
    user_id TEXT,
    created_at REAL NOT NULL,
    last_used_at REAL,
    enabled INTEGER DEFAULT 1,
    call_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);

CREATE TABLE IF NOT EXISTS api_key_daily (
    key_id TEXT NOT NULL,
    day TEXT NOT NULL,
    calls INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    PRIMARY KEY (key_id, day)
);
"""


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _today() -> str:
    return time.strftime("%Y-%m-%d")


@dataclass
class ApiKey:
    key_id: str
    name: str
    prefix: str
    scopes: list
    user_id: Optional[str]
    created_at: float
    last_used_at: Optional[float]
    enabled: bool
    call_count: int
    error_count: int

    @property
    def success_rate(self) -> float:
        if self.call_count <= 0:
            return 1.0
        return round((self.call_count - self.error_count) / self.call_count, 4)

    def to_dict(self, masked: bool = True) -> dict:
        return {
            "key_id": self.key_id,
            "name": self.name,
            "prefix": (self.prefix + "****") if masked else self.prefix,
            "scopes": list(self.scopes),
            "user_id": self.user_id,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "enabled": self.enabled,
            "call_count": self.call_count,
            "error_count": self.error_count,
            "success_rate": self.success_rate,
        }


class ApiKeyManager:
    """API 密钥管理器（aiosqlite，按需建表）。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or config.paths.resolve(config.paths.openapi_db)
        self._ready = False

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

    async def create(self, name: str, scopes: Optional[list] = None,
                     user_id: Optional[str] = None) -> tuple:
        """创建密钥，返回 (明文密钥, ApiKey)。明文只在这里出现一次。"""
        await self._ensure()
        raw = secrets.token_urlsafe(int(config.openapi.key_bytes))
        secret = "%s%s" % (config.openapi.key_prefix, raw)
        key_id = "key_" + uuid.uuid4().hex[:12]
        now = time.time()
        scopes = list(scopes or ["translate", "tasks", "languages"])
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO api_keys (key_id, name, prefix, key_hash, scopes, user_id, created_at, enabled)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                (key_id, name, secret[: len(config.openapi.key_prefix) + 8], _hash(secret),
                 json.dumps(scopes, ensure_ascii=False), user_id, now),
            )
            await db.commit()
        return secret, ApiKey(key_id, name, secret[: len(config.openapi.key_prefix) + 8],
                              scopes, user_id, now, None, True, 0, 0)

    async def verify(self, token: str) -> Optional[ApiKey]:
        """校验密钥；命中则返回记录（不修改统计，由 record_call 负责）。"""
        if not token:
            return None
        await self._ensure()
        digest = _hash(token)
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM api_keys WHERE enabled = 1") as cur:
                rows = await cur.fetchall()
        for row in rows:
            if hmac.compare_digest(row["key_hash"], digest):
                return self._row_to_key(row)
        return None

    async def record_call(self, key_id: str, ok: bool = True) -> None:
        """记录一次调用（总数/错误数/最后使用时间 + 当日统计）。"""
        await self._ensure()
        now = time.time()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE api_keys SET call_count = call_count + 1, error_count = error_count + ?,"
                " last_used_at = ? WHERE key_id = ?",
                (0 if ok else 1, now, key_id),
            )
            await db.execute(
                "INSERT INTO api_key_daily (key_id, day, calls, errors) VALUES (?, ?, 1, ?)"
                " ON CONFLICT(key_id, day) DO UPDATE SET calls = calls + 1, errors = errors + ?",
                (key_id, _today(), 0 if ok else 1, 0 if ok else 1),
            )
            await db.commit()

    async def list(self) -> list:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM api_keys ORDER BY created_at DESC") as cur:
                rows = await cur.fetchall()
        return [self._row_to_key(row) for row in rows]

    async def get(self, key_id: str) -> Optional[ApiKey]:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM api_keys WHERE key_id = ?", (key_id,)) as cur:
                row = await cur.fetchone()
        return self._row_to_key(row) if row else None

    async def set_enabled(self, key_id: str, enabled: bool) -> bool:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute("UPDATE api_keys SET enabled = ? WHERE key_id = ?",
                                   (1 if enabled else 0, key_id))
            await db.commit()
        return bool(cur.rowcount)

    async def revoke(self, key_id: str) -> bool:
        """吊销 = 停用 + 打散哈希（不可恢复，语义比"停用"更强）。"""
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "UPDATE api_keys SET enabled = 0, key_hash = ? WHERE key_id = ?",
                (_hash("revoked:" + key_id + str(time.time())), key_id),
            )
            await db.commit()
        return bool(cur.rowcount)

    async def daily(self, key_id: Optional[str] = None, days: int = 30) -> list:
        await self._ensure()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if key_id:
                sql = "SELECT * FROM api_key_daily WHERE key_id = ? ORDER BY day DESC LIMIT ?"
                args = (key_id, days)
            else:
                sql = ("SELECT day, SUM(calls) AS calls, SUM(errors) AS errors FROM api_key_daily"
                       " GROUP BY day ORDER BY day DESC LIMIT ?")
                args = (days,)
            async with db.execute(sql, args) as cur:
                rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def stats(self) -> dict:
        keys = await self.list()
        return {
            "keys": len(keys),
            "enabled": sum(1 for k in keys if k.enabled),
            "calls": sum(k.call_count for k in keys),
            "errors": sum(k.error_count for k in keys),
            "success_rate": round(
                (sum(k.call_count for k in keys) - sum(k.error_count for k in keys))
                / max(sum(k.call_count for k in keys), 1), 4) if keys else 1.0,
        }

    @staticmethod
    def _row_to_key(row) -> ApiKey:
        try:
            scopes = json.loads(row["scopes"] or "[]")
        except Exception:  # noqa: BLE001
            scopes = []
        return ApiKey(
            key_id=row["key_id"],
            name=row["name"],
            prefix=row["prefix"],
            scopes=scopes,
            user_id=row["user_id"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            enabled=bool(row["enabled"]),
            call_count=row["call_count"] or 0,
            error_count=row["error_count"] or 0,
        )


_manager: Optional[ApiKeyManager] = None


def get_api_key_manager() -> ApiKeyManager:
    global _manager
    if _manager is None:
        _manager = ApiKeyManager()
    return _manager
