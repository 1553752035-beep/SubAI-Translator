# -*- coding: utf-8 -*-
"""
SubAI Translator —— 备份与恢复测试（三期新增）
==================================================

覆盖 BackupManager 文件层逻辑：
- 创建备份（manifest / 各数据库文件 / 配置快照）
- 备份文件内容与源一致
- 列表排序（最新在前）
- 删除备份
- 自动清理超出数量的旧备份
- 恢复备份（覆盖源文件）

说明：备份/恢复的 API 集成测试（管理员接口 + 管理器重载）见
tests/test_api_server.py 的 TestBackupApi。
"""
from __future__ import annotations

import json
import os
import sqlite3

import pytest

from src.backup.manager import BackupManager


def _make_db(path: str, table: str = "t", rows: int = 3) -> None:
    """创建带测试数据的 SQLite 数据库"""
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, name TEXT)")
    for i in range(rows):
        conn.execute(f"INSERT INTO {table} (name) VALUES ('row{i}')")
    conn.commit()
    conn.close()


def _count_rows(path: str, table: str = "t") -> int:
    conn = sqlite3.connect(path)
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    """设置临时数据库路径，隔离测试（避免污染真实数据）"""
    from src.config import config as _cfg

    term_db = str(tmp_path / "terminology.db")
    tasks_db = str(tmp_path / "tasks.db")
    cache_db = str(tmp_path / "cache.db")
    users_db = str(tmp_path / "users.db")

    _make_db(term_db)
    _make_db(tasks_db)
    _make_db(cache_db)
    _make_db(users_db)

    monkeypatch.setattr(_cfg.paths, "terminology_db", term_db)
    monkeypatch.setattr(_cfg.paths, "tasks_db", tasks_db)
    monkeypatch.setattr(_cfg.cache, "db_path", cache_db)
    monkeypatch.setattr(_cfg.auth, "users_db", users_db)

    return tmp_path


class TestBackupManager:
    def test_create_backup(self, db_env):
        backup_dir = db_env / "backups"
        mgr = BackupManager(str(backup_dir), max_backups=5)
        manifest = mgr.create_backup()

        assert manifest["id"].startswith("backup_")
        assert set(manifest["files"]) == {"terminology", "tasks", "users", "cache", "config"}

        dest = backup_dir / manifest["id"]
        assert (dest / "terminology.db").exists()
        assert (dest / "tasks.db").exists()
        assert (dest / "users.db").exists()
        assert (dest / "cache.db").exists()
        assert (dest / "config.json").exists()
        assert (dest / "manifest.json").exists()

        # 备份文件内容与源一致（在线一致性备份）
        assert _count_rows(str(dest / "tasks.db")) == 3
        assert _count_rows(str(dest / "terminology.db")) == 3

    def test_config_snapshot_excludes_secrets(self, db_env):
        from src.config import config as _cfg

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(_cfg.security, "api_keys", ["secret-key-123"])
        monkeypatch.setattr(_cfg.auth, "jwt_secret", "super-secret-jwt")

        backup_dir = db_env / "backups"
        mgr = BackupManager(str(backup_dir), max_backups=5)
        manifest = mgr.create_backup()

        config_path = backup_dir / manifest["id"] / "config.json"
        with open(config_path, "r", encoding="utf-8") as f:
            snapshot = json.load(f)

        # 敏感信息不应出现在配置快照中
        snapshot_text = json.dumps(snapshot)
        assert "secret-key-123" not in snapshot_text
        assert "super-secret-jwt" not in snapshot_text
        # 非敏感配置应保留
        assert "llm_mode" in snapshot

    def test_list_backups_sorted(self, db_env):
        backup_dir = db_env / "backups"
        mgr = BackupManager(str(backup_dir), max_backups=10)
        b1 = mgr.create_backup()
        b2 = mgr.create_backup()
        b3 = mgr.create_backup()

        backups = mgr.list_backups()
        assert len(backups) == 3
        # 最新创建的排在最前
        assert backups[0]["id"] == b3["id"]
        assert backups[1]["id"] == b2["id"]
        assert backups[2]["id"] == b1["id"]

    def test_delete_backup(self, db_env):
        backup_dir = db_env / "backups"
        mgr = BackupManager(str(backup_dir), max_backups=10)
        manifest = mgr.create_backup()

        assert mgr.delete_backup(manifest["id"]) is True
        assert not (backup_dir / manifest["id"]).exists()
        assert mgr.delete_backup(manifest["id"]) is False  # 二次删除返回 False

    def test_cleanup_old_backups(self, db_env):
        backup_dir = db_env / "backups"
        mgr = BackupManager(str(backup_dir), max_backups=2)
        for _ in range(4):
            mgr.create_backup()

        backups = mgr.list_backups()
        assert len(backups) == 2  # 只保留最近 2 份

    def test_restore_backup(self, db_env):
        from src.config import config as _cfg

        backup_dir = db_env / "backups"
        mgr = BackupManager(str(backup_dir), max_backups=5)
        manifest = mgr.create_backup()

        # 修改源数据库（新增 10 行）
        conn = sqlite3.connect(_cfg.tasks_db)
        for i in range(10):
            conn.execute("INSERT INTO t (name) VALUES ('extra')")
        conn.commit()
        conn.close()
        assert _count_rows(_cfg.tasks_db) == 13

        # 恢复备份
        result = mgr.restore_backup(manifest["id"], targets=["tasks"])
        assert result["restored"] == ["tasks"]
        assert _count_rows(_cfg.tasks_db) == 3  # 回到备份时状态

    def test_restore_missing_backup_raises(self, db_env):
        backup_dir = db_env / "backups"
        mgr = BackupManager(str(backup_dir), max_backups=5)
        with pytest.raises(FileNotFoundError):
            mgr.restore_backup("backup_not_exist")
