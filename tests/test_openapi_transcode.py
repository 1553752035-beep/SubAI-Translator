# -*- coding: utf-8 -*-
"""四期深化：开放 API 建任务（multipart 上传 + 每密钥每日配额）。"""
from __future__ import annotations

import pytest


@pytest.fixture
def open_env(tmp_path, monkeypatch):
    """隔离 openapi 库 / 限流器 / 上传目录，并收紧每日配额用于测试。"""
    from src.config import config as _cfg
    from src.openapi import keys as keys_mod
    from src.openapi import ratelimit as rl_mod
    from src.openapi import webhook as wh_mod

    monkeypatch.setattr(_cfg.paths, "openapi_db", str(tmp_path / "openapi.db"))
    monkeypatch.setattr(_cfg.paths, "uploads_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(_cfg.openapi, "key_rate_limit", 0)      # 本文件不测限流
    monkeypatch.setattr(_cfg.openapi, "key_daily_tasks", 2)     # 便于触发配额
    monkeypatch.setattr(keys_mod, "_manager", None)
    monkeypatch.setattr(wh_mod, "_manager", None)
    monkeypatch.setattr(rl_mod, "_limiter", None)
    yield
    keys_mod._manager = None
    wh_mod._manager = None
    rl_mod._limiter = None


def make_key(client, auth_headers, scopes=None, name="转码密钥"):
    body = client.post("/api/openapi/keys", headers=auth_headers,
                       json={"name": name, "scopes": scopes}).json()
    return body["secret"], body["key"]["key_id"]


def upload(client, secret, filename="demo.mp4", payload=b"fake-video-bytes", **form):
    data = {"mode": "asr", "target_lang": "English", "output_format": "srt"}
    data.update(form)
    return client.post("/api/open/v1/transcode", headers={"X-API-Key": secret},
                       files={"file": (filename, payload, "video/mp4")}, data=data)


class TestOpenTranscode:
    def test_create_task_and_quota_counter(self, client, auth_headers, open_env):
        secret, _ = make_key(client, auth_headers)
        r = upload(client, secret)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["task_id"] and body["status"] in ("pending", "queued", "running")
        assert body["size_bytes"] == len(b"fake-video-bytes")
        assert body["quota"]["daily_limit"] == 2 and body["quota"]["used_today"] == 1

    def test_created_task_is_queryable(self, client, auth_headers, open_env):
        secret, _ = make_key(client, auth_headers, scopes=["transcode", "tasks"])
        created = upload(client, secret).json()
        got = client.get("/api/open/v1/tasks/%s" % created["task_id"],
                         headers={"X-API-Key": secret})
        assert got.status_code == 200, got.text
        assert got.json()["task_id"] == created["task_id"]

    def test_reject_bad_extension(self, client, auth_headers, open_env):
        secret, _ = make_key(client, auth_headers)
        r = upload(client, secret, filename="notes.txt")
        assert r.status_code == 400 and "不支持的文件类型" in r.json()["detail"]

    def test_scope_required(self, client, auth_headers, open_env):
        secret, _ = make_key(client, auth_headers, scopes=["languages"])
        r = upload(client, secret)
        assert r.status_code == 403, r.text

    def test_daily_quota_exceeded(self, client, auth_headers, open_env):
        secret, _ = make_key(client, auth_headers)
        assert upload(client, secret).status_code == 200
        assert upload(client, secret).status_code == 200
        third = upload(client, secret)
        assert third.status_code == 429, third.text
        assert "每日任务上限" in third.json()["detail"]

    def test_requires_api_key(self, client, open_env):
        r = client.post("/api/open/v1/transcode",
                        files={"file": ("a.mp4", b"x", "video/mp4")},
                        data={"target_lang": "English"})
        assert r.status_code == 401

    def test_quota_zero_means_unlimited(self, client, auth_headers, open_env, monkeypatch):
        from src.config import config as _cfg
        monkeypatch.setattr(_cfg.openapi, "key_daily_tasks", 0)
        secret, _ = make_key(client, auth_headers)
        for _ in range(3):
            assert upload(client, secret).status_code == 200

