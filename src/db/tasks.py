# -*- coding: utf-8 -*-
"""
SubAI Translator —— 任务状态持久化模块（二期新增）
================================================

使用SQLite持久化任务状态，支持：
1. 任务创建、查询、更新、删除
2. 任务状态持久化（服务重启不丢失）
3. 任务历史记录查询
4. 批量任务管理

设计思路：
- 使用aiosqlite实现异步IO，不阻塞FastAPI事件循环
- 任务状态表包含完整生命周期信息
- 支持按视频名、状态、时间范围过滤查询
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #

class TaskRecord:
    """任务记录"""
    def __init__(
        self,
        task_id: str,
        video_path: str,
        mode: str = "asr",
        source_lang: Optional[str] = None,
        target_lang: str = "en",
        output_format: str = "srt",
        terms_file: Optional[str] = None,
        status: str = "pending",
        progress: float = 0.0,
        message: str = "",
        result_files: Optional[list[str]] = None,
        created_at: Optional[float] = None,
        updated_at: Optional[float] = None,
        completed_at: Optional[float] = None,
        error_message: Optional[str] = None
    ):
        self.task_id = task_id
        self.video_path = video_path
        self.mode = mode
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.output_format = output_format
        self.terms_file = terms_file
        self.status = status
        self.progress = progress
        self.message = message
        self.result_files = result_files or []
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or time.time()
        self.completed_at = completed_at
        self.error_message = error_message
    
    def to_dict(self) -> dict:
        """转换为字典（用于API响应）"""
        return {
            "task_id": self.task_id,
            "video_path": self.video_path,
            "mode": self.mode,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "output_format": self.output_format,
            "terms_file": self.terms_file,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "result_files": self.result_files,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "updated_at": datetime.fromtimestamp(self.updated_at).isoformat(),
            "completed_at": datetime.fromtimestamp(self.completed_at).isoformat() if self.completed_at else None,
            "error_message": self.error_message
        }


# --------------------------------------------------------------------------- #
# 任务管理器
# --------------------------------------------------------------------------- #

class TaskManager:
    """
    任务状态管理器（异步）
    
    使用SQLite持久化任务状态，支持：
    - 任务创建、查询、更新、删除
    - 任务历史记录查询
    - 批量任务管理
    """
    
    def __init__(self, db_path: str):
        """
        初始化任务管理器
        
        Args:
            db_path: SQLite数据库路径
        """
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None
    
    async def initialize(self) -> None:
        """初始化数据库（创建表）"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        
        # 创建任务表
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                video_path TEXT NOT NULL,
                mode TEXT DEFAULT 'asr',
                source_lang TEXT,
                target_lang TEXT DEFAULT 'en',
                output_format TEXT DEFAULT 'srt',
                terms_file TEXT,
                status TEXT DEFAULT 'pending',
                progress REAL DEFAULT 0.0,
                message TEXT DEFAULT '',
                result_files TEXT DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                completed_at REAL,
                error_message TEXT
            )
        """)
        
        # 创建索引（加速查询）
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status 
            ON tasks(status)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_created_at 
            ON tasks(created_at DESC)
        """)
        await self._db.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_video_path 
            ON tasks(video_path)
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
    # 任务操作
    # ----------------------------------------------------------------------- #
    
    async def create_task(
        self,
        task_id: str,
        video_path: str,
        mode: str = "asr",
        source_lang: Optional[str] = None,
        target_lang: str = "en",
        output_format: str = "srt",
        terms_file: Optional[str] = None
    ) -> TaskRecord:
        """
        创建新任务
        
        Args:
            task_id: 任务ID
            video_path: 视频文件路径
            mode: 识别模式（asr/hardsub）
            source_lang: 源语言
            target_lang: 目标语言
            output_format: 输出格式
            terms_file: 术语库文件
        
        Returns:
            TaskRecord: 创建的任务记录
        """
        now = time.time()
        record = TaskRecord(
            task_id=task_id,
            video_path=video_path,
            mode=mode,
            source_lang=source_lang,
            target_lang=target_lang,
            output_format=output_format,
            terms_file=terms_file,
            status="pending",
            progress=0.0,
            message="任务已创建，等待处理",
            created_at=now,
            updated_at=now
        )
        
        await self._db.execute(
            """INSERT INTO tasks 
               (task_id, video_path, mode, source_lang, target_lang, output_format, 
                terms_file, status, progress, message, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.task_id, record.video_path, record.mode, record.source_lang,
                record.target_lang, record.output_format, record.terms_file,
                record.status, record.progress, record.message,
                record.created_at, record.updated_at
            )
        )
        await self._db.commit()
        
        return record
    
    async def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """查询任务"""
        cursor = await self._db.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        
        if not row:
            return None
        
        return self._row_to_record(row)
    
    async def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        result_files: Optional[list[str]] = None,
        error_message: Optional[str] = None
    ) -> Optional[TaskRecord]:
        """
        更新任务状态
        
        Args:
            task_id: 任务ID
            status: 新状态
            progress: 新进度
            message: 新消息
            result_files: 结果文件列表
            error_message: 错误消息
        
        Returns:
            TaskRecord: 更新后的任务记录，如果任务不存在则返回None
        """
        now = time.time()
        
        # 构建UPDATE语句
        set_clauses = []
        values = []
        
        if status is not None:
            set_clauses.append("status = ?")
            values.append(status)
        
        if progress is not None:
            set_clauses.append("progress = ?")
            values.append(progress)
        
        if message is not None:
            set_clauses.append("message = ?")
            values.append(message)
        
        if result_files is not None:
            set_clauses.append("result_files = ?")
            values.append(json.dumps(result_files, ensure_ascii=False))
        
        if error_message is not None:
            set_clauses.append("error_message = ?")
            values.append(error_message)
        
        set_clauses.append("updated_at = ?")
        values.append(now)
        
        # 如果状态是completed或failed，设置completed_at
        if status in ("completed", "failed"):
            set_clauses.append("completed_at = ?")
            values.append(now)
        
        values.append(task_id)
        
        sql = f"UPDATE tasks SET {', '.join(set_clauses)} WHERE task_id = ?"
        await self._db.execute(sql, values)
        await self._db.commit()
        
        return await self.get_task(task_id)
    
    async def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        cursor = await self._db.execute(
            "DELETE FROM tasks WHERE task_id = ?", (task_id,)
        )
        await self._db.commit()
        return cursor.rowcount > 0
    
    # ----------------------------------------------------------------------- #
    # 查询操作
    # ----------------------------------------------------------------------- #
    
    async def list_tasks(
        self,
        status: Optional[str] = None,
        video_path: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> list[TaskRecord]:
        """
        查询任务列表
        
        Args:
            status: 按状态过滤
            video_path: 按视频路径过滤
            limit: 返回数量限制
            offset: 偏移量
        
        Returns:
            TaskRecord列表
        """
        sql = "SELECT * FROM tasks WHERE 1=1"
        params = []
        
        if status:
            sql += " AND status = ?"
            params.append(status)
        
        if video_path:
            sql += " AND video_path LIKE ?"
            params.append(f"%{video_path}%")
        
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        
        return [self._row_to_record(row) for row in rows]
    
    async def get_active_tasks(self) -> list[TaskRecord]:
        """获取所有活跃任务（pending/processing状态）"""
        return await self.list_tasks(status="pending") + await self.list_tasks(status="processing")
    
    async def get_stats(self) -> dict:
        """
        获取任务统计信息
        
        Returns:
            统计字典
        """
        stats = {}
        
        # 各状态任务数
        cursor = await self._db.execute("""
            SELECT status, COUNT(*) as count 
            FROM tasks 
            GROUP BY status
        """)
        rows = await cursor.fetchall()
        stats["by_status"] = {row["status"]: row["count"] for row in rows}
        
        # 总任务数
        cursor = await self._db.execute("SELECT COUNT(*) as total FROM tasks")
        row = await cursor.fetchone()
        stats["total"] = row["total"]
        
        # 今日任务数
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        cursor = await self._db.execute(
            "SELECT COUNT(*) as count FROM tasks WHERE created_at >= ?", (today_start,)
        )
        row = await cursor.fetchone()
        stats["today"] = row["count"]
        
        return stats
    
    # ----------------------------------------------------------------------- #
    # 工具方法
    # ----------------------------------------------------------------------- #
    
    def _row_to_record(self, row: aiosqlite.Row) -> TaskRecord:
        """将数据库行转换为TaskRecord"""
        result_files = []
        if row["result_files"]:
            try:
                result_files = json.loads(row["result_files"])
            except:
                result_files = []
        
        return TaskRecord(
            task_id=row["task_id"],
            video_path=row["video_path"],
            mode=row["mode"],
            source_lang=row["source_lang"],
            target_lang=row["target_lang"],
            output_format=row["output_format"],
            terms_file=row["terms_file"],
            status=row["status"],
            progress=row["progress"],
            message=row["message"],
            result_files=result_files,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            error_message=row["error_message"]
        )


# --------------------------------------------------------------------------- #
# 全局实例（供API使用）
# --------------------------------------------------------------------------- #

# 默认数据库路径
DEFAULT_TASKS_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                "data", "tasks.db")

# 全局任务管理器实例
task_manager: Optional[TaskManager] = None


async def get_task_manager(db_path: Optional[str] = None) -> TaskManager:
    """
    获取全局任务管理器实例（单例）
    
    Args:
        db_path: 数据库路径，默认使用data/tasks.db
    
    Returns:
        TaskManager实例
    """
    global task_manager
    if task_manager is None:
        db_path = db_path or DEFAULT_TASKS_DB
        task_manager = TaskManager(db_path)
        await task_manager.initialize()
    return task_manager