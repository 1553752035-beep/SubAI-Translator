# -*- coding: utf-8 -*-
"""四期 4.5 —— 官方 SDK 测试（Python）。"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

# 保证能 import sdk.python.subai（测试从仓库根跑，但显式加一次更稳）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from sdk.python.subai import SubAIClient, SubAIError, verify_webhook  # noqa: E402


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/open/v1/me"):
            if self.headers.get("X-API-Key") == "subai_test":
                self._send(200, {"key": {"key_id": "key_1", "name": "测试"}})
            else:
                self._send(401, {"detail": "密钥无效"})
        elif self.path.startswith("/api/open/v1/languages"):
            self._send(200, {"languages": [{"code": "zh"}], "stats": {"total": 72, "asr": 44}})
        else:
            self._send(404, {"detail": "任务不存在"})

    def do_POST(self):  # noqa: N802
        # 先一次性读完 body；multipart 与 JSON 都在这里分流，避免"读两次读了空"
        length = int(self.headers.get("Content-Length") or 0)
        raw_body = self.rfile.read(length) or b""
        if self.path == "/api/open/v1/transcode":
            raw = raw_body.decode("utf-8", "replace")
            ok = ('name="file"' in raw) and ('name="target_lang"' in raw) and ("demo.mp4" in raw)
            self._send(200, {"task_id": "t_demo" if ok else "", "status": "pending",
                             "size_bytes": len(raw_body),
                             "quota": {"daily_limit": 20, "used_today": 1}})
            return
        payload = json.loads(raw_body or b"{}")
        if self.path == "/api/open/v1/translate":
            texts = payload.get("texts") or []
            self._send(200, {"translations": ["T:" + t for t in texts],
                             "target": "en", "count": len(texts)})
        else:
            self._send(404, {"detail": "no route"})

    def log_message(self, *args):
        return


@pytest.fixture(scope="module")
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


class TestPythonSdk:
    def test_me_ok(self, server):
        client = SubAIClient(server, api_key="subai_test")
        assert client.me()["key"]["key_id"] == "key_1"

    def test_me_unauthorized(self, server):
        client = SubAIClient(server, api_key="subai_bad")
        with pytest.raises(SubAIError) as ei:
            client.me()
        assert ei.value.status == 401
        assert "密钥无效" in ei.value.detail

    def test_languages(self, server):
        client = SubAIClient(server, api_key="subai_test")
        body = client.languages()
        assert body["stats"]["total"] == 72

    def test_translate(self, server):
        client = SubAIClient(server, api_key="subai_test")
        body = client.translate(["甲", "乙"], "English", terms={"甲": "A"})
        assert body["translations"] == ["T:甲", "T:乙"]
        assert body["count"] == 2

    def test_task_not_found(self, server):
        client = SubAIClient(server, api_key="subai_test")
        with pytest.raises(SubAIError) as ei:
            client.task("missing")
        assert ei.value.status == 404

    def test_connection_error(self):
        client = SubAIClient("http://127.0.0.1:9", api_key="subai_test", timeout=2)
        with pytest.raises(SubAIError) as ei:
            client.me()
        assert ei.value.status == 0

    def test_empty_base_url_rejected(self):
        with pytest.raises(ValueError):
            SubAIClient("")

    def test_verify_webhook(self):
        secret, body = "s3cret", b'{"event":"task.completed"}'
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert verify_webhook(secret, body, sig) is True
        assert verify_webhook(secret, body, "sha256=" + sig) is True
        assert verify_webhook(secret, body, "bad") is False
        assert verify_webhook("other", body, sig) is False
        assert verify_webhook(secret, body, "") is False

class TestPythonSdkTranscode:
    def test_transcode_builds_multipart(self, server, tmp_path):
        video = tmp_path / "demo.mp4"
        video.write_bytes(b"fake-video-bytes")
        client = SubAIClient(server, api_key="subai_test")
        r = client.transcode(str(video), "English")
        assert r["task_id"] == "t_demo"          # 服务端确认收到了 file/target_lang 字段
        assert r["quota"]["used_today"] == 1

    def test_transcode_missing_file(self, server):
        client = SubAIClient(server, api_key="subai_test")
        with pytest.raises(FileNotFoundError):
            client.transcode("/no/such/file.mp4", "English")
