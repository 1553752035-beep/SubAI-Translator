# -*- coding: utf-8 -*-
"""
SubAI Translator —— 翻译缓存模块单元测试
========================================

覆盖：
1. 初始化（创建表/索引）
2. 写入与读取（命中、未命中）
3. TTL 过期
4. LRU 淘汰
5. 统计查询
6. 清空、清理过期
7. 并发场景
"""
from __future__ import annotations

import os
import time
import asyncio
import pytest

from src.cache.translation_cache import TranslationCache, CacheRecord


# --------------------------------------------------------------------------- #
# 基础 CRUD
# --------------------------------------------------------------------------- #
class TestCacheCRUD:
    @pytest.fixture
    async def cache(self, tmp_path):
        db = str(tmp_path / "cache.db")
        c = TranslationCache(db, max_entries=10, ttl_days=30)
        await c.initialize()
        yield c
        await c.close()

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache: TranslationCache):
        await cache.set("Hello", "zh", "你好")
        result = await cache.get("Hello", "zh")
        assert result == "你好"

    @pytest.mark.asyncio
    async def test_get_miss_returns_none(self, cache: TranslationCache):
        result = await cache.get("NotInCache", "zh")
        assert result is None

    @pytest.mark.asyncio
    async def test_different_lang_separate(self, cache: TranslationCache):
        await cache.set("Hello", "zh", "你好")
        await cache.set("Hello", "ja", "こんにちは")
        assert await cache.get("Hello", "zh") == "你好"
        assert await cache.get("Hello", "ja") == "こんにちは"

    @pytest.mark.asyncio
    async def test_overwrite_existing(self, cache: TranslationCache):
        await cache.set("Hello", "zh", "你好")
        await cache.set("Hello", "zh", "你好世界")
        assert await cache.get("Hello", "zh") == "你好世界"

    @pytest.mark.asyncio
    async def test_delete(self, cache: TranslationCache):
        await cache.set("Hello", "zh", "你好")
        assert await cache.delete("Hello", "zh") is True
        assert await cache.get("Hello", "zh") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, cache: TranslationCache):
        assert await cache.delete("不存在", "zh") is False


# --------------------------------------------------------------------------- #
# TTL 过期
# --------------------------------------------------------------------------- #
class TestCacheTTL:
    @pytest.mark.asyncio
    async def test_expired_record_treated_as_miss(self, tmp_path):
        """is_expired=True 时 get 返回 None 并删除记录"""
        # 直接造一条 created_at=0 的记录（远超 30 天）
        db = str(tmp_path / "expired.db")
        c = TranslationCache(db, max_entries=10, ttl_days=30)
        await c.initialize()

        # 强制写入 created_at=0
        await c._db.execute(  # noqa: SLF001
            """INSERT INTO translation_cache
               (text, target_lang, translation, created_at, accessed_at, access_count)
               VALUES (?, ?, ?, 0, 0, 1)""",
            ("OldText", "zh", "旧翻译"),
        )
        await c._db.commit()

        result = await c.get("OldText", "zh")
        assert result is None

        # 过期记录应该被自动删
        cur = await c._db.execute("SELECT COUNT(*) FROM translation_cache")
        row = await cur.fetchone()
        assert row[0] == 0

        await c.close()

    @pytest.mark.asyncio
    async def test_cleanup_expired(self, tmp_path):
        db = str(tmp_path / "cleanup.db")
        c = TranslationCache(db, max_entries=100, ttl_days=30)
        await c.initialize()

        # 写一条过期、一条新鲜的
        await c._db.execute(  # noqa: SLF001
            """INSERT INTO translation_cache (text, target_lang, translation, created_at, accessed_at, access_count)
               VALUES ('old', 'zh', 'x', 0, 0, 1)"""
        )
        await c.set("new", "zh", "新")
        await c._db.commit()

        deleted = await c.cleanup_expired()
        assert deleted == 1

        stats = await c.get_stats()
        assert stats["total_entries"] == 1
        await c.close()


# --------------------------------------------------------------------------- #
# LRU 淘汰
# --------------------------------------------------------------------------- #
class TestCacheLRU:
    @pytest.mark.asyncio
    async def test_evict_when_over_capacity(self, tmp_path):
        db = str(tmp_path / "lru.db")
        c = TranslationCache(db, max_entries=5, ttl_days=30)
        await c.initialize()

        # 写 10 条（容量 5）
        for i in range(10):
            await c.set(f"text_{i}", "zh", f"翻译_{i}")
            # 让 accessed_at 不同以便验证 LRU
            time.sleep(0.001)

        stats = await c.get_stats()
        # 容量上限 5，但代码会一次淘汰 20% 富余，实际可能略多
        assert stats["total_entries"] <= 6
        # 最旧的 0~3 必被淘汰
        assert await c.get("text_0", "zh") is None
        assert await c.get("text_1", "zh") is None
        # 新写入的最后几条仍在
        assert await c.get("text_9", "zh") == "翻译_9"

        await c.close()


# --------------------------------------------------------------------------- #
# 统计
# --------------------------------------------------------------------------- #
class TestCacheStats:
    @pytest.mark.asyncio
    async def test_get_stats_initial(self, tmp_path):
        db = str(tmp_path / "stats.db")
        c = TranslationCache(db)
        await c.initialize()
        stats = await c.get_stats()
        assert stats["total_entries"] == 0
        assert stats["hit_rate"] == 0.0
        await c.close()

    @pytest.mark.asyncio
    async def test_clear(self, tmp_path):
        db = str(tmp_path / "clear.db")
        c = TranslationCache(db)
        await c.initialize()
        for i in range(3):
            await c.set(f"t_{i}", "zh", f"翻译_{i}")
        deleted = await c.clear()
        assert deleted == 3
        stats = await c.get_stats()
        assert stats["total_entries"] == 0
        await c.close()

    @pytest.mark.asyncio
    async def test_context_manager(self, tmp_path):
        db = str(tmp_path / "ctx.db")
        async with TranslationCache(db) as c:
            await c.set("Hello", "zh", "你好")
            assert await c.get("Hello", "zh") == "你好"
        # 退出上下文后连接应已关闭
        assert c._db is None  # noqa: SLF001


# --------------------------------------------------------------------------- #
# 边界场景
# --------------------------------------------------------------------------- #
class TestCacheEdgeCases:
    @pytest.mark.asyncio
    async def test_unicode_text(self, tmp_path):
        db = str(tmp_path / "u.db")
        async with TranslationCache(db) as c:
            await c.set("日本語テスト", "zh", "日文测试")
            assert await c.get("日本語テスト", "zh") == "日文测试"

    @pytest.mark.asyncio
    async def test_special_chars(self, tmp_path):
        db = str(tmp_path / "s.db")
        async with TranslationCache(db) as c:
            await c.set("Hello @#$%", "zh", "你好 @#$%")
            assert await c.get("Hello @#$%", "zh") == "你好 @#$%"

    @pytest.mark.asyncio
    async def test_concurrent_writes(self, tmp_path):
        """并发写入不应破坏数据库"""
        db = str(tmp_path / "concurrent.db")
        c = TranslationCache(db)
        await c.initialize()
        try:
            await asyncio.gather(*[c.set(f"text_{i}", "zh", f"翻译_{i}") for i in range(20)])
            stats = await c.get_stats()
            assert stats["total_entries"] == 20
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_cache_record_is_expired(self):
        rec = CacheRecord("t", "zh", "翻译", created_at=time.time() - 40 * 86400,
                          accessed_at=time.time(), access_count=1)
        assert rec.is_expired is True

        rec2 = CacheRecord("t", "zh", "翻译", created_at=time.time(),
                           accessed_at=time.time(), access_count=1)
        assert rec2.is_expired is False