# -*- coding: utf-8 -*-
"""四期深化：按 API 密钥限流 —— 单元 + API 测试。"""
from __future__ import annotations

import pytest

from src.openapi.ratelimit import KeyRateLimiter


class TestKeyRateLimiter:
    def test_basic_window(self):
        limiter = KeyRateLimiter(default_limit=3, window=60.0)
        assert [limiter.allow("k1") for _ in range(3)] == [True, True, True]
        assert limiter.allow("k1") is False          # 第 4 次超限
        assert limiter.remaining("k1") == 0

    def test_keys_are_independent(self):
        limiter = KeyRateLimiter(default_limit=2, window=60.0)
        assert limiter.allow("a") and limiter.allow("a")
        assert limiter.allow("a") is False
        assert limiter.allow("b") is True            # 另一个密钥不受影响
        assert limiter.remaining("b") == 1

    def test_per_key_override(self):
        limiter = KeyRateLimiter(default_limit=2, window=60.0)
        for _ in range(5):
            assert limiter.allow("big", limit=5) is True
        assert limiter.allow("big", limit=5) is False
        assert limiter.effective_limit(limit=5) == 5
        assert limiter.effective_limit() == 2

    def test_zero_means_unlimited(self):
        limiter = KeyRateLimiter(default_limit=0, window=60.0)
        for _ in range(50):
            assert limiter.allow("free") is True
        assert limiter.remaining("free") == -1

    def test_reset(self):
        limiter = KeyRateLimiter(default_limit=1, window=60.0)
        assert limiter.allow("x") is True and limiter.allow("x") is False
        limiter.reset("x")
        assert limiter.allow("x") is True

    def test_window_expiry(self):
        limiter = KeyRateLimiter(default_limit=1, window=0.2)
        assert limiter.allow("t") is True and limiter.allow("t") is False
        import time
        time.sleep(0.25)
        assert limiter.allow("t") is True            # 窗口滑走后恢复


@pytest.fixture
def ratelimit_env(tmp_path, monkeypatch):
    """隔离 openapi 库与限流器单例（限流器是内存态，必须重置）。"""
    from src.config import config as _cfg
    from src.openapi import keys as keys_mod
    from src.openapi import ratelimit as rl_mod
    from src.openapi import webhook as wh_mod

    monkeypatch.setattr(_cfg.paths, "openapi_db", str(tmp_path / "openapi.db"))
    monkeypatch.setattr(_cfg.openapi, "key_rate_limit", 2)   # 默认每密钥 2 次/窗口
    monkeypatch.setattr(_cfg.openapi, "key_rate_window", 60.0)
    monkeypatch.setattr(keys_mod, "_manager", None)
    monkeypatch.setattr(wh_mod, "_manager", None)
    monkeypatch.setattr(rl_mod, "_limiter", None)
    yield
    keys_mod._manager = None
    wh_mod._manager = None
    rl_mod._limiter = None


class TestRateLimitApi:
    def test_429_after_limit_with_headers(self, client, auth_headers, ratelimit_env):
        secret = client.post("/api/openapi/keys", headers=auth_headers,
                             json={"name": "限流测试"}).json()["secret"]
        headers = {"X-API-Key": secret}
        for i in range(2):
            r = client.get("/api/open/v1/me", headers=headers)
            assert r.status_code == 200, r.text
        blocked = client.get("/api/open/v1/languages", headers=headers)
        assert blocked.status_code == 429, blocked.text
        assert blocked.headers.get("Retry-After")
        assert blocked.headers.get("X-RateLimit-Limit") == "2"
        assert "过于频繁" in blocked.json()["detail"]

    def test_other_key_not_blocked(self, client, auth_headers, ratelimit_env):
        s1 = client.post("/api/openapi/keys", headers=auth_headers, json={"name": "A"}).json()["secret"]
        s2 = client.post("/api/openapi/keys", headers=auth_headers, json={"name": "B"}).json()["secret"]
        for _ in range(2):
            client.get("/api/open/v1/me", headers={"X-API-Key": s1})
        assert client.get("/api/open/v1/me", headers={"X-API-Key": s1}).status_code == 429
        assert client.get("/api/open/v1/me", headers={"X-API-Key": s2}).status_code == 200

    def test_admin_can_raise_limit(self, client, auth_headers, ratelimit_env):
        created = client.post("/api/openapi/keys", headers=auth_headers, json={"name": "C"}).json()
        secret, key_id = created["secret"], created["key"]["key_id"]
        for _ in range(2):
            client.get("/api/open/v1/me", headers={"X-API-Key": secret})
        assert client.get("/api/open/v1/me", headers={"X-API-Key": secret}).status_code == 429
        r = client.post("/api/openapi/keys/%s/rate-limit" % key_id, headers=auth_headers,
                        json={"rate_limit": 10})
        assert r.status_code == 200 and r.json()["rate_limit"] == 10
        assert client.get("/api/open/v1/me", headers={"X-API-Key": secret}).status_code == 200

    def test_zero_limit_disables_throttling(self, client, auth_headers, ratelimit_env):
        created = client.post("/api/openapi/keys", headers=auth_headers,
                              json={"name": "不限", "rate_limit": 0}).json()
        secret = created["secret"]
        assert created["key"]["rate_limit"] == 0
        for _ in range(6):
            assert client.get("/api/open/v1/me", headers={"X-API-Key": secret}).status_code == 200
        me = client.get("/api/open/v1/me", headers={"X-API-Key": secret}).json()
        assert me["rate_limit"]["remaining"] == -1        # -1 = 不限流

    def test_throttled_call_counted_as_error(self, client, auth_headers, ratelimit_env):
        secret = client.post("/api/openapi/keys", headers=auth_headers, json={"name": "D"}).json()["secret"]
        for _ in range(3):
            client.get("/api/open/v1/me", headers={"X-API-Key": secret})
        keys = client.get("/api/openapi/keys", headers=auth_headers).json()["keys"]
        entry = [k for k in keys if k["prefix"].startswith(secret[0:len(secret) - 8])] or keys
        assert any(k["error_count"] >= 1 for k in keys), keys
    def test_rate_limit_endpoint_404(self, client, auth_headers, ratelimit_env):
        r = client.post("/api/openapi/keys/key_missing/rate-limit", headers=auth_headers,
                        json={"rate_limit": 5})
        assert r.status_code == 404

