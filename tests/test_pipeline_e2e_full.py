# -*- coding: utf-8 -*-
"""
SubAI Translator —— 完整 run_pipeline 端到端测试
==================================================

链路：视频 → FFmpeg 抽音轨 → faster-whisper ASR → 翻译（本地 mock OpenAI 服务）→ 落盘。

覆盖主产品路径，且不依赖任何外部 LLM：
1. SRT 输出：译文落盘、双语文件包含原文、stats 正确
2. JSON 输出：结构与字段
3. 翻译后端不可用：仍输出 *.source.srt（原文转录）且 stats["failed"] == total

缺 FFmpeg / ASR 模型 / 测试视频 / faster-whisper 时自动跳过。
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import threading

import pytest

from src import pipeline
from src.config import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VIDEO = os.path.join(ROOT, "data", "test_speech.mp4")


def _find_ffmpeg() -> str | None:
    for c in (config.ffmpeg,
              os.path.join(os.path.dirname(ROOT), "bin", "ffmpeg.exe"),
              shutil.which("ffmpeg") or ""):
        if c and os.path.isfile(c):
            return c
    return None


def _find_model() -> str | None:
    for c in (config.models_dir,
              os.path.join(os.path.dirname(ROOT), "models", "faster-whisper-small")):
        if c and os.path.isdir(c):
            return c
    return None


FFMPEG = _find_ffmpeg()
MODEL = _find_model()

try:
    import faster_whisper  # noqa: F401
    HAS_ASR = True
except Exception:  # noqa: BLE001
    HAS_ASR = False

requires_pipeline = pytest.mark.skipif(
    FFMPEG is None or MODEL is None or not HAS_ASR or not os.path.isfile(VIDEO),
    reason="缺少 FFmpeg / ASR 模型 / 测试视频 / faster-whisper",
)


class _MockLLM:
    """极简 OpenAI 兼容服务：批量回编号译文，单行回 'T:原文'。"""

    def __init__(self):
        outer = self
        self.calls = 0

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                outer.calls += 1
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                prompt = body.get("messages", [{}])[-1].get("content", "")
                content = outer._reply(prompt)
                data = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = "http://127.0.0.1:%d/v1/chat/completions" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @staticmethod
    def _reply(prompt: str) -> str:
        if "Translate each numbered" in prompt:
            out = []
            for line in prompt.splitlines():
                s = line.strip()
                if s and s[0].isdigit() and ". " in s:
                    n, _, text = s.partition(". ")
                    out.append(n + ". T:" + text)
            return "\n".join(out)
        return "T:" + prompt

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _patch_env(monkeypatch, tmp_path):
    # 每个用例独立缓存 DB：否则上一用例写入的缓存会让"后端不可用"场景命中缓存而失真
    monkeypatch.setattr(config.cache, "db_path", str(tmp_path / "cache.db"))
    monkeypatch.setattr(pipeline, "FFMPEG", FFMPEG)
    monkeypatch.setattr(pipeline, "MODEL_DIR", MODEL)
    monkeypatch.setattr(pipeline, "TMP_DIR", str(tmp_path / "tmp"))
    monkeypatch.setattr(pipeline, "OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(config.llm, "mode", "local")
    monkeypatch.setattr(config.llm, "retry_delay", 0.0)
    monkeypatch.setattr(config.llm, "max_retries", 1)
    return tmp_path / "out"


@requires_pipeline
class TestRunPipelineEndToEnd:
    def test_srt_output_with_real_asr(self, monkeypatch, tmp_path):
        llm = _MockLLM()
        try:
            out_dir = _patch_env(monkeypatch, tmp_path)
            monkeypatch.setattr(config.llm, "local_url", llm.url)
            stats: dict = {}

            files = pipeline.run_pipeline(
                video=VIDEO, mode="asr", target_lang="en",
                output_format="srt", stats=stats,
            )

            assert stats["total"] > 0, "ASR 未产出任何字幕行"
            assert stats["failed"] == 0

            names = sorted(os.path.basename(f) for f in files)
            assert any(n.endswith(".en.srt") for n in names), names
            assert any(n.endswith(".bilingual.srt") for n in names), names
            assert all(os.path.isfile(f) for f in files)

            en = [f for f in files if f.endswith(".en.srt")][0]
            body = open(en, encoding="utf-8").read()
            assert "T:" in body, "译文未落盘：%r" % body[:200]
            assert "-->" in body
        finally:
            llm.close()

    def test_json_output_structure(self, monkeypatch, tmp_path):
        llm = _MockLLM()
        try:
            _patch_env(monkeypatch, tmp_path)
            monkeypatch.setattr(config.llm, "local_url", llm.url)
            files = pipeline.run_pipeline(
                video=VIDEO, mode="asr", target_lang="en", output_format="json",
            )
            target = [f for f in files if f.endswith(".json")][0]
            data = json.loads(open(target, encoding="utf-8").read())
            assert isinstance(data, list) and data
            assert {"start", "end", "source", "translation"} <= set(data[0])
            assert data[0]["translation"].startswith("T:")
        finally:
            llm.close()

    def test_translation_down_still_writes_source(self, monkeypatch, tmp_path):
        out_dir = _patch_env(monkeypatch, tmp_path)
        monkeypatch.setattr(config.llm, "local_url", "http://127.0.0.1:9/v1/chat/completions")
        stats: dict = {}

        files = pipeline.run_pipeline(
            video=VIDEO, mode="asr", target_lang="en", output_format="srt", stats=stats,
        )

        assert stats["total"] > 0
        assert stats["failed"] == stats["total"]
        src = [f for f in files if f.endswith(".source.srt")]
        assert src, "翻译全失败时未输出原文转录：%r" % files
        body = open(src[0], encoding="utf-8").read()
        assert "-->" in body and body.strip()
