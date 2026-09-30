# -*- coding: utf-8 -*-
"""
SubAI Translator —— 任务取消（协作式）
=======================================

问题:任务通过线程池执行,Python 无法安全地强杀线程;仅把数据库状态改成
cancelled 并不会让已经跑起来的流水线停下（此前就是这样,只是"标记"取消）。

因此采用**协作式取消**:执行方在关键节点轮询一个线程安全的事件,命中即抛出
TaskCancelled 主动退出;服务端捕获后把任务置为 cancelled。

服务端用法:
    token = register(task_id)
    try:
        run_pipeline(..., should_cancel=lambda: token.is_set())
    finally:
        unregister(task_id)

取消方:
    cancel(task_id)          # 立即置位,返回是否命中了在跑的任务
"""
from __future__ import annotations

import threading
from typing import Callable, Optional


class TaskCancelled(Exception):
    """任务被协作式取消（正常控制流,不是错误）。"""


_tokens: dict = {}
_lock = threading.Lock()


def register(task_id: str) -> threading.Event:
    """为任务创建取消事件（重复注册会覆盖旧事件）。"""
    ev = threading.Event()
    with _lock:
        _tokens[task_id] = ev
    return ev


def unregister(task_id: str) -> None:
    with _lock:
        _tokens.pop(task_id, None)


def cancel(task_id: str) -> bool:
    """置位取消标志。返回 True 表示确实有一个在跑/待跑的任务被通知。"""
    with _lock:
        ev = _tokens.get(task_id)
    if ev is None:
        return False
    ev.set()
    return True


def is_cancelled(task_id: str) -> bool:
    with _lock:
        ev = _tokens.get(task_id)
    return bool(ev and ev.is_set())


def raise_if_cancelled(should_cancel: Optional[Callable[[], bool]]) -> None:
    """供流水线在检查点调用:命中取消则抛 TaskCancelled。"""
    if should_cancel is not None and should_cancel():
        raise TaskCancelled("任务已取消")
