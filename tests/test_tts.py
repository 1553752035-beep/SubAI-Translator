# -*- coding: utf-8 -*-
"""
SubAI Translator —— 语音合成模块测试（四期 4.1）
=================================================

纯函数与 build_dub_track 用例不依赖 SAPI；
真正调用 SAPI 的用例在非 Windows 或音色不可用时自动跳过。
"""
from __future__ import annotations

import os
import subprocess

import pytest

from src.config import config
from src.tts import (
    SAMPLE_RATE,
    WindowsSapiEngine,
    _atempo_chain,
    build_dub_track,
    get_engine,
    synthesize_segments,
    voice_for_language,
    wav_duration,
)

IS_WINDOWS = os.name == "nt"


def _find_ffmpeg() -> str | None:
    import shutil
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for c in (config.ffmpeg,
              os.path.join(os.path.dirname(root), "bin", "ffmpeg.exe"),
              shutil.which("ffmpeg") or ""):
        if c and os.path.isfile(c):
            return c
    return None


FFMPEG = _find_ffmpeg()


def _make_tone(path: str, seconds: float) -> None:
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=%.3f" % seconds,
         "-ar", str(SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", path],
        check=True, capture_output=True,
    )


# --------------------------------------------------------------------------- #
# 纯函数
# --------------------------------------------------------------------------- #

class TestAtempoChain:
    def test_within_range_is_identity(self):
        assert _atempo_chain(1.0) == [1.0]
        assert _atempo_chain(1.5) == [1.5]

    def test_large_ratio_is_chunked(self):
        factors = _atempo_chain(5.0)
        assert factors == [2.0, 2.0, 1.25]
        prod = 1.0
        for f in factors:
            prod *= f
        assert abs(prod - 5.0) < 1e-9
        assert all(0.5 <= f <= 2.0 for f in factors)

    def test_small_ratio_is_chunked(self):
        factors = _atempo_chain(0.2)
        prod = 1.0
        for f in factors:
            prod *= f
        assert abs(prod - 0.2) < 1e-9
        assert all(0.5 <= f <= 2.0 for f in factors)

    def test_non_positive_rejected(self):
        with pytest.raises(ValueError):
            _atempo_chain(0)


class TestVoiceSelection:
    VOICES = [
        {"name": "Microsoft Huihui Desktop", "culture": "zh-CN"},
        {"name": "Microsoft Zira Desktop", "culture": "en-US"},
        {"name": "Microsoft Haruka", "culture": "ja-JP"},
    ]

    def test_exact_locale(self):
        assert voice_for_language("en-US", self.VOICES) == "Microsoft Zira Desktop"

    def test_language_prefix(self):
        assert voice_for_language("zh", self.VOICES) == "Microsoft Huihui Desktop"

    def test_missing_language_returns_none(self):
        assert voice_for_language("fr", self.VOICES) is None
        assert voice_for_language("", self.VOICES) is None


# --------------------------------------------------------------------------- #
# 时间轴合并（不依赖 TTS 引擎）
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(FFMPEG is None, reason="未找到 FFmpeg")
class TestDubTrack:
    def test_offsets_and_total_duration(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config.paths, "ffmpeg", FFMPEG)
        a = str(tmp_path / "a.wav")
        b = str(tmp_path / "b.wav")
        _make_tone(a, 0.5)
        _make_tone(b, 0.5)
        out = str(tmp_path / "merged.wav")
        merged, drift = build_dub_track([(0.0, a), (1.0, b)], 2.0, out)
        assert merged == out
        assert drift == 0.0
        assert abs(wav_duration(out) - 2.0) < 0.05

    def test_overlap_is_pushed_and_reported_as_drift(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config.paths, "ffmpeg", FFMPEG)
        a = str(tmp_path / "a.wav")
        b = str(tmp_path / "b.wav")
        _make_tone(a, 1.0)
        _make_tone(b, 0.3)
        out = str(tmp_path / "merged.wav")
        _, drift = build_dub_track([(0.0, a), (0.5, b)], 2.0, out)
        assert drift >= 0.4  # 第二段被推到 1.0s，误差约 0.5s


# --------------------------------------------------------------------------- #
# SAPI 端到端（仅 Windows）
# --------------------------------------------------------------------------- #

def _sapi_available() -> bool:
    if not IS_WINDOWS:
        return False
    try:
        return len(WindowsSapiEngine().list_voices()) > 0
    except Exception:
        return False


requires_sapi = pytest.mark.skipif(not _sapi_available(), reason="无可用 Windows SAPI 音色")


@requires_sapi
class TestSapiEndToEnd:
    def test_synthesize_short_text(self, tmp_path):
        engine = get_engine("sapi")
        out = str(tmp_path / "one.wav")
        engine.synthesize("你好", out)
        assert os.path.getsize(out) > 0
        assert wav_duration(out) > 0.1

    def test_synthesize_segments_aligned(self, tmp_path):
        segments = [
            {"start": 0.0, "end": 1.2, "text": "第一句测试"},
            {"start": 1.4, "end": 3.0, "text": "第二句测试"},
        ]
        result = synthesize_segments(segments, str(tmp_path), engine=get_engine("sapi"),
                                     voice=None, fit_slot=True)
        assert os.path.exists(result["merged"])
        assert len(result["clips"]) == 2
        # 验收目标：配音与字幕时间同步误差 <= 0.5s
        assert result["max_drift_seconds"] <= 0.5
        assert abs(wav_duration(result["merged"]) - result["total_seconds"]) < 0.1
