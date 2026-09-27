# -*- coding: utf-8 -*-
"""
SubAI Translator —— FastAPI 端到端集成测试
============================================

需要设置 RUN_API_TESTS=1 才会执行（避免依赖真实后端）。

覆盖路由：
1. /api/health
2. /api/upload（文件上传）
3. /api/transcode（提交任务）
4. /api/task/{id}（查询）
5. /api/task/{id} DELETE（取消/归档）
6. /api/history
7. /api/terminology GET/POST/import
8. /api/cache/stats、/api/cache/clear
9. /api/queue/stats
10. /api/config/reload
11. /api/output/{filename}
"""
from __future__ import annotations

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_API_TESTS"),
    reason="需要 RUN_API_TESTS=1 才执行 API 集成测试",
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    """用临时目录覆盖 DB 路径后创建 TestClient（with 上下文触发 lifespan）"""
    from src.config import config as _cfg
    term_path = str(tmp_path / "term.db")
    cache_path = str(tmp_path / "cache.db")
    monkeypatch.setattr(_cfg.paths, "terminology_db", term_path)
    monkeypatch.setattr(_cfg.cache, "db_path", cache_path)
    monkeypatch.setattr(_cfg.paths, "uploads_dir", str(tmp_path / "uploads"))
    # 重设单例（保证用最新的路径初始化）
    from src.db import tasks as tasks_mod
    tasks_mod.task_manager = None
    from src.cache import translation_cache as cache_mod
    cache_mod.translation_cache = None
    from src.queue import task_queue as queue_mod
    queue_mod.task_queue = None

    from fastapi.testclient import TestClient
    from src.api.server import app
    # 用 with 触发 lifespan（task_manager / task_queue / translation_cache 都在 lifespan 里初始化）
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# 健康检查
# --------------------------------------------------------------------------- #
class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "version" in body
        assert "llm_mode" in body
        assert "asr_device" in body


# --------------------------------------------------------------------------- #
# 任务提交与查询
# --------------------------------------------------------------------------- #
class TestTaskLifecycle:
    def test_transcode_missing_file_404(self, client):
        r = client.post("/api/transcode", json={"video_path": "Z:/does/not/exist.mp4"})
        assert r.status_code == 404

    def test_transcode_and_query(self, client, tmp_path):
        # 造一个假视频文件
        fake = tmp_path / "fake.mp4"
        fake.write_bytes(b"\x00" * 1024)

        r = client.post("/api/transcode", json={"video_path": str(fake)})
        assert r.status_code == 200
        task_id = r.json()["task_id"]

        r = client.get(f"/api/task/{task_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["task_id"] == task_id
        assert body["video_path"] == str(fake)

    def test_query_nonexistent_task_404(self, client):
        r = client.get("/api/task/nonexistent")
        assert r.status_code == 404

    def test_delete_task(self, client, tmp_path):
        fake = tmp_path / "fake.mp4"
        fake.write_bytes(b"\x00" * 1024)
        r = client.post("/api/transcode", json={"video_path": str(fake)})
        task_id = r.json()["task_id"]

        # 第一次删除：取消/归档
        r = client.delete(f"/api/task/{task_id}")
        assert r.status_code == 200
        assert "已" in r.json()["message"]

        # 第二次删除应幂等（任务仍存在，只是状态被标记了）
        # —— 设计取舍：保留任务记录用于审计，不允许硬删除
        r = client.delete(f"/api/task/{task_id}")
        assert r.status_code == 200

        # 但对完全不存在 task_id 的 DELETE 应返回 404
        r = client.delete("/api/task/never-existed-id")
        assert r.status_code == 404

    def test_history(self, client, tmp_path):
        fake = tmp_path / "h.mp4"
        fake.write_bytes(b"\x00" * 100)
        client.post("/api/transcode", json={"video_path": str(fake)})

        r = client.get("/api/history")
        assert r.status_code == 200
        body = r.json()
        assert "tasks" in body
        assert "total" in body
        assert body["total"] >= 1


# --------------------------------------------------------------------------- #
# 术语库
# --------------------------------------------------------------------------- #
class TestTerminologyAPI:
    def test_list_empty(self, client):
        r = client.get("/api/terminology")
        assert r.status_code == 200

    def test_add_term(self, client):
        r = client.post("/api/terminology", json={
            "source_text": "测试", "translation": "test", "priority": "high"
        })
        assert r.status_code == 200
        assert r.json()["term_id"] >= 1

    def test_add_term_validation(self, client):
        r = client.post("/api/terminology", json={
            "source_text": "", "translation": "test"
        })
        assert r.status_code == 400

    def test_import_terms(self, client):
        import json
        payload = json.dumps([
            {"source_text": "A", "translation": "甲", "priority": "high"},
            {"source_text": "B", "translation": "乙", "priority": "medium"},
        ]).encode()
        r = client.post("/api/terminology/import", files={"file": ("t.json", payload, "application/json")})
        assert r.status_code == 200
        assert "导入" in r.json()["message"]

    def test_list_with_keyword(self, client):
        client.post("/api/terminology", json={
            "source_text": "特定关键词XYZ", "translation": "special"
        })
        r = client.get("/api/terminology", params={"keyword": "XYZ"})
        assert r.status_code == 200
        assert r.json()["total"] >= 1


# --------------------------------------------------------------------------- #
# 文件上传
# --------------------------------------------------------------------------- #
class TestUpload:
    def test_upload_ok(self, client):
        content = b"\x00" * 2048  # 2KB 假视频内容
        r = client.post(
            "/api/upload",
            files={"file": ("test.mp4", content, "video/mp4")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["filename"] == "test.mp4"
        assert body["size_bytes"] == 2048
        assert os.path.isfile(body["video_path"])

    def test_upload_invalid_extension(self, client):
        r = client.post(
            "/api/upload",
            files={"file": ("notes.txt", b"hello", "text/plain")},
        )
        assert r.status_code == 400

    def test_upload_then_transcode(self, client):
        # 上传文件后，用返回的 video_path 提交转码任务（端到端）
        content = b"\x00" * 1024
        r = client.post(
            "/api/upload",
            files={"file": ("movie.mp4", content, "video/mp4")},
        )
        assert r.status_code == 200
        video_path = r.json()["video_path"]

        r = client.post("/api/transcode", json={"video_path": video_path})
        assert r.status_code == 200
        assert r.json()["task_id"]


# --------------------------------------------------------------------------- #
# 缓存与队列
# --------------------------------------------------------------------------- #
class TestCacheAndQueue:
    def test_cache_stats(self, client):
        r = client.get("/api/cache/stats")
        assert r.status_code == 200
        body = r.json()
        assert "total_entries" in body
        assert "max_entries" in body

    def test_cache_clear(self, client):
        r = client.post("/api/cache/clear")
        assert r.status_code == 200

    def test_queue_stats(self, client):
        r = client.get("/api/queue/stats")
        assert r.status_code == 200
        body = r.json()
        assert "max_concurrent" in body
        assert "queue_size" in body


# --------------------------------------------------------------------------- #
# 配置与输出
# --------------------------------------------------------------------------- #
class TestConfigAndOutput:
    def test_config_reload(self, client):
        r = client.post("/api/config/reload")
        assert r.status_code == 200
        body = r.json()
        assert "config" in body
        assert "llm_mode" in body["config"]

    def test_output_not_found(self, client):
        r = client.get("/api/output/nonexistent.srt")
        assert r.status_code == 404