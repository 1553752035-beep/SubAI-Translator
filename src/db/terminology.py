# -*- coding: utf-8 -*-
"""
SubAI Translator —— 术语库模块（一期：精确匹配）
================================================

对应设计文档「优化一：用户自定义术语库系统」
一期仅实现精确匹配，二期扩展上下文/正则匹配。

核心特性：
1. SQLite持久化存储（一期用aiosqlite）
2. 精确匹配（原文 → 用户翻译）
3. 优先级管理（高优先级覆盖AI翻译）
4. 使用统计（使用次数、创建时间）
5. 支持JSON文件导入/导出

使用示例：
    from src.db.terminology import TerminologyManager
    
    # 异步使用
    async with TerminologyManager("data/terminology.db") as tm:
        await tm.add_term("这是测试", "This is a test", priority="high")
        translation = await tm.match("这是测试")
    
    # 同步使用（内部自动创建事件循环）
    tm = TerminologyManager("data/terminology.db")
    tm.add_term("这是测试", "This is a test")
    translation = tm.match("这是测试")
"""
from __future__ import annotations

import json
import os
import sqlite3
import asyncio
from datetime import datetime
from typing import Optional


class TerminologyManager:
    """术语库管理器（同步+异步双接口）"""
    
    def __init__(self, db_path: str = "data/terminology.db"):
        """
        初始化术语库管理器
        
        Args:
            db_path: SQLite数据库路径
        """
        self.db_path = db_path
        self._ensure_db()
    
    # 建表 SQL（三期：source 不再全局唯一，改为 source+user_id 组合唯一，支持多用户隔离）
    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS terminology (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            translation TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'medium',
            category TEXT DEFAULT 'custom',
            usage_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            user_id TEXT
        )
    """
    
    def _ensure_db(self) -> None:
        """确保数据库和表存在（含三期 user_id 迁移）"""
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else ".", exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='terminology'"
            ).fetchall()]
            
            if tables:
                # 旧库迁移：无 user_id 列时重建表
                cols = [r[1] for r in conn.execute("PRAGMA table_info(terminology)").fetchall()]
                if "user_id" not in cols:
                    conn.execute("ALTER TABLE terminology RENAME TO terminology_old")
                    conn.execute(self._CREATE_TABLE_SQL)
                    conn.execute("""
                        INSERT INTO terminology (source, translation, priority, category, usage_count, created_at, updated_at, user_id)
                        SELECT source, translation, priority, category, usage_count, created_at, updated_at, NULL
                        FROM terminology_old
                    """)
                    conn.execute("DROP TABLE terminology_old")
            else:
                conn.execute(self._CREATE_TABLE_SQL)
            
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_source_user ON terminology(source, user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_priority ON terminology(priority)")
            conn.commit()
        finally:
            conn.close()
    
    def add_term(
        self,
        source: str,
        translation: str,
        priority: str = "medium",
        category: str = "custom",
        user_id: Optional[str] = None
    ) -> bool:
        """
        添加术语
        
        Args:
            source: 原文（中文/英文等）
            translation: 用户翻译
            priority: 优先级（high/medium/low）
            category: 分类（custom/domain/system）
            user_id: 所属用户ID（None 表示系统术语）
        
        Returns:
            bool: 是否添加成功（已存在则更新）
        """
        now = datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        try:
            # 检查是否已存在（同 source + user_id）
            cursor = conn.execute(
                "SELECT id FROM terminology WHERE source = ? AND user_id IS ?",
                (source, user_id)
            )
            existing = cursor.fetchone()
            
            if existing:
                # 更新现有术语
                conn.execute(
                    "UPDATE terminology SET translation = ?, priority = ?, category = ?, updated_at = ? WHERE source = ? AND user_id IS ?",
                    (translation, priority, category, now, source, user_id)
                )
                success = True
            else:
                # 插入新术语
                conn.execute(
                    "INSERT INTO terminology (source, translation, priority, category, created_at, updated_at, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (source, translation, priority, category, now, now, user_id)
                )
                success = True
            
            conn.commit()
            return success
        finally:
            conn.close()
    
    def match(self, source: str, user_id: Optional[str] = None) -> Optional[str]:
        """
        精确匹配术语库
        
        Args:
            source: 待匹配的原文
            user_id: 用户ID（None 匹配所有术语；指定时匹配系统术语+该用户术语，用户术语优先）
        
        Returns:
            str or None: 匹配的译文，未匹配返回None
        """
        conn = sqlite3.connect(self.db_path)
        try:
            if user_id is None:
                # 向后兼容：匹配所有术语
                cursor = conn.execute(
                    "SELECT id, translation FROM terminology WHERE source = ? "
                    "ORDER BY (user_id IS NULL) ASC, usage_count DESC LIMIT 1",
                    (source,)
                )
            else:
                # 匹配系统术语 + 该用户术语，用户术语优先
                cursor = conn.execute(
                    "SELECT id, translation FROM terminology WHERE source = ? "
                    "AND (user_id IS NULL OR user_id = ?) "
                    "ORDER BY (user_id IS NULL) ASC, usage_count DESC LIMIT 1",
                    (source, user_id)
                )
            row = cursor.fetchone()
            if row:
                # 增加使用计数
                conn.execute(
                    "UPDATE terminology SET usage_count = usage_count + 1 WHERE id = ?",
                    (row[0],)
                )
                conn.commit()
                return row[1]
            return None
        finally:
            conn.close()
    
    def delete_term(self, source: str, user_id: Optional[str] = None) -> bool:
        """
        删除术语
        
        Args:
            source: 原文
            user_id: 所属用户ID
        
        Returns:
            bool: 是否删除成功
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "DELETE FROM terminology WHERE source = ? AND user_id IS ?",
                (source, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def list_terms(
        self,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        keyword: Optional[str] = None,
        user_id: Optional[str] = None,
        include_system: bool = False
    ) -> list[dict]:
        """
        查询术语列表
        
        Args:
            category: 分类过滤
            priority: 优先级过滤
            keyword: 关键词搜索（原文或译文）
            user_id: 数据隔离过滤（None 表示不过滤）
            include_system: 为 True 时（且指定 user_id）同时返回系统术语（user_id IS NULL）
        
        Returns:
            list[dict]: 术语列表
        """
        conn = sqlite3.connect(self.db_path)
        try:
            query = "SELECT source, translation, priority, category, usage_count, created_at, user_id FROM terminology WHERE 1=1"
            params = []
            
            if category:
                query += " AND category = ?"
                params.append(category)
            if priority:
                query += " AND priority = ?"
                params.append(priority)
            if keyword:
                query += " AND (source LIKE ? OR translation LIKE ?)"
                params.extend([f"%{keyword}%", f"%{keyword}%"])
            if user_id is not None:
                if include_system:
                    query += " AND (user_id IS NULL OR user_id = ?)"
                else:
                    query += " AND user_id = ?"
                params.append(user_id)
            
            query += " ORDER BY (user_id IS NULL) ASC, usage_count DESC, created_at DESC"
            
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            
            return [
                {
                    "source": row[0],
                    "translation": row[1],
                    "priority": row[2],
                    "category": row[3],
                    "usage_count": row[4],
                    "created_at": row[5],
                    "user_id": row[6]
                }
                for row in rows
            ]
        finally:
            conn.close()
    
    def import_from_json(self, json_path: str, user_id: Optional[str] = None) -> int:
        """
        从JSON文件导入术语
        
        Args:
            json_path: JSON文件路径
            user_id: 归属用户ID
        
        Returns:
            int: 导入的术语数量
        """
        with open(json_path, "r", encoding="utf-8") as f:
            terms = json.load(f)
        
        count = 0
        for term in terms:
            if isinstance(term, dict) and "source" in term and "translation" in term:
                self.add_term(
                    source=term["source"],
                    translation=term["translation"],
                    priority=term.get("priority", "medium"),
                    category=term.get("category", "custom"),
                    user_id=user_id
                )
                count += 1
        
        return count
    
    def export_to_json(self, json_path: str, user_id: Optional[str] = None) -> None:
        """
        导出术语到JSON文件
        
        Args:
            json_path: JSON文件路径
            user_id: 数据隔离过滤
        """
        terms = self.list_terms(user_id=user_id)
        
        os.makedirs(os.path.dirname(json_path) if os.path.dirname(json_path) else ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(terms, f, ensure_ascii=False, indent=2)
    
    def get_stats(self, user_id: Optional[str] = None) -> dict:
        """
        获取术语库统计信息
        
        Args:
            user_id: 数据隔离过滤
        
        Returns:
            dict: 统计信息
        """
        conn = sqlite3.connect(self.db_path)
        try:
            where = "WHERE user_id = ?" if user_id is not None else ""
            params = (user_id,) if user_id is not None else ()
            
            cursor = conn.execute(f"SELECT COUNT(*) FROM terminology {where}", params)
            total = cursor.fetchone()[0]
            
            cursor = conn.execute(f"SELECT COALESCE(SUM(usage_count), 0) FROM terminology {where}", params)
            total_usage = cursor.fetchone()[0]
            
            cursor = conn.execute(
                f"SELECT priority, COUNT(*) FROM terminology {where} GROUP BY priority",
                params
            )
            by_priority = {row[0]: row[1] for row in cursor.fetchall()}
            
            return {
                "total_terms": total,
                "total_usage": total_usage,
                "by_priority": by_priority
            }
        finally:
            conn.close()


# --------------------------------------------------------------------------- #
# 异步接口（封装同步方法）
# --------------------------------------------------------------------------- #
class AsyncTerminologyManager:
    """术语库管理器异步接口"""
    
    def __init__(self, db_path: str = "data/terminology.db"):
        self._sync_manager = TerminologyManager(db_path)
    
    async def add_term(self, source: str, translation: str, priority: str = "medium", category: str = "custom", user_id: Optional[str] = None) -> bool:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.add_term, source, translation, priority, category, user_id)
    
    async def match(self, source: str, user_id: Optional[str] = None) -> Optional[str]:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.match, source, user_id)
    
    async def delete_term(self, source: str, user_id: Optional[str] = None) -> bool:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.delete_term, source, user_id)
    
    async def list_terms(self, category: Optional[str] = None, priority: Optional[str] = None, keyword: Optional[str] = None, user_id: Optional[str] = None, include_system: bool = False) -> list[dict]:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.list_terms, category, priority, keyword, user_id, include_system)
    
    async def import_from_json(self, json_path: str, user_id: Optional[str] = None) -> int:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.import_from_json, json_path, user_id)
    
    async def export_to_json(self, json_path: str, user_id: Optional[str] = None) -> None:
        await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.export_to_json, json_path, user_id)
    
    async def get_stats(self, user_id: Optional[str] = None) -> dict:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.get_stats, user_id)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass