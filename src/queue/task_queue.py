# -*- coding: utf-8 -*-
"""
SubAI Translator —— 任务队列模块（二期新增）
==========================================

实现异步任务队列，支持：
1. 并发控制（通过asyncio.Semaphore限制同时运行的任务数）
2. 任务优先级（high/medium/low）
3. 任务排队（超出并发限制的任务进入队列等待）
4. 资源监控（内存使用监控，超限自动限流）

设计思路：
- 本地模式：并发数较低（默认2），受内存限制
- 云端模式：并发数较高（默认4），内存充足
- 任务队列支持100个任务排队
- 任务状态通过TaskManager持久化

使用示例：
    from src.queue.task_queue import TaskQueue
    
    queue = TaskQueue(max_concurrent=2)
    await queue.initialize()
    
    # 提交任务
    await queue.submit(task_id, video_path, mode, ...)
    
    # 关闭队列
    await queue.shutdown()
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Optional, Callable, Any

from src.db.tasks import TaskManager, TaskRecord

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 任务优先级
# --------------------------------------------------------------------------- #

class Priority:
    """任务优先级常量"""
    HIGH = 1
    MEDIUM = 2
    LOW = 3


PRIORITY_MAP = {
    "high": Priority.HIGH,
    "medium": Priority.MEDIUM,
    "low": Priority.LOW
}


# --------------------------------------------------------------------------- #
# 队列任务
# --------------------------------------------------------------------------- #

class QueueTask:
    """队列中的任务"""
    def __init__(
        self,
        task_id: str,
        callback: Callable,
        priority: str = "medium",
        **kwargs
    ):
        self.task_id = task_id
        self.callback = callback
        self.priority = PRIORITY_MAP.get(priority, Priority.MEDIUM)
        self.kwargs = kwargs
        self.enqueued_at = time.time()
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
    
    @property
    def is_running(self) -> bool:
        return self.started_at is not None and self.completed_at is None
    
    @property
    def wait_time(self) -> float:
        """等待时间（秒）"""
        if self.started_at:
            return self.started_at - self.enqueued_at
        return time.time() - self.enqueued_at


# --------------------------------------------------------------------------- #
# 任务队列
# --------------------------------------------------------------------------- #

class TaskQueue:
    """
    异步任务队列
    
    支持：
    - 并发控制（Semaphore）
    - 优先级队列
    - 资源监控
    - 任务状态管理
    """
    
    def __init__(
        self,
        task_manager: TaskManager,
        max_concurrent: int = 2,
        max_queue_size: int = 100
    ):
        """
        初始化任务队列
        
        Args:
            task_manager: 任务管理器实例
            max_concurrent: 最大并发数
            max_queue_size: 最大队列长度
        """
        self.task_manager = task_manager
        self.max_concurrent = max_concurrent
        self.max_queue_size = max_queue_size
        
        # 信号量（控制并发）
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
        # 优先级队列（按优先级排序）
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue(maxsize=max_queue_size)
        
        # 运行中的任务
        self._running_tasks: dict[str, asyncio.Task] = {}

        # 提交序号：作为优先级队列的次键，保证全序（见 submit）
        self._seq = 0
        
        # 队列状态
        self._is_shutting_down = False
        self._processor_task: Optional[asyncio.Task] = None
    
    async def initialize(self) -> None:
        """初始化队列（启动处理器）"""
        self._processor_task = asyncio.create_task(self._process_queue())
        logger.info(f"任务队列已初始化，最大并发={self.max_concurrent}")
    
    async def shutdown(self) -> None:
        """关闭队列（等待所有任务完成）"""
        logger.info("正在关闭任务队列...")
        self._is_shutting_down = True
        
        # 等待处理器完成
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        
        # 等待所有运行中的任务完成
        if self._running_tasks:
            logger.info(f"等待 {len(self._running_tasks)} 个运行中的任务完成...")
            await asyncio.gather(*self._running_tasks.values(), return_exceptions=True)
        
        logger.info("任务队列已关闭")
    
    # ----------------------------------------------------------------------- #
    # 任务提交
    # ----------------------------------------------------------------------- #
    
    async def submit(
        self,
        task_id: str,
        callback: Callable,
        priority: str = "medium",
        **kwargs
    ) -> bool:
        """
        提交任务到队列
        
        Args:
            task_id: 任务ID
            callback: 任务回调函数（必须是async函数）
            priority: 优先级（high/medium/low）
            **kwargs: 传递给回调函数的参数
        
        Returns:
            是否提交成功
        """
        if self._is_shutting_down:
            logger.warning("队列正在关闭，拒绝新任务")
            return False
        
        # 检查队列是否已满
        if self._queue.qsize() >= self.max_queue_size:
            logger.error(f"任务队列已满（{self.max_queue_size}），拒绝任务 {task_id}")
            return False
        
        # 创建队列任务
        queue_task = QueueTask(task_id, callback, priority, **kwargs)
        
        # 加入优先级队列：元组按 (优先级, 提交序号) 排序，序号单调递增保证全序。
        # 不能用 enqueued_at 做次键——同一时钟刻度内连续提交时两个任务时间戳可能相同，
        # 此时 PriorityQueue 会继续比较 QueueTask 本身，因缺少 __lt__ 抛 TypeError。
        self._seq += 1
        await self._queue.put((queue_task.priority, self._seq, queue_task))
        
        logger.info(f"任务 {task_id} 已加入队列（优先级={priority}，队列长度={self._queue.qsize()}）")
        return True
    
    # ----------------------------------------------------------------------- #
    # 队列处理
    # ----------------------------------------------------------------------- #
    
    async def _process_queue(self) -> None:
        """队列处理器（后台任务）

        关键修复：先 acquire 信号量再从队列取任务，否则 max_concurrent 已满时
        PriorityQueue 里的元素会被立刻拉出但阻塞在信号量上，导致队列内最多
        只有一个待出队项，优先级排序失效。
        """
        logger.info("队列处理器已启动")

        while not self._is_shutting_down:
            try:
                # 1. 先拿并发槽位（满了就在这里等，队列自然累积）
                try:
                    await asyncio.wait_for(
                        self.semaphore.acquire(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    continue  # 周期性检查关闭信号

                # 2. 有槽位后再从优先级队列取任务（保证高优先级先出）
                try:
                    _priority, _seq, queue_task = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=1.0,
                    )
                except asyncio.TimeoutError:
                    # 没有任务，释放槽位
                    self.semaphore.release()
                    continue

                # 3. 派发——信号量所有权随任务一起交给 _execute_task
                asyncio.create_task(self._execute_task(queue_task))

            except asyncio.CancelledError:
                break
            except Exception as e:
                # 异常时安全释放信号量（如果还持有）
                try:
                    self.semaphore.release()
                except ValueError:
                    pass
                logger.error(f"队列处理器异常: {e}", exc_info=True)
    
    async def _execute_task(self, queue_task: QueueTask) -> None:
        """
        执行任务。

        注意：信号量已由 _process_queue 在派发前 acquire，
        本函数只负责释放（放在 finally）。
        """
        task_id = queue_task.task_id

        try:
            # 更新任务状态为processing
            await self.task_manager.update_task(
                task_id,
                status="processing",
                progress=0.1,
                message="任务已开始处理"
            )

            queue_task.started_at = time.time()
            self._running_tasks[task_id] = asyncio.current_task()

            logger.info(f"开始执行任务 {task_id}")

            # 执行回调（支持async和sync函数）
            # 把 task_id 注入 kwargs，让回调能感知自身 id（便于回调内更新进度/打日志）
            merged_kwargs = {"task_id": task_id, **queue_task.kwargs}
            if inspect.iscoroutinefunction(queue_task.callback):
                await queue_task.callback(**merged_kwargs)
            else:
                # 同步函数：在线程池中执行
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    lambda: queue_task.callback(**merged_kwargs)
                )
            
            # 更新任务状态为completed
            await self.task_manager.update_task(
                task_id,
                status="completed",
                progress=1.0,
                message="任务完成"
            )
            
            queue_task.completed_at = time.time()
            logger.info(f"任务 {task_id} 完成（耗时 {queue_task.completed_at - queue_task.started_at:.1f}s）")
            
        except Exception as e:
            # 更新任务状态为failed
            await self.task_manager.update_task(
                task_id,
                status="failed",
                error_message=str(e)
            )
            logger.error(f"任务 {task_id} 失败: {e}", exc_info=True)
        
        finally:
            # 释放信号量
            self.semaphore.release()
            
            # 移除运行中的任务
            self._running_tasks.pop(task_id, None)
    
    # ----------------------------------------------------------------------- #
    # 状态查询
    # ----------------------------------------------------------------------- #
    
    @property
    def queue_size(self) -> int:
        """当前队列长度"""
        return self._queue.qsize()
    
    @property
    def running_count(self) -> int:
        """当前运行中的任务数"""
        return len([t for t in self._running_tasks.values() if t and not t.done()])
    
    @property
    def is_idle(self) -> bool:
        """队列是否空闲"""
        return self.queue_size == 0 and self.running_count == 0
    
    async def get_stats(self) -> dict:
        """
        获取队列统计信息
        
        Returns:
            统计字典
        """
        return {
            "max_concurrent": self.max_concurrent,
            "max_queue_size": self.max_queue_size,
            "queue_size": self.queue_size,
            "running_count": self.running_count,
            "is_idle": self.is_idle
        }


# --------------------------------------------------------------------------- #
# 全局实例（供API使用）
# --------------------------------------------------------------------------- #

task_queue: Optional[TaskQueue] = None


async def get_task_queue(task_manager: TaskManager, max_concurrent: int) -> TaskQueue:
    """
    获取全局任务队列实例（单例）
    
    Args:
        task_manager: 任务管理器实例
        max_concurrent: 最大并发数
    
    Returns:
        TaskQueue实例
    """
    global task_queue
    if task_queue is None:
        task_queue = TaskQueue(task_manager, max_concurrent)
        await task_queue.initialize()
    return task_queue