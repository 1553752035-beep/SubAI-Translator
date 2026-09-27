# -*- coding: utf-8 -*-
"""
SubAI Translator —— 重试模块单元测试
======================================

覆盖：
1. 同步重试 retry()
2. 异步重试 async_retry()
3. 异常分类：可重试 vs 不可重试
4. HTTP 状态码判断
5. RetryExhausted 抛出条件
6. on_retry 回调
7. 边界情况（max_retries=1、异常不是 retry_on 子类）
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.retry import (
    RetryExhausted,
    async_retry,
    retry,
    _calc_delay,
    _is_retryable_http_status,
)


# --------------------------------------------------------------------------- #
# 同步 retry() 测试
# --------------------------------------------------------------------------- #
class TestSyncRetry:
    def test_success_first_try(self):
        """首次就成功：不应触发任何重试"""
        called = []

        def fn(x: int) -> int:
            called.append(x)
            return x * 2

        result = retry(fn, 5, max_retries=3)
        assert result == 10
        assert len(called) == 1

    def test_retry_then_success(self):
        """失败 1 次后成功"""
        state = {"n": 0}

        def fn() -> str:
            state["n"] += 1
            if state["n"] < 2:
                raise ConnectionError("暂时性故障")
            return "ok"

        # 用 0 base_delay 加快测试
        result = retry(fn, max_retries=3, base_delay=0.0)
        assert result == "ok"
        assert state["n"] == 2

    def test_exhausted_raises_retry_exhausted(self):
        """重试耗尽后应抛 RetryExhausted"""
        def always_fail():
            raise ConnectionError("永久故障")

        with pytest.raises(RetryExhausted) as exc_info:
            retry(always_fail, max_retries=2, base_delay=0.0)
        assert isinstance(exc_info.value.last_exception, ConnectionError)
        assert exc_info.value.attempts == 2

    def test_non_retryable_exception_propagates_immediately(self):
        """不在白名单的异常立即抛出，不重试"""
        called = []

        def fn():
            called.append(1)
            raise ValueError("编程错误，不应重试")

        with pytest.raises(ValueError):
            retry(fn, max_retries=5, base_delay=0.0)
        assert len(called) == 1  # 没有重试

    def test_http_status_retry(self):
        """HTTP 5xx 视为可重试"""
        state = {"n": 0}
        resp = MagicMock()
        resp.status_code = 503

        def fn():
            state["n"] += 1
            if state["n"] < 3:
                e = ConnectionError("HTTP 503")
                e.response = resp  # type: ignore[attr-defined]
                raise e
            return "ok"

        result = retry(fn, max_retries=3, base_delay=0.0)
        assert result == "ok"

    def test_http_status_non_retryable(self):
        """HTTP 4xx（客户端错误）不应重试"""
        called = []
        resp = MagicMock()
        resp.status_code = 404

        def fn():
            called.append(1)
            e = ConnectionError("HTTP 404")
            e.response = resp  # type: ignore[attr-defined]
            raise e

        with pytest.raises(ConnectionError):
            retry(fn, max_retries=5, base_delay=0.0)
        assert len(called) == 1

    def test_on_retry_callback_invoked(self):
        """on_retry 每次重试前都触发一次"""
        state = {"n": 0, "callbacks": 0}

        def fn():
            state["n"] += 1
            if state["n"] < 3:
                raise ConnectionError("retry me")

        def on_retry(attempt: int, exc: Exception, delay: float) -> None:
            state["callbacks"] += 1
            assert attempt >= 1
            assert delay >= 0

        retry(fn, max_retries=3, base_delay=0.0, on_retry=on_retry)
        # 失败 2 次 → 重试 2 次 → 回调次数 = 2
        assert state["callbacks"] == 2

    def test_max_retries_one_means_no_retry(self):
        """max_retries=1 等价于不重试"""
        called = []

        def fn():
            called.append(1)
            raise ConnectionError("boom")

        with pytest.raises(RetryExhausted):
            retry(fn, max_retries=1, base_delay=0.0)
        assert len(called) == 1


# --------------------------------------------------------------------------- #
# 异步 async_retry() 测试
# --------------------------------------------------------------------------- #
class TestAsyncRetry:
    @pytest.mark.asyncio
    async def test_async_success(self):
        async def fn(x: int) -> int:
            return x + 1

        result = await async_retry(fn, 5, max_retries=3, base_delay=0.0)
        assert result == 6

    @pytest.mark.asyncio
    async def test_async_retry_then_success(self):
        state = {"n": 0}

        async def fn() -> str:
            state["n"] += 1
            if state["n"] < 2:
                raise ConnectionError("transient")
            return "ok"

        result = await async_retry(fn, max_retries=3, base_delay=0.0)
        assert result == "ok"
        assert state["n"] == 2

    @pytest.mark.asyncio
    async def test_async_exhausted(self):
        async def fn():
            raise TimeoutError("永久超时")

        with pytest.raises(RetryExhausted):
            await async_retry(fn, max_retries=2, base_delay=0.0)

    @pytest.mark.asyncio
    async def test_async_on_retry_may_be_coroutine(self):
        """on_retry 既可以是同步函数也可以是异步协程"""
        state = {"n": 0, "callbacks": 0}

        async def fn():
            state["n"] += 1
            if state["n"] < 3:
                raise ConnectionError("retry")

        async def on_retry(attempt: int, exc: Exception, delay: float):
            state["callbacks"] += 1

        await async_retry(fn, max_retries=3, base_delay=0.0, on_retry=on_retry)
        assert state["callbacks"] == 2


# --------------------------------------------------------------------------- #
# 内部工具函数测试
# --------------------------------------------------------------------------- #
class TestCalcDelay:
    def test_increases_with_attempt(self):
        """延迟随重试次数指数增长"""
        d1 = _calc_delay(1, base=1.0, cap=100.0)
        d2 = _calc_delay(2, base=1.0, cap=100.0)
        d3 = _calc_delay(3, base=1.0, cap=100.0)
        # jitter ±25%，取近似值校验
        assert 0.7 <= d1 <= 1.3
        assert 1.5 <= d2 <= 2.5
        assert 3.0 <= d3 <= 5.0

    def test_capped_at_max_delay(self):
        """延迟上限生效"""
        d = _calc_delay(10, base=1.0, cap=5.0)
        assert d <= 5.0 * 1.25  # cap + jitter 上界


class TestIsRetryableHttpStatus:
    def test_404_not_retryable(self):
        resp = MagicMock(); resp.status_code = 404
        e = ConnectionError("404"); e.response = resp  # type: ignore[attr-defined]
        assert _is_retryable_http_status(e, [400, 401, 404]) is False

    def test_500_retryable(self):
        resp = MagicMock(); resp.status_code = 500
        e = ConnectionError("500"); e.response = resp  # type: ignore[attr-defined]
        assert _is_retryable_http_status(e, [400, 401]) is True

    def test_no_response_defaults_to_retryable(self):
        e = ConnectionError("no resp")
        assert _is_retryable_http_status(e, [400]) is True