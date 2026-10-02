# -*- coding: utf-8 -*-
"""
SubAI Translator —— FastAPI 认证依赖（三期新增）
================================================

提供可复用的认证依赖，供 API 路由注入当前用户：
1. get_current_user：解析 Bearer JWT，返回当前登录用户
2. get_current_admin：要求当前用户为 admin 角色

用法示例：
    @app.get("/api/me")
    async def me(current_user: UserRecord = Depends(get_current_user)):
        return current_user.to_dict()
"""
from __future__ import annotations

import hmac
import time
from typing import Optional

from fastapi import Depends, Header, HTTPException

from src.config import config
from .local_token import verify_local_token
from .security import decode_access_token
from .users import UserRecord, get_user_manager


# 服务账户 ID（API Key 认证映射的虚拟用户，非 hex 形式不会与真实 uuid 冲突）
_SERVICE_ACCOUNT_ID = "service-account-api-key"


def _api_key_matches(provided: str, keys: list[str]) -> bool:
    """常量时间比较 API Key（防时序攻击）"""
    for key in keys:
        if hmac.compare_digest(provided.encode("utf-8"), key.encode("utf-8")):
            return True
    return False


def _make_service_account() -> UserRecord:
    """构造 API Key 认证对应的服务账户（admin 角色，用于程序化/服务间访问）"""
    return UserRecord(
        user_id=_SERVICE_ACCOUNT_ID,
        username="api-key",
        password_hash="",
        role="admin",
        email=None,
        is_active=True,
        created_at=time.time(),
        updated_at=time.time(),
    )


_LOCAL_OWNER_FALLBACK_ID = "local-owner"


async def _local_owner() -> UserRecord:
    """本机主人（免登录模式下的当前用户）。

    优先返回库里已有的管理员 —— 这样**历史任务与术语库仍然看得见**
    （否则老数据会因 user_id 不同而从界面上"消失"）；
    库里还没有管理员时，用合成账号兜底。
    """
    try:
        manager = await get_user_manager()
        for user in await manager.list_users(limit=100):
            if user.role == "admin" and user.is_active:
                return user
    except Exception as e:  # noqa: BLE001
        logger_debug = getattr(__import__("logging").getLogger(__name__), "debug")
        logger_debug("读取本机管理员失败，使用兜底账号: %r", e)
    return UserRecord(
        user_id=_LOCAL_OWNER_FALLBACK_ID,
        username="本机用户",
        password_hash="",
        role="admin",
        email=None,
        is_active=True,
        created_at=time.time(),
        updated_at=time.time(),
    )


async def get_current_user(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_local_token: Optional[str] = Header(None, alias="X-Local-Token"),
) -> UserRecord:
    """
    解析当前用户，支持两种认证方式：

    1. API Key：`X-API-Key: <key>` 请求头，匹配 config.security.api_keys 任一即视为
       服务账户（admin），用于程序化访问或服务间调用。
    2. JWT：`Authorization: Bearer <token>`，由登录接口签发。

    优先级：提供了 X-API-Key 时按 API Key 校验（无效则直接拒绝，不回落 JWT）。

    Raises:
        HTTPException(401): 令牌缺失、无效、过期或用户不存在/停用
    """
    # 五期：本机令牌 —— 免登录模式（默认）。令牌正确即视为本机主人（admin）。
    if x_local_token:
        if config.auth.require_login:
            raise HTTPException(status_code=401, detail="已启用登录模式，请使用账号登录")
        if verify_local_token(x_local_token):
            return await _local_owner()
        raise HTTPException(status_code=401, detail="本机令牌无效")

    # API Key 认证
    if x_api_key:
        if config.security.api_keys and _api_key_matches(x_api_key, config.security.api_keys):
            return _make_service_account()
        raise HTTPException(status_code=401, detail="API 密钥无效")

    # JWT 认证
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    token = authorization[7:].strip()
    payload = decode_access_token(token, config.auth.jwt_secret)
    if not payload:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")

    user_manager = await get_user_manager()
    user = await user_manager.get_by_id(payload.get("sub", ""))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")

    return user


async def get_current_admin(
    current_user: UserRecord = Depends(get_current_user),
) -> UserRecord:
    """
    要求当前用户为管理员

    Raises:
        HTTPException(403): 非管理员访问
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return current_user
