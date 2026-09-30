# -*- coding: utf-8 -*-
"""
SubAI Translator —— 翻译链路 HTTP 集成测试
============================================

此前的测试只 mock 了内部函数；本文件用**真实 HTTP 端点**（本地临时服务器，
模拟 OpenAI 兼容接口）验证：
1. 批量编号协议：请求体正确 → 应答按行解析正确
2. 批量应答格式不合规 → 自动退回逐行翻译
3. 5xx 瞬时故障 → 重试后成功
4. 云端模式携带 Authorization: Bearer
5. 端点不可达 → 不抛异常，全部计入 stats["failed"]
"""
from __future__ import annotations

import http.server
import json
import threading

import pytest

from src import pipeline
from src.config import config


class _Server:
    """极简 OpenAI 兼容 mock 服务。handler(req_body, headers, state) -> (status, content)"""

    def __init__(self, handler):
        self.handler = handler
        self.state = {"calls": 0}
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                outer.state["calls"] += 1
                n = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(n) if n else b"{}"
                try:
                    body = json.loads(raw or b"{}")
                except Exception:  # noqa: BLE001
                    body = {}
                status, content = outer.handler(body, self.headers, outer.state)
                data = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):  # 静音
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return "http://127.0.0.1:%d/v1/chat/completions" % self.port

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _echo_numbered(body, headers, state):
    """批量 prompt -> 返回带编号的译文；单行 prompt -> 返回 'T:xxx'。"""
    prompt = body.get("messages", [{}])[-1].get("content", "")
    if "Translate each numbered" in prompt:
        out = []
        for line in prompt.splitlines():
            s = line.strip()
            if s and s[0].isdigit() and ". " in s:
                n, _, text = s.partition(". ")
                out.append(n + ". T:" + text)
        return 200, "\n".join(out)
    return 200, "T:" + prompt


def _set_local(monkeypatch, url, retry_delay=0.0):
    monkeypatch.setattr(config.llm, "mode", "local")
    monkeypatch.setattr(config.llm, "local_url", url)
    monkeypatch.setattr(config.llm, "local_model", "mock")
    monkeypatch.setattr(config.llm, "retry_delay", retry_delay)
    monkeypatch.setattr(config.llm, "max_retries", 3)


class TestTranslateOverHttp:
    def test_batch_numbered_protocol(self, monkeypatch):
        srv = _Server(_echo_numbered)
        try:
            _set_local(monkeypatch, srv.url)
            stats: dict = {}
            out = pipeline.translate(
                ["第一句", "第二句"], "en", {}, batch_size=10, use_cache=False, stats=stats
            )
            assert out == ["T:第一句", "T:第二句"]
            assert stats["failed"] == 0
            assert stats["llm_requests"] == 1        # 一次批量请求
        finally:
            srv.close()

    def test_malformed_batch_falls_back_to_per_line(self, monkeypatch):
        calls = {"n": 0}

        def handler(body, headers, state):
            calls["n"] += 1
            prompt = body.get("messages", [{}])[-1].get("content", "")
            if "\n" in prompt:                        # 批量请求 -> 返回不合规内容
                return 200, "sorry, no numbering here"
            return 200, "LINE:" + prompt

        srv = _Server(handler)
        try:
            _set_local(monkeypatch, srv.url)
            stats: dict = {}
            out = pipeline.translate(
                ["甲", "乙"], "en", {}, batch_size=10, use_cache=False, stats=stats
            )
            assert out == ["LINE:甲", "LINE:乙"]
            assert calls["n"] == 3                     # 1 次批量 + 2 次逐行
        finally:
            srv.close()

    def test_5xx_is_retried(self, monkeypatch):
        def handler(body, headers, state):
            if state["calls"] == 1:
                return 503, "busy"
            return _echo_numbered(body, headers, state)

        srv = _Server(handler)
        try:
            _set_local(monkeypatch, srv.url)
            text = pipeline._call_llm("hello", "en")
            assert text == "T:hello"
            assert srv.state["calls"] == 2              # 第一次 503 -> 重试成功
        finally:
            srv.close()

    def test_4xx_is_not_retried(self, monkeypatch):
        def handler(body, headers, state):
            return 401, "unauthorized"

        srv = _Server(handler)
        try:
            _set_local(monkeypatch, srv.url)
            with pytest.raises(RuntimeError):
                pipeline._call_llm("hello", "en")
            assert srv.state["calls"] == 1              # 4xx 立即失败，不重试
        finally:
            srv.close()

    def test_cloud_mode_sends_bearer_token(self, monkeypatch):
        seen = {}

        def handler(body, headers, state):
            seen["auth"] = headers.get("Authorization")
            seen["model"] = body.get("model")
            return _echo_numbered(body, headers, state)

        srv = _Server(handler)
        try:
            monkeypatch.setattr(config.llm, "mode", "cloud")
            monkeypatch.setattr(config.llm, "cloud_url", srv.url)
            monkeypatch.setattr(config.llm, "cloud_model", "gpt-mock")
            monkeypatch.setattr(config.llm, "cloud_api_key", "secret-key")
            monkeypatch.setattr(config.llm, "retry_delay", 0.0)
            out = pipeline.translate(["你好"], "en", {}, batch_size=10, use_cache=False)
            assert out == ["T:你好"]
            assert seen["auth"] == "Bearer secret-key"
            assert seen["model"] == "gpt-mock"
        finally:
            srv.close()

    def test_unreachable_endpoint_degrades(self, monkeypatch):
        _set_local(monkeypatch, "http://127.0.0.1:9/v1/chat/completions")
        monkeypatch.setattr(config.llm, "max_retries", 1)
        stats: dict = {}
        out = pipeline.translate(["x"], "en", {}, batch_size=10, use_cache=False, stats=stats)
        assert out == [""]
        assert stats["failed"] == 1
        assert stats["total"] == 1
