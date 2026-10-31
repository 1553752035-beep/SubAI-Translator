# -*- coding: utf-8 -*-
"""五期 P2：专有名词词表持久化（按「系列/主播」命名，供下次复用）。"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

import aiosqlite

from src.config import config


def glossary_db_path() -> str:
    return config.paths.resolve("{root}/data/glossary.db")


class GlossaryStore:
    """词表仓库：一条记录 = 一个命名词表（如「橘长的三角洲」），terms 是 JSON 数组。"""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or glossary_db_path()

    async def _connect(self) -> aiosqlite.Connection:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row
        await db.execute("""
            CREATE TABLE IF NOT EXISTS glossary_series (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                terms TEXT NOT NULL DEFAULT '[]',
                updated_at REAL NOT NULL
            )
        """)
        await db.commit()
        return db

    @staticmethod
    def _row(row) -> dict:
        try:
            terms = json.loads(row["terms"] or "[]")
        except Exception:  # noqa: BLE001
            terms = []
        return {"id": row["id"], "name": row["name"], "terms": terms,
                "updated_at": row["updated_at"]}

    async def list_all(self) -> list[dict]:
        db = await self._connect()
        try:
            cur = await db.execute("SELECT * FROM glossary_series ORDER BY updated_at DESC")
            return [self._row(r) for r in await cur.fetchall()]
        finally:
            await db.close()

    async def upsert(self, name: str, terms: list, force: bool = False) -> dict:
        """按名字新增或覆盖（名字是复用键）。

        [P1 2026-10-24] 加护栏。此方法是**整体替换**语义，一次误用就能把整张词表打回 1 条 ——
        实测发生过：往 22 条词表里「追加」一条新词，结果只剩那 1 条。
        除非显式 force=True，新条数骤降到「现有的 50% 以下」时拒绝写入，
        以免调用方把「追加」误当成合并。
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("词表名称不能为空")
        terms = terms or []
        now = time.time()
        db = await self._connect()
        try:
            if not force:
                cur0 = await db.execute(
                    "SELECT terms FROM glossary_series WHERE name = ?", (name,))
                row0 = await cur0.fetchone()
                if row0:
                    try:
                        old = json.loads(row0[0] or "[]")
                    except Exception:
                        old = []
                    if len(old) >= 4 and len(terms) < len(old) * 0.5:
                        raise ValueError(
                            "拒绝覆盖词表「%s」：现有 %d 条，本次仅写入 %d 条（骤降过半）。"
                            "若确实要整体替换，请传 force=True。" % (name, len(old), len(terms)))
            await db.execute(
                """INSERT INTO glossary_series (name, terms, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET terms = excluded.terms,
                   updated_at = excluded.updated_at""",
                (name, json.dumps(terms or [], ensure_ascii=False), now))
            await db.commit()
            cur = await db.execute("SELECT * FROM glossary_series WHERE name = ?", (name,))
            return self._row(await cur.fetchone())
        finally:
            await db.close()

    async def delete(self, gid: int) -> bool:
        db = await self._connect()
        try:
            cur = await db.execute("DELETE FROM glossary_series WHERE id = ?", (gid,))
            await db.commit()
            return cur.rowcount > 0
        finally:
            await db.close()
