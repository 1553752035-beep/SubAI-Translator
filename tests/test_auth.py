# -*- coding: utf-8 -*-
"""
SubAI Translator —— 认证模块单元测试
======================================

覆盖：
1. 密码哈希：哈希/校验、盐随机性、非法输入
2. JWT：往返、错误密钥、过期、篡改、非法令牌
3. 用户管理：创建/查询、用户名查重、凭据校验、改密、账户停用
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import src.auth.users as users_mod
from src.auth.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from src.auth.users import UserManager
from src.config import config as _cfg


# --------------------------------------------------------------------------- #
# 密码哈希
# --------------------------------------------------------------------------- #

class TestPasswordHashing:
    def test_hash_and_verify(self):
        encoded = hash_password("mysecret123")
        assert encoded.startswith("pbkdf2_sha256$")
        assert verify_password("mysecret123", encoded) is True

    def test_wrong_password_rejected(self):
        encoded = hash_password("correct-horse")
        assert verify_password("wrong-horse", encoded) is False

    def test_hash_is_salted(self):
        """相同密码两次哈希结果不同（随机盐）"""
        assert hash_password("same-password") != hash_password("same-password")

    def test_empty_password_raises(self):
        with pytest.raises(ValueError):
            hash_password("")

    def test_verify_invalid_inputs(self):
        assert verify_password("x", "not-a-valid-hash") is False
        assert verify_password("", "") is False
        assert verify_password("x", "") is False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #

class TestJWT:
    SECRET = "unit-test-secret"

    def test_roundtrip(self):
        token = create_access_token("u1", "alice", "user", self.SECRET)
        payload = decode_access_token(token, self.SECRET)
        assert payload is not None
        assert payload["sub"] == "u1"
        assert payload["username"] == "alice"
        assert payload["role"] == "user"

    def test_wrong_secret_rejected(self):
        token = create_access_token("u1", "alice", "user", self.SECRET)
        assert decode_access_token(token, "other-secret") is None

    def test_expired_token_rejected(self):
        token = create_access_token(
            "u1", "alice", "user", self.SECRET, expires_in_seconds=-1
        )
        assert decode_access_token(token, self.SECRET) is None

    def test_tampered_payload_rejected(self):
        token = create_access_token("u1", "alice", "user", self.SECRET)
        header_b64, payload_b64, sig_b64 = token.split(".")
        # 篡改 payload 的最后一个字符
        flipped = payload_b64[:-1] + ("A" if payload_b64[-1] != "A" else "B")
        tampered = f"{header_b64}.{flipped}.{sig_b64}"
        assert decode_access_token(tampered, self.SECRET) is None

    def test_invalid_token_formats(self):
        assert decode_access_token("not-a-jwt", self.SECRET) is None
        assert decode_access_token("", self.SECRET) is None
        assert decode_access_token("a.b.c.d", self.SECRET) is None


# --------------------------------------------------------------------------- #
# 用户管理
# --------------------------------------------------------------------------- #

class TestUserManager:
    @staticmethod
    async def _make_manager(tmp_path) -> UserManager:
        mgr = UserManager(str(tmp_path / "users.db"))
        await mgr.initialize()
        return mgr

    @pytest.mark.asyncio
    async def test_create_and_get(self, tmp_path):
        mgr = await self._make_manager(tmp_path)
        try:
            user = await mgr.create_user("alice", "password123")
            assert user.user_id
            assert user.username == "alice"
            assert user.role == "user"
            # 密码以哈希存储，不含明文
            assert user.password_hash != "password123"
            assert user.password_hash.startswith("pbkdf2_sha256$")

            fetched = await mgr.get_by_username("alice")
            assert fetched is not None
            assert fetched.user_id == user.user_id

            by_id = await mgr.get_by_id(user.user_id)
            assert by_id is not None
            assert by_id.username == "alice"
        finally:
            await mgr.close()

    @pytest.mark.asyncio
    async def test_duplicate_username_rejected(self, tmp_path):
        mgr = await self._make_manager(tmp_path)
        try:
            await mgr.create_user("alice", "password123")
            with pytest.raises(ValueError):
                await mgr.create_user("alice", "other456")
        finally:
            await mgr.close()

    @pytest.mark.asyncio
    async def test_verify_credentials(self, tmp_path):
        mgr = await self._make_manager(tmp_path)
        try:
            await mgr.create_user("bob", "correct-pw")
            assert await mgr.verify_credentials("bob", "correct-pw") is not None
            assert await mgr.verify_credentials("bob", "wrong-pw") is None
            assert await mgr.verify_credentials("nobody", "correct-pw") is None
        finally:
            await mgr.close()

    @pytest.mark.asyncio
    async def test_change_password(self, tmp_path):
        mgr = await self._make_manager(tmp_path)
        try:
            user = await mgr.create_user("carol", "old-password")
            assert await mgr.change_password(user.user_id, "new-password") is True
            assert await mgr.verify_credentials("carol", "new-password") is not None
            assert await mgr.verify_credentials("carol", "old-password") is None
        finally:
            await mgr.close()

    @pytest.mark.asyncio
    async def test_deactivate_account(self, tmp_path):
        mgr = await self._make_manager(tmp_path)
        try:
            user = await mgr.create_user("dave", "password123")
            await mgr.set_active(user.user_id, False)
            # 停用后无法登录
            assert await mgr.verify_credentials("dave", "password123") is None
        finally:
            await mgr.close()

    @pytest.mark.asyncio
    async def test_list_and_count(self, tmp_path):
        mgr = await self._make_manager(tmp_path)
        try:
            await mgr.create_user("u1", "password1")
            await mgr.create_user("u2", "password2", role="admin")
            assert await mgr.count_users() == 2
            users = await mgr.list_users()
            assert len(users) == 2
        finally:
            await mgr.close()

    @pytest.mark.asyncio
    async def test_get_user_manager_resolves_root_placeholder(self, tmp_path, monkeypatch):
        """回归：单例必须使用解析后的 config.users_db，而不是未解析的 config.auth.users_db。
        否则会按字面量在工作目录下创建 {root}/data/users.db。"""
        monkeypatch.setattr(_cfg.paths, "root", str(tmp_path))
        monkeypatch.setattr(
            _cfg.auth, "users_db", os.path.join("{root}", "data", "users.db")
        )
        monkeypatch.setattr(users_mod, "_user_manager", None)

        mgr = await users_mod.get_user_manager()
        try:
            expected = Path(tmp_path) / "data" / "users.db"
            assert Path(mgr.db_path) == expected
            assert expected.exists()
            assert "{root}" not in mgr.db_path
        finally:
            await mgr.close()
            monkeypatch.setattr(users_mod, "_user_manager", None)
