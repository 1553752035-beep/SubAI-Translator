# -*- coding: utf-8 -*-
"""
SubAI Translator —— 安全加固单元测试（三期新增）
====================================================

覆盖：
1. 频率限制器（滑动窗口逻辑、超限拒绝、窗口滑动、重置、非法参数）
2. API Key 辅助函数（常量时间比较、服务账户构造）

说明：中间件 / API Key 端到端认证测试在 tests/test_api_server.py 中
（需要 RUN_API_TESTS=1，复用完整 lifespan 与 client fixture）。
"""
from __future__ import annotations

import pytest

from src.security.rate_limit import SlidingWindowRateLimiter


# --------------------------------------------------------------------------- #
# 频率限制器
# --------------------------------------------------------------------------- #
class TestSlidingWindowRateLimiter:
    def test_allow_under_limit(self):
        rl = SlidingWindowRateLimiter(max_requests=3, window_seconds=60)
        assert rl.allow("ip1", now=100) is True
        assert rl.allow("ip1", now=100) is True
        assert rl.allow("ip1", now=100) is True

    def test_reject_over_limit(self):
        rl = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
        assert rl.allow("ip1", now=100) is True
        assert rl.allow("ip1", now=100) is True
        assert rl.allow("ip1", now=100) is False

    def test_window_slides(self):
        """窗口滑动后配额恢复"""
        rl = SlidingWindowRateLimiter(max_requests=2, window_seconds=60)
        assert rl.allow("ip1", now=100) is True
        assert rl.allow("ip1", now=100) is True
        # 61 秒后旧时间戳被淘汰，重新放行
        assert rl.allow("ip1", now=161) is True

    def test_independent_keys(self):
        """不同 key 互不影响"""
        rl = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
        assert rl.allow("ip1", now=100) is True
        assert rl.allow("ip2", now=100) is True
        assert rl.allow("ip1", now=100) is False
        assert rl.allow("ip2", now=100) is False

    def test_reset_key(self):
        rl = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
        assert rl.allow("ip1", now=100) is True
        assert rl.allow("ip1", now=100) is False
        rl.reset("ip1")
        assert rl.allow("ip1", now=100) is True

    def test_reset_all(self):
        rl = SlidingWindowRateLimiter(max_requests=1, window_seconds=60)
        rl.allow("ip1", now=100)
        rl.allow("ip2", now=100)
        rl.reset()
        assert rl.allow("ip1", now=100) is True
        assert rl.allow("ip2", now=100) is True

    def test_current_count(self):
        rl = SlidingWindowRateLimiter(max_requests=10, window_seconds=60)
        rl.allow("ip1", now=100)
        rl.allow("ip1", now=100)
        assert rl.current_count("ip1", now=100) == 2

    def test_invalid_params(self):
        with pytest.raises(ValueError):
            SlidingWindowRateLimiter(max_requests=0, window_seconds=60)
        with pytest.raises(ValueError):
            SlidingWindowRateLimiter(max_requests=10, window_seconds=0)


# --------------------------------------------------------------------------- #
# API Key 辅助函数
# --------------------------------------------------------------------------- #
class TestApiKeyHelpers:
    def test_api_key_matches(self):
        from src.auth.dependencies import _api_key_matches

        assert _api_key_matches("key-abc", ["key-abc", "other"]) is True
        assert _api_key_matches("wrong", ["key-abc"]) is False
        assert _api_key_matches("key-abc", []) is False

    def test_service_account_is_admin(self):
        from src.auth.dependencies import _make_service_account

        acct = _make_service_account()
        assert acct.role == "admin"
        assert acct.user_id == "service-account-api-key"
        assert acct.is_active is True
