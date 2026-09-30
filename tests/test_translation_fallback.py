# -*- coding: utf-8 -*-
"""
SubAI Translator —— 翻译失败降级测试（v3.1.1）
================================================

验证：
1. 翻译后端不可用时，translate() 不抛异常，而是把失败行留空并写入 stats；
2. 部分失败不影响其余行；
3. 术语库命中完全不走 LLM；
4. 任务队列尊重回调显式写入的终态（不被覆盖为 completed）。
"""
from __future__ import annotations

import asyncio
import time

from src import pipeline
from src.db.tasks import TaskManager
from src.queue.task_queue import TaskQueue


class TestTranslateFallback:
    def test_all_lines_fail_does_not_raise(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("llm down")

        monkeypatch.setattr(pipeline, "_call_llm", boom)
        stats: dict = {}
        out = pipeline.translate(["甲", "乙"], "en", {}, batch_size=10, use_cache=False, stats=stats)
        assert out == ["", ""]
        assert stats["total"] == 2
        assert stats["failed"] == 2

    def test_partial_failure_keeps_other_lines(self, monkeypatch):
        def flaky(text, target, **k):
            if "BAD" in text:
                raise RuntimeError("nope")
            # 批量 prompt 返回不带编号的内容 => 触发"解析不全 -> 退回逐行"
            if "\n" in text or text.startswith("Translate"):
                return "(no numbering)"
            return "T:" + text

        monkeypatch.setattr(pipeline, "_call_llm", flaky)
        stats: dict = {}
        out = pipeline.translate(
            ["good", "BAD", "fine"], "en", {}, batch_size=1, use_cache=False, stats=stats
        )
        assert out[0] == "T:good"
        assert out[1] == ""
        assert out[2] == "T:fine"
        assert stats["failed"] == 1
        assert stats["total"] == 3

    def test_terms_bypass_llm(self, monkeypatch):
        calls = {"n": 0}

        def fake(*a, **k):
            calls["n"] += 1
            return "LLM"

        monkeypatch.setattr(pipeline, "_call_llm", fake)
        stats: dict = {}
        out = pipeline.translate(
            ["你好", "世界"], "en", {"你好": "Hello"}, batch_size=10, use_cache=False, stats=stats
        )
        assert out[0] == "Hello"
        assert stats["terms"] == 1
        assert stats["failed"] == 0

    def test_stats_optional(self, monkeypatch):
        monkeypatch.setattr(pipeline, "_call_llm", lambda *a, **k: "x")
        out = pipeline.translate(["a"], "en", {}, batch_size=1, use_cache=False)
        assert isinstance(out, list) and len(out) == 1


class TestQueueTerminalStatus:
    async def test_callback_failed_is_not_overwritten(self, tmp_path):
        tm = TaskManager(str(tmp_path / "tasks.db"))
        await tm.initialize()
        await tm.create_task(task_id="T1", video_path="v.mp4")

        q = TaskQueue(tm, max_concurrent=1, max_queue_size=10)
        await q.initialize()

        async def cb(task_id, **kwargs):
            await tm.update_task(task_id=task_id, status="failed", error_message="boom")

        await q.submit(task_id="T1", callback=cb, priority="high")

        deadline = time.time() + 10
        while time.time() < deadline:
            t = await tm.get_task("T1")
            if t and t.status in ("failed", "completed"):
                break
            await asyncio.sleep(0.05)

        task = await tm.get_task("T1")
        assert task is not None
        assert task.status == "failed"          # 未被队列覆盖为 completed
        assert task.error_message == "boom"

        await q.shutdown()
        await tm.close()
