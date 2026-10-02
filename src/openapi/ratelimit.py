# -*- coding: utf-8 -*-
"""四期 4.5 深化：按 API 密钥限流。

复用 'src.security.rate_limit.SlidingWindowRateLimiter'（内存滑动窗口，零依赖）：
不另写一套限流算法，避免"两套规则、两种行为"。

约定：
- 每个密钥可有自己的上限（api_keys.rate_limit），为空则用配置默认值；
- 上限 <= 0 表示**不限流**（便于内部脚本或压测）；
- 多实例部署时内存态限流不共享 —— 这一点在文档里如实标注（可换 Redis）。
"""
from __future__ import annotations

from typing import Optional

from src.config import config
from src.security.rate_limit import SlidingWindowRateLimiter


class KeyRateLimiter:
    """按密钥限流；不同上限各自持有窗口实例，key 维度互不影响。"""

    def __init__(self, default_limit: Optional[int] = None,
                 window: Optional[float] = None) -> None:
        self.default_limit = int(
            config.openapi.key_rate_limit if default_limit is None else default_limit
        )
        self.window = float(
            config.openapi.key_rate_window if window is None else window
        )
        self._limiters: dict = {}

    def _limiter(self, limit: int) -> SlidingWindowRateLimiter:
        limiter = self._limiters.get(limit)
        if limiter is None:
            limiter = SlidingWindowRateLimiter(limit, self.window)
            self._limiters[limit] = limiter
        return limiter

    def effective_limit(self, limit: Optional[int] = None) -> int:
        # 注意：0 是合法值（表示不限流），只有 None 才回落到默认上限。
        # 早期写成 "if limit else default" 会把 0 当成未设置 —— 已修正。
        if limit is None:
            return self.default_limit
        return int(limit)

    def allow(self, key_id: str, limit: Optional[int] = None) -> bool:
        """是否允许本次请求（并计入窗口）。上限 <= 0 视为不限流。"""
        effective = self.effective_limit(limit)
        if effective <= 0:
            return True
        return self._limiter(effective).allow(key_id)

    def remaining(self, key_id: str, limit: Optional[int] = None) -> int:
        """当前窗口剩余额度；-1 表示不限流。"""
        effective = self.effective_limit(limit)
        if effective <= 0:
            return -1
        used = self._limiter(effective).current_count(key_id)
        return max(0, effective - used)

    def reset(self, key_id: Optional[str] = None) -> None:
        for limiter in self._limiters.values():
            limiter.reset(key_id)


_limiter: Optional[KeyRateLimiter] = None


def get_key_limiter() -> KeyRateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = KeyRateLimiter()
    return _limiter
