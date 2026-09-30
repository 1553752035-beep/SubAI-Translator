# -*- coding: utf-8 -*-
"""
SubAI Translator —— 密码哈希与 JWT 工具（三期新增）
====================================================

使用 Python 标准库实现，零外部依赖：
1. 密码哈希：PBKDF2-HMAC-SHA256，20 万次迭代，随机盐
2. 访问令牌：JWT（HS256），HMAC-SHA256 签名

设计要点：
- 密码哈希采用 "pbkdf2_sha256$iterations$salt$hash" 格式，自描述、可升级
- 签名与哈希比较均使用 hmac.compare_digest，防止时序攻击
- JWT 使用 base64url 编码（无 padding），payload 含 sub/role/iat/exp
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

# PBKDF2 迭代次数（20 万次，兼顾安全与性能）
_PBKDF2_ITERATIONS = 200_000


# --------------------------------------------------------------------------- #
# base64url 编解码
# --------------------------------------------------------------------------- #

def _b64url_encode(data: bytes) -> str:
    """base64url 编码（去 padding）"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """base64url 解码（补 padding）"""
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding)


# --------------------------------------------------------------------------- #
# 密码哈希
# --------------------------------------------------------------------------- #

def hash_password(password: str) -> str:
    """
    对密码进行 PBKDF2 哈希

    Args:
        password: 明文密码

    Returns:
        自描述哈希字符串，格式 "pbkdf2_sha256$iterations$salt$hash"
    """
    if not password:
        raise ValueError("密码不能为空")

    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        _PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """
    校验明文密码是否与哈希匹配

    Args:
        password: 明文密码
        encoded: 由 hash_password 生成的哈希字符串

    Returns:
        是否匹配
    """
    if not password or not encoded:
        return False

    try:
        algo, iterations, salt, expected = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(iterations),
        )
        return hmac.compare_digest(dk.hex(), expected)
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# JWT 令牌
# --------------------------------------------------------------------------- #

def create_access_token(
    user_id: str,
    username: str,
    role: str,
    secret: str,
    expires_in_seconds: int = 86400,
) -> str:
    """
    创建 JWT 访问令牌（HS256）

    Args:
        user_id: 用户 ID
        username: 用户名
        role: 角色（user/admin）
        secret: 签名密钥
        expires_in_seconds: 过期时间（秒），默认 24 小时

    Returns:
        JWT 字符串（header.payload.signature）
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + expires_in_seconds,
    }

    header_b64 = _b64url_encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}"

    sig = hmac.new(
        secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256
    ).digest()

    return f"{signing_input}.{_b64url_encode(sig)}"


def decode_access_token(token: str, secret: str) -> Optional[dict]:
    """
    验证并解码 JWT 令牌

    Args:
        token: JWT 字符串
        secret: 签名密钥

    Returns:
        解码后的 payload 字典；签名无效或已过期时返回 None
    """
    if not token:
        return None

    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}"

        expected_sig = hmac.new(
            secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256
        ).digest()
        provided_sig = _b64url_decode(sig_b64)

        if not hmac.compare_digest(expected_sig, provided_sig):
            return None

        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))

        # 校验过期时间
        if payload.get("exp", 0) < int(time.time()):
            return None

        return payload
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
