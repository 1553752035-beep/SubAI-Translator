# -*- coding: utf-8 -*-
"""
SubAI Translator —— 备份与恢复管理器（三期新增）
================================================

职责：
- 对术语库 / 任务库 / 用户库 / 翻译缓存 / 配置快照进行一致性备份
- 列出 / 恢复 / 删除备份，自动清理过期备份

设计要点：
- SQLite 备份使用 `sqlite3.Connection.backup()` 在线备份 API，可在服务运行中
  安全地生成一致性快照，无需停机。
- 备份按时间戳目录组织，manifest.json 记录元数据与文件清单。
- 恢复仅负责文件层覆盖；涉及活动连接的重载由调用方（server.py）协调。
- 配置快照排除敏感信息（API 密钥 / JWT 密钥 / 管理员密码等）。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
from typing import Optional

from src.config import config


class BackupManager:
    """备份管理器（同步文件层操作，异步包装见下方 AsyncBackupManager）"""

    def __init__(self, backup_dir: Optional[str] = None, max_backups: int = 10):
        self.backup_dir = backup_dir or config.backup_dir
        self.max_backups = max_backups

    # ------------------------------------------------------------------ #
    # 备份
    # ------------------------------------------------------------------ #
    def create_backup(self) -> dict:
        """创建完整备份，返回 manifest 摘要"""
        os.makedirs(self.backup_dir, exist_ok=True)

        backup_id = "backup_" + time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
        dest_dir = os.path.join(self.backup_dir, backup_id)
        os.makedirs(dest_dir, exist_ok=True)

        targets = {
            "terminology": config.terminology_db,
            "tasks": config.tasks_db,
            "users": config.users_db,
            "cache": config.cache_db_path,
        }

        manifest: dict = {
            "id": backup_id,
            "created_at": time.time(),
            "files": {},
        }

        for name, src in targets.items():
            if os.path.exists(src):
                dest = os.path.join(dest_dir, f"{name}.db")
                self._backup_sqlite(src, dest)
                manifest["files"][name] = {"size": os.path.getsize(dest)}

        # 配置快照（排除敏感信息）
        snapshot = self._snapshot_config()
        config_path = os.path.join(dest_dir, "config.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        manifest["files"]["config"] = {"size": os.path.getsize(config_path)}

        # 写 manifest
        with open(os.path.join(dest_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        # 自动清理超出数量的旧备份
        self.cleanup_old_backups()
        return manifest

    def _backup_sqlite(self, src: str, dest: str) -> None:
        """SQLite 在线一致性备份"""
        src_conn = sqlite3.connect(src)
        try:
            dest_conn = sqlite3.connect(dest)
            try:
                src_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            src_conn.close()

    def _snapshot_config(self) -> dict:
        """导出配置快照（排除敏感信息，便于恢复后参考）"""
        return {
            "llm_mode": config.llm.mode,
            "llm_local_url": config.llm.local_url,
            "llm_local_model": config.llm.local_model,
            "llm_cloud_url": config.llm.cloud_url,
            "llm_cloud_model": config.llm.cloud_model,
            "asr_device": config.asr.device,
            "asr_compute_type": config.asr.compute_type,
            "ocr_sample_fps": config.ocr.sample_fps,
            "ocr_min_score": config.ocr.min_score,
            "server_host": config.server.host,
            "server_port": config.server.port,
            "max_chars": config.max_chars,
            "max_dur": config.max_dur,
        }

    # ------------------------------------------------------------------ #
    # 查询 / 删除
    # ------------------------------------------------------------------ #
    def list_backups(self) -> list[dict]:
        """列出所有备份（按创建时间倒序）"""
        if not os.path.isdir(self.backup_dir):
            return []
        backups = []
        for name in os.listdir(self.backup_dir):
            manifest_path = os.path.join(self.backup_dir, name, "manifest.json")
            if os.path.isfile(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        backups.append(json.load(f))
                except (OSError, json.JSONDecodeError):
                    continue
        backups.sort(key=lambda b: b.get("created_at", 0), reverse=True)
        return backups

    def delete_backup(self, backup_id: str) -> bool:
        """删除指定备份"""
        backup_dir = os.path.join(self.backup_dir, backup_id)
        if os.path.isdir(backup_dir):
            shutil.rmtree(backup_dir)
            return True
        return False

    def cleanup_old_backups(self) -> int:
        """清理超出 max_backups 的旧备份，返回清理数量"""
        backups = self.list_backups()
        removed = 0
        for backup in backups[self.max_backups:]:
            if self.delete_backup(backup["id"]):
                removed += 1
        return removed

    # ------------------------------------------------------------------ #
    # 恢复
    # ------------------------------------------------------------------ #
    def restore_backup(self, backup_id: str, targets: Optional[list[str]] = None) -> dict:
        """
        恢复备份（文件层覆盖）

        Args:
            backup_id: 备份 ID
            targets: 需要恢复的目标列表（terminology/tasks/users/cache），None 表示全部

        Returns:
            {"backup_id": ..., "restored": [...]}

        Note:
            调用方需在恢复前关闭对应管理器连接，恢复后重新初始化。
        """
        manifest_path = os.path.join(self.backup_dir, backup_id, "manifest.json")
        if not os.path.isfile(manifest_path):
            raise FileNotFoundError(f"备份不存在：{backup_id}")

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        restore_map = {
            "terminology": config.terminology_db,
            "tasks": config.tasks_db,
            "users": config.users_db,
            "cache": config.cache_db_path,
        }

        restored = []
        for name, dest in restore_map.items():
            if targets and name not in targets:
                continue
            src = os.path.join(self.backup_dir, backup_id, f"{name}.db")
            if os.path.isfile(src):
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(src, dest)
                restored.append(name)

        return {"backup_id": backup_id, "restored": restored}


class AsyncBackupManager:
    """备份管理器异步包装（供 FastAPI 接口调用）"""

    def __init__(self, backup_dir: Optional[str] = None, max_backups: int = 10):
        self._sync = BackupManager(backup_dir, max_backups)

    async def create_backup(self) -> dict:
        import asyncio
        return await asyncio.to_thread(self._sync.create_backup)

    async def list_backups(self) -> list[dict]:
        import asyncio
        return await asyncio.to_thread(self._sync.list_backups)

    async def delete_backup(self, backup_id: str) -> bool:
        import asyncio
        return await asyncio.to_thread(self._sync.delete_backup, backup_id)

    async def restore_backup(self, backup_id: str, targets: Optional[list[str]] = None) -> dict:
        import asyncio
        return await asyncio.to_thread(self._sync.restore_backup, backup_id, targets)
