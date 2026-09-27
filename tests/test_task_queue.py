# -*- coding: utf-8 -*-
"""
SubAI Translator —— TaskQueue 单元测试
=======================================

覆盖：
1. 任务提交与并发控制
2. 优先级排序
3. 队列上限
4. 关闭与清理
5. 状态查询
"""
from __future__ import annotations

import asyncio
import pytest

from src.db.tasks import TaskManager
from src.queue.task_queue import TaskQueue, Priority


# --------------------------------------------------------------------------- #
# 基础功能
# --------------------------------------------------------------------------- #
class TestTaskQueueBasic:
    @pytest.fixture
    async def setup(self, tmp_path):
        tm = TaskManager(str(tmp_path / "tasks.db"))
        await tm.initialize()
        queue = TaskQueue(tm, max_concurrent=2, max_queue_size=10)
        await queue.initialize()
        yield tm, queue
        await queue.shutdown()
        await tm.close()

    @pytest.mark.asyncio
    async def test_submit_and_execute(self, setup):
        tm, queue = setup
        executed = []

        async def cb(task_id: str, **kwargs):
            executed.append(task_id)
            await tm.update_task(task_id, status="completed", progress=1.0)

        await tm.create_task("t1", "/v.mp4")
        ok = await queue.submit("t1", cb, video_path="/v.mp4")
        assert ok is True

        # 等任务完成
        for _ in range(50):
            await asyncio.sleep(0.05)
            if executed:
                break
        assert executed == ["t1"]

    @pytest.mark.asyncio
    async def test_priority_ordering(self, tmp_path):
        """priority 必须使 high 先于 medium 先于 low 出队"""
        tm = TaskManager(str(tmp_path / "tasks.db"))
        await tm.initialize()
        # max_concurrent=0 等价于"全部排队"，保证同时进队列后再竞争出队
        # 但实际 queue 要求 >=1，所以用 max_concurrent=1 + 让首任务慢跑
        queue = TaskQueue(tm, max_concurrent=1, max_queue_size=10)
        await queue.initialize()

        order = []
        started = asyncio.Event()

        async def slow_first_cb(task_id: str, **kwargs):
            if task_id == "blocker":
                # 第一个任务 sleep 阻塞，让后续 3 个进入队列再开始执行
                await asyncio.sleep(0.3)
                order.append(task_id)
                started.set()
            else:
                order.append(task_id)

        # 先发一个 blocker 占住并发槽 0.3s，期间把 3 个真任务全部塞进队列
        await tm.create_task("blocker", "/v.mp4")
        await queue.submit("blocker", slow_first_cb)

        await asyncio.sleep(0.02)  # 让 blocker 进入 running

        for tid in ("low", "medium", "high"):
            await tm.create_task(tid, "/v.mp4")
            await queue.submit(tid, slow_first_cb, priority=tid)

        # 等全部完成
        for _ in range(100):
            await asyncio.sleep(0.05)
            if len(order) >= 4:
                break

        # blocker 必最先，剩下 3 个按优先级
        assert order[0] == "blocker"
        assert order[1:] == ["high", "medium", "low"], \
            f"优先级顺序错乱：{order}"

        await queue.shutdown()
        await tm.close()


# --------------------------------------------------------------------------- #
# 并发控制
# --------------------------------------------------------------------------- #
class TestTaskQueueConcurrency:
    @pytest.mark.asyncio
    async def test_concurrency_limit(self, tmp_path):
        """max_concurrent=1 时任务应串行执行"""
        tm = TaskManager(str(tmp_path / "tasks.db"))
        await tm.initialize()
        queue = TaskQueue(tm, max_concurrent=1, max_queue_size=10)
        await queue.initialize()

        active = []
        max_concurrent_observed = 0
        lock = asyncio.Lock()

        async def slow_cb(task_id: str, **kwargs):
            nonlocal max_concurrent_observed
            async with lock:
                active.append(task_id)
                if len(active) > max_concurrent_observed:
                    max_concurrent_observed = len(active)
            await asyncio.sleep(0.1)
            async with lock:
                active.remove(task_id)

        for i in range(3):
            await tm.create_task(f"t{i}", "/v.mp4")
            await queue.submit(f"t{i}", slow_cb)

        await asyncio.sleep(0.6)  # 等所有任务完成
        assert max_concurrent_observed == 1

        await queue.shutdown()
        await tm.close()


# --------------------------------------------------------------------------- #
# 队列上限
# --------------------------------------------------------------------------- #
class TestTaskQueueLimits:
    @pytest.mark.asyncio
    async def test_queue_full_rejects(self, tmp_path):
        """队列满时第 max_queue_size+1 个 submit 应返回 False"""
        tm = TaskManager(str(tmp_path / "tasks.db"))
        await tm.initialize()
        # max_concurrent=1 让任务长时间占用并发槽，确保队列占满
        # max_queue_size=2 允许缓冲 2 个
        queue = TaskQueue(tm, max_concurrent=1, max_queue_size=2)
        await queue.initialize()

        # 第一个任务占住并发槽，callback 慢一点
        start_event = asyncio.Event()

        async def slow_cb(**kwargs):
            # 让回调持续运行直到被显式释放
            await start_event.wait()

        await tm.create_task("t1", "/v.mp4")
        ok1 = await queue.submit("t1", slow_cb)
        assert ok1 is True

        # 给队列处理器一点时间把 t1 从队列取出进入 running
        await asyncio.sleep(0.05)

        # 接下来 2 个进入队列
        for i in range(2, 4):
            await tm.create_task(f"t{i}", "/v.mp4")
            ok = await queue.submit(f"t{i}", slow_cb)
            assert ok is True

        # 此时队列应已满
        await tm.create_task("t4", "/v.mp4")
        ok = await queue.submit("t4", slow_cb)
        assert ok is False, "队列满时应拒绝第 4 个任务"

        # 释放 slow_cb 让任务收尾
        start_event.set()
        await asyncio.sleep(0.5)
        await queue.shutdown()
        await tm.close()


# --------------------------------------------------------------------------- #
# 状态查询
# --------------------------------------------------------------------------- #
class TestTaskQueueStats:
    @pytest.mark.asyncio
    async def test_stats_initial(self, tmp_path):
        tm = TaskManager(str(tmp_path / "tasks.db"))
        await tm.initialize()
        queue = TaskQueue(tm, max_concurrent=2, max_queue_size=10)
        await queue.initialize()

        stats = await queue.get_stats()
        assert stats["max_concurrent"] == 2
        assert stats["max_queue_size"] == 10
        assert stats["queue_size"] == 0
        assert stats["running_count"] == 0
        assert stats["is_idle"] is True

        await queue.shutdown()
        await tm.close()

    @pytest.mark.asyncio
    async def test_priority_constants(self):
        """Priority 数值越小越优先（PriorityQueue 默认行为）"""
        assert Priority.HIGH < Priority.MEDIUM < Priority.LOW


# --------------------------------------------------------------------------- #
# 关闭
# --------------------------------------------------------------------------- #
class TestTaskQueueShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_rejects_new_tasks(self, tmp_path):
        tm = TaskManager(str(tmp_path / "tasks.db"))
        await tm.initialize()
        queue = TaskQueue(tm, max_concurrent=1, max_queue_size=10)
        await queue.initialize()
        await queue.shutdown()

        async def cb(**kwargs): pass
        ok = await queue.submit("t1", cb)
        assert ok is False
        await tm.close()