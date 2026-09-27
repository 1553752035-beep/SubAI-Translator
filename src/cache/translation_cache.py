# -*- coding: utf-8 -*-
"""
SubAI Translator —— 翻译缓存模块（二期新增）
==========================================

使用SQLite持久化翻译缓存，支持：
1. 精确匹配查询（相同文本+相同目标语言=命中）
2. TTL机制（缓存有效期，默认30天）
3. 容量限制（最多10000条）
4. LRU淘汰策略（超出容量时淘汰最久未使用）

性能指标：
- 缓存查询延迟≤10ms
- 缓存命中率≥20%
- 缓存持久化（服务重启不丢失）

使用示例：
    from src.cache.translation_cache import TranslationCache
    
    cache = TranslationCache()
    await cache.initialize()
    
    # 查询缓存
    cached = await cache.get("Hello world", "zh")
    if cached:
        print(f"缓存命中: {cached}")
    else:
        # 翻译并缓存
        translation = await translate_text("Hello world", "zh")
        await cache.set("Hello world", "zh", translation)
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from typing import Optional

import aiosqlite


# --------------------------------------------------------------------------- #
# 缓存记录
# --------------------------------------------------------------------------- #

class CacheRecord:
    """缓存记录"""
    def __init__(
        self,
        text: str,
        target_lang: str,
        translation: str,
        created_at: float,
        accessed_at: float,
        access_count: int = 1
    ):
        self.text = text
        self.target_lang = target_lang
        self.translation = translation
        self.created_at = created_at
        self.accessed_at = accessed_at
        self.access_count = access_count
    
    @property
    def is_expired(self) -> bool:
        """检查是否过期"""
        ttl_seconds = 30 * 24 * 3600  # 30天
        return (time.time() - self.created_at) > ttl_seconds
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "text": self.text,
            "target_lang": self.target_lang,
            "translation": self.translation,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "accessed_at": datetime.fromtimestamp(self.accessed_at).isoformat(),
            "access_count": self.access_count
        }


# --------------------------------------------------------------------------- #
# 翻译缓存管理器
# --------------------------------------------------------------------------- #

class TranslationCache:
    """
    翻译缓存管理器
    
    使用SQLite持久化翻译结果，支持：
    - 精确匹配查询
    - TTL过期机制
    - LRU淘汰策略
    - 统计查询
    """
    
    def __init__(
        self,
        db_path: str,
        max_entries: int = 10000,
        ttl_days: int = 30
    ):
        """
        初始化翻译缓存
        
        Args:
            db_path: SQLite数据库路径
            max_entries: 最大缓存条目数
            ttl_days: 缓存有效期（天）
        """
        self.db_path = db_path
        self.max_entries = max_entries
        self.ttl_days = ttl_days
        self._db: Optional[aiosqlite.Connection] = None
    
    async def initialize(self) -> None:
        """初始化数据库（创建表）"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        
        # 创建缓存表
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS translation_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                target_lang TEXT NOT NULL,
                translation TEXT NOT NULL,
                created_at REAL NOT NULL,
                accessed_at REAL NOT NULL,
                access_count INTEGER DEFAULT 1,
                UNIQUE(text, target_lang)
            )
        """)
        
        # 创建索引
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_text_lang 
            ON translation_cache(text, target_lang)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_cache_accessed_at 
            ON translation_cache(accessed_at DESC)
        """)
        
        await self._db.commit()
    
    async def close(self) -> None:
        """关闭数据库连接"""
        if self._db:
            await self._db.close()
            self._db = None
    
    @property
    def is_open(self) -> bool:
        return self._db is not None
    
    # ----------------------------------------------------------------------- #
    # 缓存操作
    # ----------------------------------------------------------------------- #
    
    async def get(self, text: str, target_lang: str) -> Optional[str]:
        """
        查询缓存
        
        Args:
            text: 源文本
            target_lang: 目标语言
        
        Returns:
            缓存的翻译结果，如果未命中或过期则返回None
        """
        if not self._db:
            return None
        
        # 查询缓存
        cursor = await self._db.execute(
            """SELECT * FROM translation_cache 
               WHERE text = ? AND target_lang = ?""",
            (text, target_lang)
        )
        row = await cursor.fetchone()
        
        if not row:
            return None
        
        # 检查是否过期
        record = CacheRecord(
            text=row["text"],
            target_lang=row["target_lang"],
            translation=row["translation"],
            created_at=row["created_at"],
            accessed_at=row["accessed_at"],
            access_count=row["access_count"]
        )
        
        if record.is_expired:
            # 删除过期记录
            await self._db.execute(
                "DELETE FROM translation_cache WHERE id = ?", (row["id"],)
            )
            await self._db.commit()
            return None
        
        # 更新访问时间和计数
        await self._db.execute(
            """UPDATE translation_cache 
               SET accessed_at = ?, access_count = access_count + 1 
               WHERE id = ?""",
            (time.time(), row["id"])
        )
        await self._db.commit()
        
        return record.translation
    
    async def set(
        self,
        text: str,
        target_lang: str,
        translation: str
    ) -> None:
        """
        写入缓存
        
        Args:
            text: 源文本
            target_lang: 目标语言
            translation: 翻译结果
        """
        if not self._db:
            return
        
        now = time.time()
        
        try:
            # 插入或更新（UPERT）
            await self._db.execute(
                """INSERT INTO translation_cache 
                   (text, target_lang, translation, created_at, accessed_at, access_count)
                   VALUES (?, ?, ?, ?, ?, 1)
                   ON CONFLICT(text, target_lang) 
                   DO UPDATE SET 
                       translation = excluded.translation,
                       accessed_at = excluded.accessed_at,
                       access_count = access_count + 1""",
                (text, target_lang, translation, now, now)
            )
        except Exception:
            # 如果UPERT失败，尝试更新
            await self._db.execute(
                """UPDATE translation_cache 
                   SET translation = ?, accessed_at = ?, access_count = access_count + 1
                   WHERE text = ? AND target_lang = ?""",
                (translation, now, text, target_lang)
            )
        
        await self._db.commit()
        
        # 检查容量限制，执行LRU淘汰
        await self._evict_if_needed()
    
    async def delete(self, text: str, target_lang: str) -> bool:
        """
        删除缓存
        
        Args:
            text: 源文本
            target_lang: 目标语言
        
        Returns:
            是否删除成功
        """
        if not self._db:
            return False
        
        cursor = await self._db.execute(
            """DELETE FROM translation_cache 
               WHERE text = ? AND target_lang = ?""",
            (text, target_lang)
        )
        await self._db.commit()
        return cursor.rowcount > 0
    
    async def clear(self) -> int:
        """
        清空所有缓存
        
        Returns:
            删除的记录数
        """
        if not self._db:
            return 0
        
        cursor = await self._db.execute("DELETE FROM translation_cache")
        await self._db.commit()
        return cursor.rowcount
    
    async def cleanup_expired(self) -> int:
        """
        清理过期记录
        
        Returns:
            删除的记录数
        """
        if not self._db:
            return 0
        
        ttl_seconds = self.ttl_days * 24 * 3600
        cutoff_time = time.time() - ttl_seconds
        
        cursor = await self._db.execute(
            "DELETE FROM translation_cache WHERE created_at < ?",
            (cutoff_time,)
        )
        await self._db.commit()
        return cursor.rowcount
    
    # ----------------------------------------------------------------------- #
    # 统计查询
    # ----------------------------------------------------------------------- #
    
    async def get_stats(self) -> dict:
        """
        获取缓存统计信息
        
        Returns:
            统计字典
        """
        if not self._db:
            return {
                "total_entries": 0,
                "max_entries": self.max_entries,
                "ttl_days": self.ttl_days,
                "hit_rate": 0.0,
                "size_mb": 0.0
            }
        
        # 总条目数
        cursor = await self._db.execute("SELECT COUNT(*) as total FROM translation_cache")
        row = await cursor.fetchone()
        total_entries = row["total"]
        
        # 数据库文件大小
        if os.path.exists(self.db_path):
            size_mb = os.path.getsize(self.db_path) / (1024 * 1024)
        else:
            size_mb = 0.0
        
        # 估算命中率（简化版：access_count>1的记录占比）
        cursor = await self._db.execute(
            "SELECT COUNT(*) as hits FROM translation_cache WHERE access_count > 1"
        )
        row = await cursor.fetchone()
        hit_count = row["hits"]
        hit_rate = (hit_count / total_entries * 100) if total_entries > 0 else 0.0
        
        return {
            "total_entries": total_entries,
            "max_entries": self.max_entries,
            "ttl_days": self.ttl_days,
            "hit_rate": round(hit_rate, 2),
            "size_mb": round(size_mb, 2)
        }
    
    # ----------------------------------------------------------------------- #
    # 工具方法
    # ----------------------------------------------------------------------- #
    
    async def _evict_if_needed(self) -> None:
        """如果超出容量限制，执行LRU淘汰"""
        if not self._db:
            return
        
        # 查询当前条目数
        cursor = await self._db.execute("SELECT COUNT(*) as total FROM translation_cache")
        row = await cursor.fetchone()
        total = row["total"]
        
        if total <= self.max_entries:
            return
        
        # 计算需要淘汰的数量（淘汰20%）
        evict_count = int((total - self.max_entries) * 1.2)
        evict_count = max(1, evict_count)
        
        # 淘汰最久未访问的记录（LRU）
        await self._db.execute(
            """DELETE FROM translation_cache 
               WHERE id IN (
                   SELECT id FROM translation_cache 
                   ORDER BY accessed_at ASC 
                   LIMIT ?
               )""",
            (evict_count,)
        )
        await self._db.commit()
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()


# --------------------------------------------------------------------------- #
# 全局实例（供Pipeline使用）
# --------------------------------------------------------------------------- #

DEFAULT_CACHE_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                "data", "translation_cache.db")

# 全局缓存实例
translation_cache: Optional[TranslationCache] = None


async def get_translation_cache(db_path: Optional[str] = None) -> TranslationCache:
    """
    获取全局翻译缓存实例（单例）
    
    Args:
        db_path: 数据库路径
    
    Returns:
        TranslationCache实例
    """
    global translation_cache
    if translation_cache is None:
        db_path = db_path or DEFAULT_CACHE_DB
        translation_cache = TranslationCache(db_path)
        await translation_cache.initialize()
    return translation_cache