# -*- coding: utf-8 -*-
"""
SubAI Translator —— 重试模块（二期新增）
========================================

支持能力：
1. 指数退避（exponential backoff with jitter）
2. 异常分类：仅对可重试异常重试（网络/超时/5xx），对 4xx 等编程错误立即抛出
3. 同步 + 异步双接口
4. 可配置最大重试次数、初始延迟、上限延迟、可重试异常白名单
5. 重试回调：每次重试前触发（用于打日志 / 推进度）

使用示例（同步）：
    from src.retry import retry
    result = retry(httpx.post, args=(url,), kwargs=json_body,
                   max_retries=3, retry_on=(httpx.HTTPError,))

使用示例（异步）：
    from src.retry import async_retry
    result = await async_retry(llm_call, args=(text,),
                               max_retries=3, retry_on=(httpx.HTTPError,))

设计取舍：
- 默认不对 httpx.HTTPStatusError 整体重试，而是仅当 status in {502, 503, 504, 429}
  时重试（4xx 客户端错误立即失败）。
- jitter 使用 uniform(-25%, +25%)，避免雷鸣群。
- 同步重试用 time.sleep，异步用 asyncio.sleep，不破坏调用方的事件循环。
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Awaitable, Callable, Iterable, Optional, TypeVar, Union

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 默认可重试的异常白名单：网络层 + 超时
DEFAULT_RETRY_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

# 默认 retry 类不重试的 HTTP 状态码（视为编程错误，立即失败）
DEFAULT_NON_RETRYABLE_HTTP_STATUS: tuple[int, ...] = (
    400, 401, 403, 404, 405, 422,  # 客户端错误
)


class RetryExhausted(Exception):
    """所有重试用尽后仍失败时抛出。携带最后一次原始异常。"""
    def __init__(self, last_exception: BaseException, attempts: int):
        self.last_exception = last_exception
        self.attempts = attempts
        super().__init__(
            f"重试 {attempts} 次后仍失败: {type(last_exception).__name__}: {last_exception}"
        )


def _calc_delay(attempt: int, base: float, cap: float) -> float:
    """计算第 attempt 次（从 1 起）的等待秒数：base * 2^(attempt-1)，加 jitter，截顶到 cap"""
    raw = base * (2 ** (attempt - 1))
    capped = min(raw, cap)
    jitter = capped * random.uniform(-0.25, 0.25)
    return max(0.0, capped + jitter)


def _is_retryable_http_status(exc: BaseException, non_retryable: Iterable[int]) -> bool:
    """httpx.HTTPStatusError 等异常携带 response，可单独判断 status。"""
    resp = getattr(exc, "response", None)
    if resp is None:
        return True
    status = getattr(resp, "status_code", None)
    if status is None:
        return True
    return status not in set(non_retryable)


def retry(
    func: Callable[..., T],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: Iterable[type[BaseException]] = DEFAULT_RETRY_EXCEPTIONS,
    non_retryable_http_status: Iterable[int] = DEFAULT_NON_RETRYABLE_HTTP_STATUS,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
    **kwargs: Any,
) -> T:
    """
    同步函数重试包装器。

    参数：
        func: 要调用的同步函数
        *args: 位置参数透传给 func
        max_retries: 最大尝试次数（含首次），1 表示不重试
        base_delay: 首次重试前等待秒数（指数退避基数）
        max_delay: 单次等待上限秒数
        retry_on: 视为可重试的异常类型元组
        non_retryable_http_status: 携带 response.status_code 的异常在这些状态码下立即失败
        on_retry: 每次重试前的回调 (attempt, exception, delay_seconds)
        **kwargs: 关键字参数透传给 func

    返回：
        func 的返回值

    抛出：
        RetryExhausted: 重试耗尽
        Exception: 不可重试异常立即透传
    """
    retry_on_t = tuple(retry_on)
    non_retry_status = set(non_retryable_http_status)
    last_exc: Optional[BaseException] = None

    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except retry_on_t as e:
            last_exc = e
            # 若是 HTTP 异常且状态码在禁重试列表里，立即失败
            if not _is_retryable_http_status(e, non_retry_status):
                raise
            if attempt >= max_retries:
                break
            delay = _calc_delay(attempt, base_delay, max_delay)
            logger.warning(
                "重试 %s (%d/%d) 异常: %r，等待 %.2fs",
                getattr(func, "__name__", repr(func)), attempt, max_retries, e, delay,
            )
            if on_retry:
                try:
                    on_retry(attempt, e, delay)
                except Exception:  # 回调绝不能阻断主流程
                    logger.exception("on_retry 回调异常")
            time.sleep(delay)

    raise RetryExhausted(last_exc, max_retries)  # type: ignore[misc]


async def async_retry(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: Iterable[type[BaseException]] = DEFAULT_RETRY_EXCEPTIONS,
    non_retryable_http_status: Iterable[int] = DEFAULT_NON_RETRYABLE_HTTP_STATUS,
    on_retry: Optional[Callable[[int, BaseException, float], Any]] = None,
    **kwargs: Any,
) -> T:
    """
    异步函数重试包装器。语义与 retry() 对齐，唯一区别是用 asyncio.sleep。
    """
    retry_on_t = tuple(retry_on)
    non_retry_status = set(non_retryable_http_status)
    last_exc: Optional[BaseException] = None

    for attempt in range(1, max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except retry_on_t as e:
            last_exc = e
            if not _is_retryable_http_status(e, non_retry_status):
                raise
            if attempt >= max_retries:
                break
            delay = _calc_delay(attempt, base_delay, max_delay)
            logger.warning(
                "异步重试 %s (%d/%d) 异常: %r，等待 %.2fs",
                getattr(func, "__name__", repr(func)), attempt, max_retries, e, delay,
            )
            if on_retry:
                try:
                    ret = on_retry(attempt, e, delay)
                    if asyncio.iscoroutine(ret):
                        await ret
                except Exception:
                    logger.exception("on_retry 回调异常")
            await asyncio.sleep(delay)

    raise RetryExhausted(last_exc, max_retries)  # type: ignore[misc]