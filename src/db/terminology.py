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
    
    def _ensure_db(self) -> None:
        """确保数据库和表存在"""
        os.makedirs(os.path.dirname(self.db_path) if os.path.dirname(self.db_path) else ".", exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS terminology (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL UNIQUE,
                translation TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium',
                category TEXT DEFAULT 'custom',
                usage_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON terminology(source)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_priority ON terminology(priority)")
        conn.commit()
        conn.close()
    
    def add_term(
        self,
        source: str,
        translation: str,
        priority: str = "medium",
        category: str = "custom"
    ) -> bool:
        """
        添加术语
        
        Args:
            source: 原文（中文/英文等）
            translation: 用户翻译
            priority: 优先级（high/medium/low）
            category: 分类（custom/domain/system）
        
        Returns:
            bool: 是否添加成功（已存在则更新）
        """
        now = datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        try:
            # 检查是否已存在
            cursor = conn.execute("SELECT id FROM terminology WHERE source = ?", (source,))
            existing = cursor.fetchone()
            
            if existing:
                # 更新现有术语
                conn.execute(
                    "UPDATE terminology SET translation = ?, priority = ?, category = ?, updated_at = ? WHERE source = ?",
                    (translation, priority, category, now, source)
                )
                success = True
            else:
                # 插入新术语
                conn.execute(
                    "INSERT INTO terminology (source, translation, priority, category, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (source, translation, priority, category, now, now)
                )
                success = True
            
            conn.commit()
            return success
        finally:
            conn.close()
    
    def match(self, source: str) -> Optional[str]:
        """
        精确匹配术语库
        
        Args:
            source: 待匹配的原文
        
        Returns:
            str or None: 匹配的译文，未匹配返回None
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute(
                "SELECT translation FROM terminology WHERE source = ?",
                (source,)
            )
            row = cursor.fetchone()
            if row:
                # 增加使用计数
                conn.execute(
                    "UPDATE terminology SET usage_count = usage_count + 1 WHERE source = ?",
                    (source,)
                )
                conn.commit()
                return row[0]
            return None
        finally:
            conn.close()
    
    def delete_term(self, source: str) -> bool:
        """
        删除术语
        
        Args:
            source: 原文
        
        Returns:
            bool: 是否删除成功
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("DELETE FROM terminology WHERE source = ?", (source,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def list_terms(
        self,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        keyword: Optional[str] = None
    ) -> list[dict]:
        """
        查询术语列表
        
        Args:
            category: 分类过滤
            priority: 优先级过滤
            keyword: 关键词搜索（原文或译文）
        
        Returns:
            list[dict]: 术语列表
        """
        conn = sqlite3.connect(self.db_path)
        try:
            query = "SELECT source, translation, priority, category, usage_count, created_at FROM terminology WHERE 1=1"
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
            
            query += " ORDER BY usage_count DESC, created_at DESC"
            
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            
            return [
                {
                    "source": row[0],
                    "translation": row[1],
                    "priority": row[2],
                    "category": row[3],
                    "usage_count": row[4],
                    "created_at": row[5]
                }
                for row in rows
            ]
        finally:
            conn.close()
    
    def import_from_json(self, json_path: str) -> int:
        """
        从JSON文件导入术语
        
        Args:
            json_path: JSON文件路径
        
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
                    category=term.get("category", "custom")
                )
                count += 1
        
        return count
    
    def export_to_json(self, json_path: str) -> None:
        """
        导出术语到JSON文件
        
        Args:
            json_path: JSON文件路径
        """
        terms = self.list_terms()
        
        os.makedirs(os.path.dirname(json_path) if os.path.dirname(json_path) else ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(terms, f, ensure_ascii=False, indent=2)
    
    def get_stats(self) -> dict:
        """
        获取术语库统计信息
        
        Returns:
            dict: 统计信息
        """
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM terminology")
            total = cursor.fetchone()[0]
            
            cursor = conn.execute("SELECT COALESCE(SUM(usage_count), 0) FROM terminology")
            total_usage = cursor.fetchone()[0]
            
            cursor = conn.execute(
                "SELECT priority, COUNT(*) FROM terminology GROUP BY priority"
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
    
    async def add_term(self, source: str, translation: str, priority: str = "medium", category: str = "custom") -> bool:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.add_term, source, translation, priority, category)
    
    async def match(self, source: str) -> Optional[str]:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.match, source)
    
    async def delete_term(self, source: str) -> bool:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.delete_term, source)
    
    async def list_terms(self, category: Optional[str] = None, priority: Optional[str] = None, keyword: Optional[str] = None) -> list[dict]:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.list_terms, category, priority, keyword)
    
    async def import_from_json(self, json_path: str) -> int:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.import_from_json, json_path)
    
    async def export_to_json(self, json_path: str) -> None:
        await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.export_to_json, json_path)
    
    async def get_stats(self) -> dict:
        return await asyncio.get_event_loop().run_in_executor(None, self._sync_manager.get_stats)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass