# -*- coding: utf-8 -*-
"""
SubAI Translator —— 请求指标中间件（三期：监控与告警）
========================================================

对每个 HTTP 请求记录：
1. request_total：请求计数（按 method / path / status_code 标签）
2. request_duration_seconds：请求延迟直方图

指标写入进程内 MetricsRegistry，供 /api/metrics 暴露；
指标路径自身与健康检查不计入，避免抓取探测污染延迟统计。
"""
from __future__ import annotations

import time

from starlette.requests import Request

from .metrics import REGISTRY

# 不计入指标统计的路径前缀（监控抓取 / 健康探测）
_EXEMPT_PREFIXES = ("/api/metrics", "/api/health")


def _is_exempt(path: str) -> bool:
    return any(path.startswith(p) for p in _EXEMPT_PREFIXES)


async def request_metrics_middleware(request: Request, call_next):
    """记录每个请求的计数与延迟"""
    path = request.url.path
    start = time.perf_counter()

    if _is_exempt(path):
        return await call_next(request)

    response = await call_next(request)

    elapsed = time.perf_counter() - start
    labels = {
        "method": request.method,
        "path": path,
        "status_code": str(response.status_code),
    }
    REGISTRY.inc("subai_request_total", labels=labels)
    REGISTRY.observe("subai_request_duration_seconds", elapsed)

    return response
