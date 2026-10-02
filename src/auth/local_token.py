# -*- coding: utf-8 -*-
"""五期：本机令牌（免登录模式的核心）。

设计取舍：
- 界面**不做登录**（开源单机工具不需要用户体系）；
- 但后端**不是裸奔**：每个请求都要带一个只存在本机的令牌；
- 令牌首次启动自动生成在 data/local_token.txt（仅当前用户可读写），
  Tauri 端读这个文件注入前端；外部程序拿不到它就调不动后端。
- 想恢复账号登录：把 SUBAI_AUTH_REQUIRE_LOGIN 设为 true（整套登录代码都还在）。
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets

from src.config import config

logger = logging.getLogger(__name__)

_cache: dict = {}


def _token_path() -> str:
    raw = config.auth.local_token_file or os.path.join("{root}", "data", "local_token.txt")
    return config.paths.resolve(raw)


def ensure_local_token(path: str = "") -> str:
    """读取本机令牌；不存在则生成并落盘。返回令牌内容。"""
    target = path or _token_path()
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if os.path.isfile(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                token = f.read().strip()
            if token:
                _cache[target] = token
                return token
        except OSError as e:
            logger.warning("读取本机令牌失败，将重新生成: %r", e)
    token = secrets.token_hex(32)
    with open(target, "w", encoding="utf-8") as f:
        f.write(token)
    try:
        os.chmod(target, 0o600)   # 只有当前用户能读
    except OSError:
        pass
    _cache[target] = token
    logger.info("已生成本机令牌（免登录模式）: %s", target)
    return token


def get_local_token() -> str:
    target = _token_path()
    if target in _cache:
        return _cache[target]
    return ensure_local_token(target)


def verify_local_token(provided: str) -> bool:
    """常量时间比对本机令牌。"""
    if not provided:
        return False
    expected = get_local_token()
    return bool(expected) and hmac.compare_digest(provided.strip(), expected)


def reset_cache() -> None:
    """仅供测试：清掉缓存，让下次读取重新落盘。"""
    _cache.clear()
