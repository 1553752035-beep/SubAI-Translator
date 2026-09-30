# -*- coding: utf-8 -*-
"""
SubAI Translator —— 安全中间件（三期新增）
============================================

提供三个纯 ASGI 中间件，按需挂载到 FastAPI 应用：
1. security_headers：注入安全响应头（防点击劫持/嗅探/XSS）
2. ip_filter：IP 白名单 / 黑名单过滤
3. rate_limit：全局频率限制（认证接口更严格，防暴力破解）

设计要点：
- 配置通过 src.config 动态读取，支持 /api/config/reload 热更新
- 限流器按当前配置参数缓存，参数变化时自动重建
- 健康检查 / 文档 / OpenAPI 路由豁免限流，避免监控探针被误伤
"""
from __future__ import annotations

import logging
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse

from src.security.rate_limit import SlidingWindowRateLimiter

logger = logging.getLogger(__name__)


def _get_config():
    """动态获取当前配置（避免 reload 后引用失效）"""
    import src.config as cfg_mod
    return cfg_mod.config


# --------------------------------------------------------------------------- #
# 限流器缓存（按参数重建）
# --------------------------------------------------------------------------- #

_rate_limiter_cache: dict[str, dict] = {}


def _get_rate_limiter(kind: str) -> SlidingWindowRateLimiter:
    """按配置参数获取（必要时重建）限流器实例"""
    cfg = _get_config().security
    if kind == "auth":
        params = (cfg.auth_rate_limit_requests, cfg.auth_rate_limit_window_seconds)
    else:
        params = (cfg.rate_limit_requests, cfg.rate_limit_window_seconds)

    entry = _rate_limiter_cache.get(kind)
    if entry is None or entry.get("params") != params:
        _rate_limiter_cache[kind] = {
            "params": params,
            "limiter": SlidingWindowRateLimiter(max_requests=params[0], window_seconds=params[1]),
        }
    return _rate_limiter_cache[kind]["limiter"]


def _client_ip(request: Request) -> str:
    """获取客户端 IP（优先 X-Forwarded-For，回退到直连地址）"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# 豁免限流的路径前缀（监控探针 / 文档 / OpenAPI）
_RATE_LIMIT_EXEMPT_PREFIXES = (
    "/api/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)


def _is_exempt(path: str) -> bool:
    return any(path.startswith(p) for p in _RATE_LIMIT_EXEMPT_PREFIXES)


# --------------------------------------------------------------------------- #
# 中间件
# --------------------------------------------------------------------------- #

async def security_headers_middleware(request: Request, call_next):
    """注入安全响应头"""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-XSS-Protection", "1; mode=block")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if _get_config().security.enable_https:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


async def ip_filter_middleware(request: Request, call_next):
    """IP 白名单 / 黑名单过滤"""
    cfg = _get_config().security
    if not cfg.ip_whitelist and not cfg.ip_blacklist:
        return await call_next(request)

    client_ip = _client_ip(request)

    if cfg.ip_blacklist and client_ip in cfg.ip_blacklist:
        logger.warning("拒绝黑名单 IP 访问: %s", client_ip)
        return JSONResponse(status_code=403, content={"detail": "IP 被禁止访问"})

    if cfg.ip_whitelist and client_ip not in cfg.ip_whitelist:
        logger.warning("拒绝非白名单 IP 访问: %s", client_ip)
        return JSONResponse(status_code=403, content={"detail": "IP 不在白名单"})

    return await call_next(request)


async def rate_limit_middleware(request: Request, call_next):
    """全局频率限制（认证接口更严格）"""
    cfg = _get_config().security
    if not cfg.rate_limit_enabled or _is_exempt(request.url.path):
        return await call_next(request)

    path = request.url.path
    is_auth = path.startswith("/api/auth/login") or path.startswith("/api/auth/register")
    limiter = _get_rate_limiter("auth" if is_auth else "api")
    key = _client_ip(request)

    if not limiter.allow(key):
        logger.warning("触发频率限制: ip=%s path=%s", key, path)
        return JSONResponse(
            status_code=429,
            content={"detail": "请求过于频繁，请稍后再试"},
            headers={"Retry-After": str(limiter.window_seconds)},
        )
    return await call_next(request)
