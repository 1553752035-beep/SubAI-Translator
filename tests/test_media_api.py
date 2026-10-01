# -*- coding: utf-8 -*-
"""
SubAI Translator —— 四期媒体端点测试
======================================

覆盖此前**完全没有 HTTP 层测试**的三个端点：
    POST /api/video/burn   硬字幕压制（4.2）
    POST /api/video/mux    软字幕封装（4.2）
    POST /api/tts/dub      配音音轨生成（4.1）

重型依赖（FFmpeg 压制、TTS 合成）以 monkeypatch 替换，测试聚焦在：
鉴权、入参校验、参数透传、产物落点与**能否通过 /api/output 下载**。
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_API_TESTS"),
    reason="需要 RUN_API_TESTS=1 才执行 API 集成测试",
)


@pytest.fixture
def media_files(tmp_path):
    """伪造的视频与字幕文件（内容无所谓，端点只校验存在性）"""
    video = tmp_path / "v.mp4"
    video.write_bytes(b"fake-video")
    sub = tmp_path / "s.srt"
    sub.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8")
    return str(video), str(sub)


class TestBurnEndpoint:
    def test_requires_auth(self, client, media_files):
        v, s = media_files
        r = client.post("/api/video/burn", json={"video_path": v, "subtitle_path": s})
        assert r.status_code == 401

    def test_missing_files_return_404(self, client, auth_headers, tmp_path):
        r = client.post("/api/video/burn", headers=auth_headers, json={
            "video_path": str(tmp_path / "nope.mp4"),
            "subtitle_path": str(tmp_path / "nope.srt"),
        })
        assert r.status_code == 404

    def test_burn_passes_params_and_output_is_downloadable(self, client, auth_headers, media_files, monkeypatch):
        import src.api.server as server_mod
        v, s = media_files
        captured: dict = {}

        def fake_burn(video, subtitle, out_path, **kw):
            captured.update(video=video, subtitle=subtitle, out=out_path, kw=kw)
            with open(out_path, "wb") as f:
                f.write(b"fake-mp4")

        monkeypatch.setattr(server_mod, "burn_hardsub", fake_burn)

        r = client.post("/api/video/burn", headers=auth_headers, json={
            "video_path": v, "subtitle_path": s, "crf": 20, "preset": "fast", "font_size": 30,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["filename"].endswith(".hardsub.mp4")
        assert os.path.isfile(body["output_path"])
        assert captured["video"] == v and captured["subtitle"] == s
        assert captured["kw"]["crf"] == 20 and captured["kw"]["preset"] == "fast"
        assert captured["kw"]["font_size"] == 30

        d = client.get("/api/output/" + body["filename"], headers=auth_headers)
        assert d.status_code == 200 and d.content == b"fake-mp4"


class TestMuxEndpoint:
    def test_requires_track(self, client, auth_headers, media_files):
        v, _ = media_files
        r = client.post("/api/video/mux", headers=auth_headers,
                        json={"video_path": v, "tracks": []})
        assert r.status_code == 422          # 至少一条字幕轨

    def test_mux_builds_tracks_and_returns_mkv(self, client, auth_headers, media_files, monkeypatch):
        import src.api.server as server_mod
        v, s = media_files
        captured: dict = {}

        def fake_mux(video, tracks, out_path):
            captured.update(video=video, tracks=tracks, out=out_path)
            with open(out_path, "wb") as f:
                f.write(b"fake-mkv")

        monkeypatch.setattr(server_mod, "mux_softsub", fake_mux)

        r = client.post("/api/video/mux", headers=auth_headers, json={
            "video_path": v,
            "tracks": [{"path": s, "language": "zh", "title": "中文"}],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["filename"].endswith(".softsub.mkv")
        assert captured["tracks"][0]["language"] == "zh"
        assert client.get("/api/output/" + body["filename"], headers=auth_headers).status_code == 200


class TestDubEndpoint:
    def _fake_engine(self):
        class _Engine:
            name = "fake-engine"

            def list_voices(self):
                return [{"name": "voice-a", "culture": "zh-CN", "engine": self.name}]

        return _Engine()

    def test_requires_auth(self, client):
        r = client.post("/api/tts/dub", json={"segments": [{"start": 0, "end": 1, "text": "你好"}]})
        assert r.status_code == 401

    def test_voices_lists_engine_and_voices(self, client, auth_headers, monkeypatch):
        import src.api.server as server_mod
        monkeypatch.setattr(server_mod, "get_tts_engine", lambda: self._fake_engine())
        r = client.get("/api/tts/voices", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["engine"] == "fake-engine"
        assert body["voices"][0]["name"] == "voice-a"

    def test_dub_merged_file_lands_in_output_root_and_downloads(
        self, client, auth_headers, monkeypatch, tmp_path
    ):
        """回归：合并音轨原先落在 dub_xxx/ 子目录，而 /api/output/{filename} 不接受子目录，
        导致前端拿不到配音结果。现在必须落在输出根目录并可直接下载。"""
        import src.api.server as server_mod
        monkeypatch.setattr(server_mod, "get_tts_engine", lambda: self._fake_engine())

        def fake_synth(segments, out_dir, **kw):
            os.makedirs(out_dir, exist_ok=True)
            merged = os.path.join(out_dir, kw.get("merged_name") or "m.wav")
            with open(merged, "wb") as f:
                f.write(b"RIFF-fake")
            return {"merged": merged, "clips": [], "max_drift_seconds": 0.0, "total_seconds": 2.0}

        monkeypatch.setattr(server_mod, "synthesize_segments", fake_synth)

        r = client.post("/api/tts/dub", headers=auth_headers, json={
            "segments": [{"start": 0.0, "end": 2.0, "text": "你好，世界"}],
            "voice": "voice-a",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["voice"] == "voice-a" and body["engine"] == "fake-engine"
        assert body["filename"], "应返回可直接下载的文件名"
        assert "/" not in body["filename"] and "\\" not in body["filename"], body["filename"]
        assert os.path.isfile(body["merged"])
        assert os.path.isfile(os.path.join(server_mod.config.out_dir, body["filename"]))

        d = client.get("/api/output/" + body["filename"], headers=auth_headers)
        assert d.status_code == 200 and d.content == b"RIFF-fake"

    def test_default_merged_name_is_unique_per_call(self, client, auth_headers, monkeypatch):
        """回归：默认名固定为 dub_merged.wav 时，多次配音会互相覆盖。"""
        import src.api.server as server_mod
        monkeypatch.setattr(server_mod, "get_tts_engine", lambda: self._fake_engine())
        seen: list = []

        def fake_synth(segments, out_dir, **kw):
            os.makedirs(out_dir, exist_ok=True)
            merged = os.path.join(out_dir, kw.get("merged_name") or "m.wav")
            with open(merged, "wb") as f:
                f.write(b"RIFF")
            seen.append(os.path.basename(merged))
            return {"merged": merged, "clips": [], "max_drift_seconds": 0.0, "total_seconds": 1.0}

        monkeypatch.setattr(server_mod, "synthesize_segments", fake_synth)
        payload = {"segments": [{"start": 0.0, "end": 1.0, "text": "一"}]}
        for _ in range(2):
            assert client.post("/api/tts/dub", headers=auth_headers, json=payload).status_code == 200
        assert len(set(seen)) == 2, "两次配音不应共用同一个默认文件名: %r" % seen


class TestDubVoiceMatching:
    """配音的"音色是否匹配目标语言"与"静音段"必须回传给前端（否则用户拿到全静音音轨）。"""

    class _EnOnlyEngine:
        name = "fake-en"

        def list_voices(self):
            return [{"name": "en-voice", "culture": "en-US", "engine": self.name}]

    def _fake_synth(self, silent_clips: int):
        def fake(segments, out_dir, **kw):
            os.makedirs(out_dir, exist_ok=True)
            merged = os.path.join(out_dir, kw.get("merged_name") or "m.wav")
            with open(merged, "wb") as f:
                f.write(b"RIFF")
            return {
                "merged": merged, "clips": [], "max_drift_seconds": 0.0, "total_seconds": 1.0,
                "silent_clips": silent_clips, "silent_indices": list(range(silent_clips)),
            }

        return fake

    def test_voice_matched_false_and_silent_clips_reported(self, client, auth_headers, monkeypatch):
        import src.api.server as server_mod
        monkeypatch.setattr(server_mod, "get_tts_engine", lambda: self._EnOnlyEngine())
        monkeypatch.setattr(server_mod, "synthesize_segments", self._fake_synth(1))

        r = client.post("/api/tts/dub", headers=auth_headers, json={
            "segments": [{"start": 0.0, "end": 1.0, "text": "你好"}],
            "language": "zh",          # 只有 en 音色 -> 无法匹配
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["voice_matched"] is False
        assert body["silent_clips"] == 1
        assert body["silent_indices"] == [0]

    def test_voice_matched_true_when_language_matches(self, client, auth_headers, monkeypatch):
        import src.api.server as server_mod
        monkeypatch.setattr(server_mod, "get_tts_engine", lambda: self._EnOnlyEngine())
        monkeypatch.setattr(server_mod, "synthesize_segments", self._fake_synth(0))

        r = client.post("/api/tts/dub", headers=auth_headers, json={
            "segments": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
            "language": "en",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["voice_matched"] is True
        assert body["silent_clips"] == 0

    def test_explicit_voice_never_reports_mismatch(self, client, auth_headers, monkeypatch):
        import src.api.server as server_mod
        monkeypatch.setattr(server_mod, "get_tts_engine", lambda: self._EnOnlyEngine())
        monkeypatch.setattr(server_mod, "synthesize_segments", self._fake_synth(0))

        r = client.post("/api/tts/dub", headers=auth_headers, json={
            "segments": [{"start": 0.0, "end": 1.0, "text": "你好"}],
            "language": "zh",
            "voice": "en-voice",       # 用户显式指定 -> 不算"未匹配"
        })
        assert r.status_code == 200, r.text
        assert r.json()["voice_matched"] is True
