# -*- coding: utf-8 -*-
"""
SubAI Translator —— 频率限制器（三期新增）
============================================

内存滑动窗口限流，纯标准库 + asyncio 实现，零外部依赖。

设计要点：
- 每个 key（客户端 IP / 认证接口）维护一个时间戳双端队列，
  每次请求先淘汰窗口外的时间戳，再判断是否超限。
- 单实例内存态，适合单机/单容器部署；多实例场景建议替换为 Redis。
- 提供 `allow()` 同步判断 + `check()` 异步统一入口，便于中间件调用。
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import DefaultDict


class SlidingWindowRateLimiter:
    """
    滑动窗口限流器

    Args:
        max_requests: 窗口内允许的最大请求数
        window_seconds: 时间窗口长度（秒）
    """

    def __init__(self, max_requests: int, window_seconds: float):
        if max_requests <= 0:
            raise ValueError("max_requests 必须大于 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds 必须大于 0")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: DefaultDict[str, deque] = defaultdict(deque)

    def allow(self, key: str, now: float | None = None) -> bool:
        """
        判断 key 是否被允许本次请求（并记录本次请求时间戳）

        Args:
            key: 限流维度（如客户端 IP）
            now: 当前时间戳（默认 time.time()，测试时可注入）

        Returns:
            True 表示允许；False 表示超限拒绝
        """
        now = time.time() if now is None else now
        window_start = now - self.window_seconds
        q = self._timestamps[key]

        # 淘汰窗口外的旧时间戳
        while q and q[0] <= window_start:
            q.popleft()

        if len(q) >= self.max_requests:
            return False

        q.append(now)
        return True

    def reset(self, key: str | None = None) -> None:
        """清空计数（key 为 None 时清空全部）"""
        if key is None:
            self._timestamps.clear()
        else:
            self._timestamps.pop(key, None)

    def current_count(self, key: str, now: float | None = None) -> int:
        """返回 key 在当前窗口内的请求数（不记录本次）"""
        now = time.time() if now is None else now
        window_start = now - self.window_seconds
        q = self._timestamps[key]
        return sum(1 for ts in q if ts > window_start)
