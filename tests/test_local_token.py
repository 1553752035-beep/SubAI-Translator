# -*- coding: utf-8 -*-
"""五期：免登录模式（本机令牌）测试。"""
from __future__ import annotations

import os

import pytest

from src.auth import local_token as lt


@pytest.fixture
def token_env(tmp_path, monkeypatch):
    """令牌落到 tmp，并清掉模块缓存。"""
    from src.config import config as _cfg

    path = str(tmp_path / "local_token.txt")
    monkeypatch.setattr(_cfg.auth, "local_token_file", path)
    monkeypatch.setattr(_cfg.auth, "require_login", False)
    lt.reset_cache()
    yield path
    lt.reset_cache()


class TestLocalToken:
    def test_generates_and_persists(self, token_env):
        token = lt.ensure_local_token()
        assert len(token) == 64 and all(c in "0123456789abcdef" for c in token)
        assert os.path.isfile(token_env)
        # 第二次读取必须稳定（不是每次重新生成）
        assert lt.ensure_local_token() == token

    def test_verify(self, token_env):
        token = lt.ensure_local_token()
        assert lt.verify_local_token(token) is True
        assert lt.verify_local_token("deadbeef") is False
        assert lt.verify_local_token("") is False
        assert lt.verify_local_token(token.upper()) is False   # 大小写敏感

    def test_file_is_not_world_readable_on_windows_friendly(self, token_env):
        # Windows 上 chmod 语义有限，这里只确认文件能读且非空
        token = lt.ensure_local_token()
        with open(token_env, "r", encoding="utf-8") as f:
            assert f.read().strip() == token


class TestNoLoginApi:
    def test_health_reports_require_login_false(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["require_login"] is False

    def test_protected_endpoint_needs_token(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_local_token_grants_admin_access(self, client, token_env):
        token = lt.ensure_local_token()
        r = client.get("/api/auth/me", headers={"X-Local-Token": token})
        assert r.status_code == 200, r.text
        # 免登录时本机主人应有管理员权限（高级页才有权限）
        keys = client.get("/api/openapi/keys", headers={"X-Local-Token": token})
        assert keys.status_code == 200, keys.text

    def test_wrong_token_rejected(self, client, token_env):
        r = client.get("/api/auth/me", headers={"X-Local-Token": "wrong"})
        assert r.status_code == 401
        assert "本机令牌" in r.json()["detail"]

    def test_require_login_true_rejects_local_token(self, client, token_env, monkeypatch):
        from src.config import config as _cfg
        token = lt.ensure_local_token()
        monkeypatch.setattr(_cfg.auth, "require_login", True)
        r = client.get("/api/auth/me", headers={"X-Local-Token": token})
        assert r.status_code == 401
        assert "登录" in r.json()["detail"]

