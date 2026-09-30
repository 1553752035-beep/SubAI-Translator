# -*- coding: utf-8 -*-
"""
SubAI Translator —— FastAPI 端到端集成测试
============================================

需要设置 RUN_API_TESTS=1 才会执行（避免依赖真实后端）。

覆盖路由：
1. /api/health
2. /api/auth/register、/api/auth/login
3. /api/upload（文件上传，需认证）
4. /api/transcode（提交任务，需认证）
5. /api/task/{id}（查询/删除，需认证）
6. /api/history（需认证）
7. /api/terminology GET/POST/import/DELETE（需认证）
8. /api/cache/stats、/api/cache/clear（仅管理员）
9. /api/queue/stats（仅管理员）
10. /api/config/reload（仅管理员）
11. /api/output/{filename}（需认证）
12. 数据隔离（用户间任务/术语互不可见）
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
    users_path = str(tmp_path / "users.db")
    monkeypatch.setattr(_cfg.paths, "terminology_db", term_path)
    monkeypatch.setattr(_cfg.cache, "db_path", cache_path)
    monkeypatch.setattr(_cfg.paths, "uploads_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(_cfg.auth, "users_db", users_path)
    monkeypatch.setattr(_cfg.paths, "tasks_db", str(tmp_path / "tasks.db"))
    monkeypatch.setattr(_cfg.backup, "backup_dir", str(tmp_path / "backups"))

    # 重设单例（保证用最新的路径初始化）
    from src.db import tasks as tasks_mod
    tasks_mod.task_manager = None
    from src.cache import translation_cache as cache_mod
    cache_mod.translation_cache = None
    from src.queue import task_queue as queue_mod
    queue_mod.task_queue = None
    from src.auth import users as users_mod
    users_mod._user_manager = None
    # 重置限流器（模块级单例，跨 TestClient 累积会误伤后续测试）
    from src.security import middleware as security_mw
    security_mw._rate_limiter_cache.clear()

    from fastapi.testclient import TestClient
    from src.api.server import app
    import src.api.server as server_mod
    # 同步 server 模块的 config 引用，防止 reload_config 后引用分离导致 monkeypatch 失效
    server_mod.config = _cfg

    # 用 with 触发 lifespan（各管理器都在 lifespan 里初始化，并自动创建默认 admin）
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers(client):
    """登录默认 admin，返回带 Bearer Token 的请求头"""
    from src.config import config as _cfg
    r = client.post("/api/auth/login", json={
        "username": _cfg.auth.admin_username,
        "password": _cfg.auth.admin_password,
    })
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _login(client, username, password):
    """注册并登录普通用户，返回请求头"""
    client.post("/api/auth/register", json={"username": username, "password": password})
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


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
# 认证
# --------------------------------------------------------------------------- #
class TestAuth:
    def test_register_and_login(self, client):
        r = client.post("/api/auth/register", json={
            "username": "newuser", "password": "secret123"
        })
        assert r.status_code == 200

        r = client.post("/api/auth/login", json={
            "username": "newuser", "password": "secret123"
        })
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_me_requires_token(self, client, auth_headers):
        # 无令牌 → 401
        assert client.get("/api/auth/me").status_code == 401
        # 有令牌 → 200
        r = client.get("/api/auth/me", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["role"] == "admin"


# --------------------------------------------------------------------------- #
# 任务提交与查询
# --------------------------------------------------------------------------- #
class TestTaskLifecycle:
    def test_transcode_missing_file_404(self, client, auth_headers):
        r = client.post("/api/transcode", json={"video_path": "Z:/does/not/exist.mp4"}, headers=auth_headers)
        assert r.status_code == 404

    def test_transcode_requires_auth(self, client):
        r = client.post("/api/transcode", json={"video_path": "x.mp4"})
        assert r.status_code == 401

    def test_transcode_and_query(self, client, auth_headers, tmp_path):
        # 造一个假视频文件
        fake = tmp_path / "fake.mp4"
        fake.write_bytes(b"\x00" * 1024)

        r = client.post("/api/transcode", json={"video_path": str(fake)}, headers=auth_headers)
        assert r.status_code == 200
        task_id = r.json()["task_id"]

        r = client.get(f"/api/task/{task_id}", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["task_id"] == task_id
        assert body["video_path"] == str(fake)

    def test_query_nonexistent_task_404(self, client, auth_headers):
        r = client.get("/api/task/nonexistent", headers=auth_headers)
        assert r.status_code == 404

    def test_delete_task(self, client, auth_headers, tmp_path):
        fake = tmp_path / "fake.mp4"
        fake.write_bytes(b"\x00" * 1024)
        r = client.post("/api/transcode", json={"video_path": str(fake)}, headers=auth_headers)
        task_id = r.json()["task_id"]

        # 第一次删除：取消/归档
        r = client.delete(f"/api/task/{task_id}", headers=auth_headers)
        assert r.status_code == 200
        assert "已" in r.json()["message"]

        # 第二次删除应幂等（任务仍存在，只是状态被标记了）
        r = client.delete(f"/api/task/{task_id}", headers=auth_headers)
        assert r.status_code == 200

        # 但对完全不存在 task_id 的 DELETE 应返回 404
        r = client.delete("/api/task/never-existed-id", headers=auth_headers)
        assert r.status_code == 404

    def test_history(self, client, auth_headers, tmp_path):
        fake = tmp_path / "h.mp4"
        fake.write_bytes(b"\x00" * 100)
        client.post("/api/transcode", json={"video_path": str(fake)}, headers=auth_headers)

        r = client.get("/api/history", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "tasks" in body
        assert "total" in body
        assert body["total"] >= 1


# --------------------------------------------------------------------------- #
# 术语库
# --------------------------------------------------------------------------- #
class TestTerminologyAPI:
    def test_list_empty(self, client, auth_headers):
        r = client.get("/api/terminology", headers=auth_headers)
        assert r.status_code == 200

    def test_add_term(self, client, auth_headers):
        r = client.post("/api/terminology", json={
            "source_text": "测试", "translation": "test", "priority": "high"
        }, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["message"] == "术语已添加"

    def test_add_term_validation(self, client, auth_headers):
        r = client.post("/api/terminology", json={
            "source_text": "", "translation": "test"
        }, headers=auth_headers)
        assert r.status_code == 400

    def test_import_terms(self, client, auth_headers):
        import json
        payload = json.dumps([
            {"source_text": "A", "translation": "甲", "priority": "high"},
            {"source_text": "B", "translation": "乙", "priority": "medium"},
        ]).encode()
        r = client.post("/api/terminology/import", files={"file": ("t.json", payload, "application/json")}, headers=auth_headers)
        assert r.status_code == 200
        assert "导入" in r.json()["message"]

    def test_delete_term(self, client, auth_headers):
        client.post("/api/terminology", json={
            "source_text": "待删", "translation": "to-delete"
        }, headers=auth_headers)
        r = client.delete("/api/terminology/待删", headers=auth_headers)
        assert r.status_code == 200

        # 再删一次 → 404
        r = client.delete("/api/terminology/待删", headers=auth_headers)
        assert r.status_code == 404

    def test_list_with_keyword(self, client, auth_headers):
        client.post("/api/terminology", json={
            "source_text": "特定关键词XYZ", "translation": "special"
        }, headers=auth_headers)
        r = client.get("/api/terminology", params={"keyword": "XYZ"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] >= 1


# --------------------------------------------------------------------------- #
# 文件上传
# --------------------------------------------------------------------------- #
class TestUpload:
    def test_upload_ok(self, client, auth_headers):
        content = b"\x00" * 2048  # 2KB 假视频内容
        r = client.post(
            "/api/upload",
            files={"file": ("test.mp4", content, "video/mp4")},
            headers=auth_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["filename"] == "test.mp4"
        assert body["size_bytes"] == 2048
        assert os.path.isfile(body["video_path"])

    def test_upload_invalid_extension(self, client, auth_headers):
        r = client.post(
            "/api/upload",
            files={"file": ("notes.txt", b"hello", "text/plain")},
            headers=auth_headers,
        )
        assert r.status_code == 400

    def test_upload_then_transcode(self, client, auth_headers):
        # 上传文件后，用返回的 video_path 提交转码任务（端到端）
        content = b"\x00" * 1024
        r = client.post(
            "/api/upload",
            files={"file": ("movie.mp4", content, "video/mp4")},
            headers=auth_headers,
        )
        assert r.status_code == 200
        video_path = r.json()["video_path"]

        r = client.post("/api/transcode", json={"video_path": video_path}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["task_id"]


# --------------------------------------------------------------------------- #
# 缓存与队列（仅管理员）
# --------------------------------------------------------------------------- #
class TestCacheAndQueue:
    def test_cache_stats(self, client, auth_headers):
        r = client.get("/api/cache/stats", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "total_entries" in body
        assert "max_entries" in body

    def test_cache_clear(self, client, auth_headers):
        r = client.post("/api/cache/clear", headers=auth_headers)
        assert r.status_code == 200

    def test_queue_stats(self, client, auth_headers):
        r = client.get("/api/queue/stats", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "max_concurrent" in body
        assert "queue_size" in body

    def test_cache_stats_forbidden_for_user(self, client):
        user_headers = _login(client, "plainuser", "plain123")
        r = client.get("/api/cache/stats", headers=user_headers)
        assert r.status_code == 403


# --------------------------------------------------------------------------- #
# 配置与输出
# --------------------------------------------------------------------------- #
class TestConfigAndOutput:
    def test_config_reload(self, client, auth_headers):
        r = client.post("/api/config/reload", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "config" in body
        assert "llm_mode" in body["config"]

    def test_output_not_found(self, client, auth_headers):
        r = client.get("/api/output/nonexistent.srt", headers=auth_headers)
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# 数据隔离（三期）
# --------------------------------------------------------------------------- #
class TestDataIsolation:
    def test_user_cannot_see_others_tasks(self, client, tmp_path):
        alice = _login(client, "alice", "alice123")
        bob = _login(client, "bob", "bob123")

        fake = tmp_path / "iso.mp4"
        fake.write_bytes(b"\x00" * 1024)

        # alice 提交任务
        r = client.post("/api/transcode", json={"video_path": str(fake)}, headers=alice)
        assert r.status_code == 200
        task_id = r.json()["task_id"]

        # alice 能看到自己的任务
        assert client.get(f"/api/task/{task_id}", headers=alice).status_code == 200

        # bob 看不到 alice 的任务
        assert client.get(f"/api/task/{task_id}", headers=bob).status_code == 404

        # bob 的历史里也没有 alice 的任务
        r = client.get("/api/history", headers=bob)
        assert all(t["task_id"] != task_id for t in r.json()["tasks"])

    def test_user_cannot_see_others_terms(self, client):
        carol = _login(client, "carol", "carol123")
        dave = _login(client, "dave", "dave123")

        # carol 添加私有术语
        r = client.post("/api/terminology", json={
            "source_text": "私密术语", "translation": "secret"
        }, headers=carol)
        assert r.status_code == 200

        # carol 可见
        r = client.get("/api/terminology", params={"keyword": "私密术语"}, headers=carol)
        assert r.json()["total"] >= 1

        # dave 不可见（普通用户仅见系统术语 + 自己的术语）
        r = client.get("/api/terminology", params={"keyword": "私密术语"}, headers=dave)
        assert r.json()["total"] == 0

        # dave 无权删除 carol 的术语
        r = client.delete("/api/terminology/私密术语", headers=dave)
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# 配额限制（三期）
# --------------------------------------------------------------------------- #
class TestQuota:
    def test_task_quota_enforced(self, client, monkeypatch, tmp_path):
        from src.config import config as _cfg
        monkeypatch.setattr(_cfg.quota, "max_active_tasks", 0)
        headers = _login(client, "taskquota", "taskquota123")

        fake = tmp_path / "q.mp4"
        fake.write_bytes(b"\x00" * 1024)
        r = client.post("/api/transcode", json={"video_path": str(fake)}, headers=headers)
        assert r.status_code == 429

    def test_admin_exempt_from_task_quota(self, client, monkeypatch, auth_headers, tmp_path):
        from src.config import config as _cfg
        monkeypatch.setattr(_cfg.quota, "max_active_tasks", 0)

        fake = tmp_path / "a.mp4"
        fake.write_bytes(b"\x00" * 1024)
        r = client.post("/api/transcode", json={"video_path": str(fake)}, headers=auth_headers)
        assert r.status_code == 200

    def test_term_quota_enforced(self, client, monkeypatch):
        from src.config import config as _cfg
        monkeypatch.setattr(_cfg.quota, "max_terms", 0)
        headers = _login(client, "termquota", "termquota123")

        r = client.post("/api/terminology", json={"source_text": "t", "translation": "x"}, headers=headers)
        assert r.status_code == 429

    def test_upload_size_quota_enforced(self, client, monkeypatch):
        from src.config import config as _cfg
        monkeypatch.setattr(_cfg.quota, "max_upload_mb", 1)
        headers = _login(client, "uploadquota", "uploadquota123")

        # 2MB 文件，超过 1MB 上限
        content = b"\x00" * (2 * 1024 * 1024)
        r = client.post("/api/upload", files={"file": ("big.mp4", content, "video/mp4")}, headers=headers)
        assert r.status_code == 413


# --------------------------------------------------------------------------- #
# 安全加固（三期）
# --------------------------------------------------------------------------- #
class TestSecurityHardening:
    def test_security_headers_present(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("x-frame-options") == "DENY"
        assert r.headers.get("x-xss-protection") == "1; mode=block"

    def test_api_key_auth(self, client, monkeypatch):
        from src.config import config as _cfg
        monkeypatch.setattr(_cfg.security, "api_keys", ["test-api-key-123"])
        r = client.get("/api/auth/me", headers={"X-API-Key": "test-api-key-123"})
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "admin"
        assert body["user_id"] == "service-account-api-key"

    def test_invalid_api_key_rejected(self, client, monkeypatch):
        from src.config import config as _cfg
        monkeypatch.setattr(_cfg.security, "api_keys", ["test-api-key-123"])
        r = client.get("/api/auth/me", headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401

    def test_no_api_keys_configured_rejected(self, client, monkeypatch):
        from src.config import config as _cfg
        monkeypatch.setattr(_cfg.security, "api_keys", [])
        r = client.get("/api/auth/me", headers={"X-API-Key": "any-key"})
        assert r.status_code == 401

    def test_ip_blacklist_rejected(self, client, monkeypatch):
        from src.config import config as _cfg
        # TestClient 的客户端地址为 "testclient"
        monkeypatch.setattr(_cfg.security, "ip_blacklist", ["testclient"])
        r = client.get("/api/health")
        assert r.status_code == 403

    def test_ip_whitelist_enforced(self, client, monkeypatch):
        from src.config import config as _cfg
        monkeypatch.setattr(_cfg.security, "ip_whitelist", ["10.0.0.1"])
        # testclient 不在白名单内 → 拒绝
        r = client.get("/api/health")
        assert r.status_code == 403

    def test_rate_limit_triggered(self, client, monkeypatch):
        from src.config import config as _cfg
        from src.security import middleware as mw

        monkeypatch.setattr(_cfg.security, "rate_limit_enabled", True)
        monkeypatch.setattr(_cfg.security, "rate_limit_requests", 2)
        mw._rate_limiter_cache.clear()

        # /api/history 非豁免路由，前两次通过限流（未认证返回 401），第三次被限流
        assert client.get("/api/history").status_code == 401
        assert client.get("/api/history").status_code == 401
        assert client.get("/api/history").status_code == 429

    def test_auth_rate_limit_triggered(self, client, monkeypatch):
        from src.config import config as _cfg
        from src.security import middleware as mw

        monkeypatch.setattr(_cfg.security, "auth_rate_limit_requests", 2)
        mw._rate_limiter_cache.clear()

        # 登录接口（错误密码），前两次 401，第三次触发认证接口限流
        for _ in range(2):
            assert client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code == 401
        assert client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code == 429

    def test_health_exempt_from_rate_limit(self, client, monkeypatch):
        from src.config import config as _cfg
        from src.security import middleware as mw

        monkeypatch.setattr(_cfg.security, "rate_limit_requests", 1)
        mw._rate_limiter_cache.clear()

        # 健康检查豁免限流，连续多次访问均成功
        for _ in range(5):
            assert client.get("/api/health").status_code == 200


# --------------------------------------------------------------------------- #
# 备份与恢复 API（三期）
# --------------------------------------------------------------------------- #
class TestBackupApi:
    def test_backup_requires_auth_and_admin(self, client):
        # 未认证 → 401
        assert client.post("/api/admin/backup").status_code == 401
        assert client.get("/api/admin/backups").status_code == 401
        # 普通用户 → 403
        user = _login(client, "backupuser", "backupuser123")
        assert client.post("/api/admin/backup", headers=user).status_code == 403
        assert client.get("/api/admin/backups", headers=user).status_code == 403

    def test_create_and_list_backup(self, client, auth_headers):
        admin = auth_headers
        r = client.post("/api/admin/backup", headers=admin)
        assert r.status_code == 200
        bid = r.json()["id"]
        assert bid.startswith("backup_")
        assert set(r.json()["files"]) == {"terminology", "tasks", "users", "cache", "config"}

        r = client.get("/api/admin/backups", headers=admin)
        assert r.status_code == 200
        assert any(b["id"] == bid for b in r.json())

    def test_restore_backup(self, client, auth_headers):
        admin = auth_headers
        bid = client.post("/api/admin/backup", headers=admin).json()["id"]
        r = client.post(f"/api/admin/backup/{bid}/restore", headers=admin)
        assert r.status_code == 200
        body = r.json()
        assert body["backup_id"] == bid
        assert body["message"] == "备份已恢复"

    def test_delete_backup(self, client, auth_headers):
        admin = auth_headers
        bid = client.post("/api/admin/backup", headers=admin).json()["id"]
        r = client.delete(f"/api/admin/backup/{bid}", headers=admin)
        assert r.status_code == 200
        # 二次删除 → 404
        assert client.delete(f"/api/admin/backup/{bid}", headers=admin).status_code == 404

    def test_restore_missing_backup_404(self, client, auth_headers):
        admin = auth_headers
        r = client.post("/api/admin/backup/not_exist/restore", headers=admin)
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# 批量转码（三期）
# --------------------------------------------------------------------------- #
class TestBatchTranscode:
    def test_batch_requires_auth(self, client):
        r = client.post("/api/transcode/batch", json={"items": []})
        assert r.status_code == 401

    def test_batch_empty_items_422(self, client, auth_headers):
        r = client.post("/api/transcode/batch", json={"items": []}, headers=auth_headers)
        assert r.status_code == 422

    def test_batch_submit_ok(self, client, auth_headers, tmp_path):
        v1 = tmp_path / "b1.mp4"
        v2 = tmp_path / "b2.mp4"
        v1.write_bytes(b"\x00" * 1024)
        v2.write_bytes(b"\x00" * 1024)

        r = client.post("/api/transcode/batch", json={
            "items": [
                {"video_path": str(v1), "priority": "high"},
                {"video_path": str(v2), "mode": "hardsub", "priority": "low"},
            ]
        }, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert body["succeeded"] == 2
        assert body["failed"] == 0
        assert all("task_id" in t for t in body["tasks"])

    def test_batch_partial_failure(self, client, auth_headers, tmp_path):
        v1 = tmp_path / "ok.mp4"
        v1.write_bytes(b"\x00" * 1024)

        r = client.post("/api/transcode/batch", json={
            "items": [
                {"video_path": str(v1)},
                {"video_path": "Z:/missing.mp4"},
            ]
        }, headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert body["succeeded"] == 1
        assert body["failed"] == 1
        assert "error" in body["tasks"][1]

    def test_batch_quota_enforced(self, client, monkeypatch, tmp_path):
        from src.config import config as _cfg
        monkeypatch.setattr(_cfg.quota, "max_active_tasks", 2)
        headers = _login(client, "batchquota", "batchquota123")

        v1 = tmp_path / "q1.mp4"
        v2 = tmp_path / "q2.mp4"
        v3 = tmp_path / "q3.mp4"
        v1.write_bytes(b"\x00" * 1024)
        v2.write_bytes(b"\x00" * 1024)
        v3.write_bytes(b"\x00" * 1024)

        r = client.post("/api/transcode/batch", json={
            "items": [
                {"video_path": str(v1)},
                {"video_path": str(v2)},
                {"video_path": str(v3)},
            ]
        }, headers=headers)
        assert r.status_code == 429


# --------------------------------------------------------------------------- #
# 监控与告警（三期）
# --------------------------------------------------------------------------- #
class TestMonitoring:
    def test_metrics_endpoint_prometheus(self, client):
        r = client.get("/api/metrics")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        body = r.text
        # 至少包含 uptime 指标（Prometheus 文本格式）
        assert "subai_uptime_seconds" in body

    def test_metrics_records_requests(self, client):
        # 触发一个非豁免请求后，request_total 应被记录（含方法/路径标签）
        client.get("/api/history")  # 未认证返回 401，但仍会被指标中间件统计
        r = client.get("/api/metrics")
        assert 'subai_request_total{' in r.text
        assert 'method="GET"' in r.text
        assert 'path="/api/history"' in r.text

    def test_admin_metrics_requires_auth(self, client):
        assert client.get("/api/admin/metrics").status_code == 401
        user = _login(client, "monuser", "monuser123")
        assert client.get("/api/admin/metrics", headers=user).status_code == 403

    def test_admin_metrics_ok(self, client, auth_headers):
        r = client.get("/api/admin/metrics", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "snapshot" in body
        assert "metrics" in body
        # 快照包含队列相关字段
        assert "queue_size" in body["snapshot"]
        assert "max_queue_size" in body["snapshot"]

    def test_admin_alerts_requires_auth(self, client):
        assert client.get("/api/admin/alerts").status_code == 401
        user = _login(client, "alertuser", "alertuser123")
        assert client.get("/api/admin/alerts", headers=user).status_code == 403

    def test_admin_alerts_ok(self, client, auth_headers):
        r = client.get("/api/admin/alerts", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert "active" in body
        assert "history" in body
        assert isinstance(body["active"], list)
