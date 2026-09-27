# -*- coding: utf-8 -*-
"""
SubAI Translator —— TaskManager 单元测试
=========================================

覆盖：
1. 创建/查询/更新/删除任务
2. 列表 + 分页 + 状态过滤
3. 状态统计
4. 完成时间戳自动写入
5. 并发场景
6. 边界场景
"""
from __future__ import annotations

import asyncio
import pytest

from src.db.tasks import TaskManager, TaskRecord


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #
class TestTaskManagerCRUD:
    @pytest.fixture
    async def tm(self, tmp_path):
        db = str(tmp_path / "tasks.db")
        m = TaskManager(db)
        await m.initialize()
        yield m
        await m.close()

    @pytest.mark.asyncio
    async def test_create_and_get(self, tm: TaskManager):
        task = await tm.create_task(
            task_id="t1",
            video_path="D:/videos/test.mp4",
            mode="asr",
            target_lang="en",
        )
        assert task.task_id == "t1"
        assert task.status == "pending"

        got = await tm.get_task("t1")
        assert got is not None
        assert got.video_path == "D:/videos/test.mp4"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, tm: TaskManager):
        assert await tm.get_task("nope") is None

    @pytest.mark.asyncio
    async def test_update_status(self, tm: TaskManager):
        await tm.create_task("t1", "/v.mp4")
        updated = await tm.update_task("t1", status="processing", progress=0.5)
        assert updated is not None
        assert updated.status == "processing"
        assert abs(updated.progress - 0.5) < 1e-6

    @pytest.mark.asyncio
    async def test_update_completed_sets_completed_at(self, tm: TaskManager):
        await tm.create_task("t1", "/v.mp4")
        before = updated = await tm.update_task("t1", status="completed", progress=1.0)
        assert updated.completed_at is not None
        assert updated.completed_at >= before.updated_at

    @pytest.mark.asyncio
    async def test_update_failed_sets_completed_at(self, tm: TaskManager):
        await tm.create_task("t1", "/v.mp4")
        updated = await tm.update_task("t1", status="failed", error_message="boom")
        assert updated.completed_at is not None
        assert updated.error_message == "boom"

    @pytest.mark.asyncio
    async def test_update_result_files_json_serialized(self, tm: TaskManager):
        await tm.create_task("t1", "/v.mp4")
        files = ["output/a.srt", "output/b.srt"]
        updated = await tm.update_task("t1", result_files=files)
        assert updated.result_files == files

        # 重新读取验证 JSON 反序列化
        got = await tm.get_task("t1")
        assert got.result_files == files

    @pytest.mark.asyncio
    async def test_delete(self, tm: TaskManager):
        await tm.create_task("t1", "/v.mp4")
        assert await tm.delete_task("t1") is True
        assert await tm.get_task("t1") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, tm: TaskManager):
        assert await tm.delete_task("nope") is False


# --------------------------------------------------------------------------- #
# 列表与统计
# --------------------------------------------------------------------------- #
class TestTaskManagerList:
    @pytest.fixture
    async def tm(self, tmp_path):
        db = str(tmp_path / "tasks.db")
        m = TaskManager(db)
        await m.initialize()
        yield m
        await m.close()

    @pytest.mark.asyncio
    async def test_list_all(self, tm: TaskManager):
        for i in range(5):
            await tm.create_task(f"t{i}", f"/v{i}.mp4")
        tasks = await tm.list_tasks(limit=10)
        assert len(tasks) == 5

    @pytest.mark.asyncio
    async def test_list_by_status(self, tm: TaskManager):
        await tm.create_task("t1", "/v.mp4")
        await tm.create_task("t2", "/v.mp4")
        await tm.update_task("t1", status="processing")
        processing = await tm.list_tasks(status="processing")
        pending = await tm.list_tasks(status="pending")
        assert len(processing) == 1
        assert processing[0].task_id == "t1"
        assert len(pending) == 1

    @pytest.mark.asyncio
    async def test_list_pagination(self, tm: TaskManager):
        for i in range(10):
            await tm.create_task(f"t{i}", "/v.mp4")
        page1 = await tm.list_tasks(limit=4, offset=0)
        page2 = await tm.list_tasks(limit=4, offset=4)
        assert len(page1) == 4
        assert len(page2) == 4
        # 不同页 task_id 不重叠
        ids1 = {t.task_id for t in page1}
        ids2 = {t.task_id for t in page2}
        assert ids1.isdisjoint(ids2)

    @pytest.mark.asyncio
    async def test_get_active_tasks(self, tm: TaskManager):
        await tm.create_task("p1", "/v.mp4")
        await tm.create_task("p2", "/v.mp4")
        await tm.create_task("done", "/v.mp4")
        await tm.update_task("done", status="completed", progress=1.0)
        active = await tm.get_active_tasks()
        active_ids = {t.task_id for t in active}
        assert active_ids == {"p1", "p2"}

    @pytest.mark.asyncio
    async def test_get_stats(self, tm: TaskManager):
        await tm.create_task("t1", "/v.mp4")
        await tm.create_task("t2", "/v.mp4")
        await tm.update_task("t1", status="completed")
        stats = await tm.get_stats()
        assert stats["total"] == 2
        assert stats["by_status"]["pending"] == 1
        assert stats["by_status"]["completed"] == 1
        assert "today" in stats


# --------------------------------------------------------------------------- #
# TaskRecord 模型
# --------------------------------------------------------------------------- #
class TestTaskRecordModel:
    def test_to_dict_default(self):
        rec = TaskRecord(task_id="t1", video_path="/v.mp4")
        d = rec.to_dict()
        assert d["task_id"] == "t1"
        assert d["status"] == "pending"
        assert d["result_files"] == []
        assert d["error_message"] is None

    def test_to_dict_with_timestamps(self):
        import time
        now = time.time()
        rec = TaskRecord(task_id="t1", video_path="/v.mp4",
                         created_at=now, updated_at=now, completed_at=now)
        d = rec.to_dict()
        assert d["created_at"] is not None
        assert d["completed_at"] is not None


# --------------------------------------------------------------------------- #
# 边界场景
# --------------------------------------------------------------------------- #
class TestTaskManagerEdgeCases:
    @pytest.fixture
    async def tm(self, tmp_path):
        db = str(tmp_path / "tasks.db")
        m = TaskManager(db)
        await m.initialize()
        yield m
        await m.close()

    @pytest.mark.asyncio
    async def test_concurrent_creates(self, tm: TaskManager):
        await asyncio.gather(*[
            tm.create_task(f"t{i}", f"/v{i}.mp4") for i in range(10)
        ])
        tasks = await tm.list_tasks(limit=20)
        assert len(tasks) == 10

    @pytest.mark.asyncio
    async def test_unicode_video_path(self, tm: TaskManager):
        await tm.create_task("t1", "D:/视频/测试视频.mp4")
        got = await tm.get_task("t1")
        assert got.video_path == "D:/视频/测试视频.mp4"

    @pytest.mark.asyncio
    async def test_update_with_only_some_fields(self, tm: TaskManager):
        await tm.create_task("t1", "/v.mp4", source_lang="zh")
        await tm.update_task("t1", status="processing")
        got = await tm.get_task("t1")
        # source_lang 应保持不变
        assert got.source_lang == "zh"
        assert got.status == "processing"