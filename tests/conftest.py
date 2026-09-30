# -*- coding: utf-8 -*-
"""
SubAI Translator —— 测试共享夹具
==================================

把 API 集成测试的 client / auth_headers 提到这里，供多个测试文件复用
（原先只在 test_api_server.py 内定义，新测试文件无法共享）。
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_API_TESTS"),
    reason="需要 RUN_API_TESTS=1 才执行 API 集成测试",
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    """用临时目录覆盖 DB 路径后创建 TestClient（with 上下文触发 lifespan）"""
    from src.config import config as _cfg
    term_path = str(tmp_path / "term.db")
    cache_path = str(tmp_path / "cache.db")
    users_path = str(tmp_path / "users.db")
    monkeypatch.setattr(_cfg.paths, "terminology_db", term_path)
    monkeypatch.setattr(_cfg.cache, "db_path", cache_path)
    monkeypatch.setattr(_cfg.paths, "uploads_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(_cfg.auth, "users_db", users_path)
    monkeypatch.setattr(_cfg.paths, "tasks_db", str(tmp_path / "tasks.db"))
    monkeypatch.setattr(_cfg.backup, "backup_dir", str(tmp_path / "backups"))
    # 隔离输出目录：否则测试产物会写进仓库的 output/
    monkeypatch.setattr(_cfg.paths, "out_dir", str(tmp_path / "output"))

    # 重设单例（保证用最新的路径初始化）
    from src.db import tasks as tasks_mod
    tasks_mod.task_manager = None
    from src.cache import translation_cache as cache_mod
    cache_mod.translation_cache = None
    from src.queue import task_queue as queue_mod
    queue_mod.task_queue = None
    from src.auth import users as users_mod
    users_mod._user_manager = None
    # 重置限流器（模块级单例，跨 TestClient 累积会误伤后续测试）
    from src.security import middleware as security_mw
    security_mw._rate_limiter_cache.clear()

    from fastapi.testclient import TestClient
    from src.api.server import app
    import src.api.server as server_mod
    # 同步 server 模块的 config 引用，防止 reload_config 后引用分离导致 monkeypatch 失效
    server_mod.config = _cfg

    # 用 with 触发 lifespan（各管理器都在 lifespan 里初始化，并自动创建默认 admin）
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    """登录默认 admin，返回带 Bearer Token 的请求头"""
    from src.config import config as _cfg
    r = client.post("/api/auth/login", json={
        "username": _cfg.auth.admin_username,
        "password": _cfg.auth.admin_password,
    })
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
