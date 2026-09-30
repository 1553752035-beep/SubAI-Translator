# -*- coding: utf-8 -*-
"""
SubAI Translator —— 用户账户管理模块（三期新增）
================================================

使用 aiosqlite 持久化用户账户，支持：
1. 用户注册、查询、密码校验
2. 角色管理（user/admin）
3. 密码修改、账户启停

设计要点：
- 密码只存 PBKDF2 哈希，绝不存明文
- 用户名唯一约束，注册前先查重
- 与 tasks.py 保持一致的异步风格与单例模式
"""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from typing import Optional

import aiosqlite

from .security import hash_password, verify_password


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #

class UserRecord:
    """用户记录"""

    def __init__(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        role: str = "user",
        email: Optional[str] = None,
        is_active: bool = True,
        created_at: Optional[float] = None,
        updated_at: Optional[float] = None,
    ):
        self.user_id = user_id
        self.username = username
        self.password_hash = password_hash
        self.role = role
        self.email = email
        self.is_active = bool(is_active)
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or time.time()

    def to_dict(self, include_hash: bool = False) -> dict:
        """转换为字典（默认不暴露密码哈希）"""
        data = {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role,
            "email": self.email,
            "is_active": self.is_active,
            "created_at": datetime.fromtimestamp(self.created_at).isoformat(),
            "updated_at": datetime.fromtimestamp(self.updated_at).isoformat(),
        }
        if include_hash:
            data["password_hash"] = self.password_hash
        return data


# --------------------------------------------------------------------------- #
# 用户管理器
# --------------------------------------------------------------------------- #

class UserManager:
    """用户账户管理器（异步）"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """初始化数据库并建表"""
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row

        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT DEFAULT 'user',
                email TEXT,
                is_active INTEGER DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)"
        )
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
    # 用户操作
    # ----------------------------------------------------------------------- #

    async def create_user(
        self,
        username: str,
        password: str,
        role: str = "user",
        email: Optional[str] = None,
    ) -> UserRecord:
        """
        创建新用户

        Args:
            username: 用户名（唯一）
            password: 明文密码（入库前哈希）
            role: 角色（user/admin）
            email: 邮箱（可选）

        Returns:
            创建的用户记录

        Raises:
            ValueError: 用户名已存在或密码为空
        """
        username = (username or "").strip()
        if not username:
            raise ValueError("用户名不能为空")
        if not password:
            raise ValueError("密码不能为空")
        if role not in ("user", "admin"):
            role = "user"

        # 用户名查重
        existing = await self.get_by_username(username)
        if existing:
            raise ValueError(f"用户名已存在: {username}")

        now = time.time()
        user_id = uuid.uuid4().hex
        password_hash = hash_password(password)

        await self._db.execute(
            """INSERT INTO users (id, username, password_hash, role, email, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (user_id, username, password_hash, role, email, now, now),
        )
        await self._db.commit()

        return UserRecord(
            user_id=user_id,
            username=username,
            password_hash=password_hash,
            role=role,
            email=email,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

    async def get_by_username(self, username: str) -> Optional[UserRecord]:
        """按用户名查询用户"""
        cursor = await self._db.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        )
        row = await cursor.fetchone()
        return self._row_to_record(row) if row else None

    async def get_by_id(self, user_id: str) -> Optional[UserRecord]:
        """按用户 ID 查询用户"""
        cursor = await self._db.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_record(row) if row else None

    async def verify_credentials(
        self, username: str, password: str
    ) -> Optional[UserRecord]:
        """
        校验用户名密码

        Returns:
            校验成功返回用户记录，失败返回 None
        """
        user = await self.get_by_username((username or "").strip())
        if not user or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user

    async def change_password(self, user_id: str, new_password: str) -> bool:
        """修改密码"""
        if not new_password:
            return False
        new_hash = hash_password(new_password)
        now = time.time()
        cursor = await self._db.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (new_hash, now, user_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def set_active(self, user_id: str, is_active: bool) -> bool:
        """启用/停用账户"""
        cursor = await self._db.execute(
            "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
            (1 if is_active else 0, time.time(), user_id),
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def list_users(self, limit: int = 100, offset: int = 0) -> list[UserRecord]:
        """查询用户列表"""
        cursor = await self._db.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [self._row_to_record(row) for row in rows]

    async def count_users(self) -> int:
        """用户总数"""
        cursor = await self._db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0]

    # ----------------------------------------------------------------------- #
    # 工具方法
    # ----------------------------------------------------------------------- #

    def _row_to_record(self, row: aiosqlite.Row) -> UserRecord:
        """数据库行转 UserRecord"""
        return UserRecord(
            user_id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            role=row["role"],
            email=row["email"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


# --------------------------------------------------------------------------- #
# 全局单例
# --------------------------------------------------------------------------- #

_user_manager: Optional[UserManager] = None


async def get_user_manager(db_path: Optional[str] = None) -> UserManager:
    """获取全局用户管理器单例"""
    global _user_manager
    if _user_manager is None:
        from src.config import config

        # 必须使用解析后的路径（config.users_db 会把 {root} 占位符替换为项目根目录）；
        # 直接用 config.auth.users_db 会按字面量在工作目录下生成 {root}/data/users.db
        db_path = db_path or config.users_db
        _user_manager = UserManager(db_path)
        await _user_manager.initialize()
    return _user_manager
