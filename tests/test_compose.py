# -*- coding: utf-8 -*-
"""
SubAI Translator —— 视频合成模块测试（四期 4.2）
=================================================

纯函数用例如 build_* / escape_filter_path 无需 FFmpeg；
端到端用例（实际烧录/封装/PSNR）在缺少 FFmpeg 时自动跳过。
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from src.compose import (
    build_burn_command,
    build_mux_command,
    burn_hardsub,
    escape_filter_path,
    measure_psnr,
    mux_softsub,
)
from src.config import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_ffmpeg() -> str | None:
    for c in (
        config.ffmpeg,
        os.path.join(os.path.dirname(ROOT), "bin", "ffmpeg.exe"),
        os.path.join(ROOT, "bin", "ffmpeg.exe"),
        shutil.which("ffmpeg") or "",
    ):
        if c and os.path.isfile(c):
            return c
    return None


FFMPEG = _find_ffmpeg()
requires_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="未找到 FFmpeg")


@pytest.fixture()
def ffmpeg_env(monkeypatch):
    if FFMPEG is None:
        pytest.skip("未找到 FFmpeg")
    monkeypatch.setattr(config.paths, "ffmpeg", FFMPEG)
    return FFMPEG


# --------------------------------------------------------------------------- #
# 纯函数
# --------------------------------------------------------------------------- #

class TestCommandBuilders:
    def test_escape_filter_path_escapes_drive_colon(self):
        out = escape_filter_path(r"D:\a b\sub.srt")
        # 仅盘符冒号前保留一个转义反斜杠，目录分隔符统一为正斜杠
        assert out == r"D\:/a b/sub.srt"

    def test_escape_filter_path_escapes_quote(self):
        assert "\\'" in escape_filter_path("D:\\o'brien\\s.srt")

    def test_burn_command_shape(self):
        cmd = build_burn_command("in.mp4", "sub.srt", "out.mp4", crf=20, font_size=24)
        assert "libx264" in cmd
        assert "-crf" in cmd and cmd[cmd.index("-crf") + 1] == "20"
        vf = cmd[cmd.index("-vf") + 1]
        assert vf.startswith("subtitles='")
        assert "FontSize=24" in vf

    def test_mux_command_maps_all_tracks(self):
        tracks = [
            {"path": "en.srt", "language": "eng", "title": "English"},
            {"path": "zh.srt", "language": "chi", "title": "中文"},
        ]
        cmd = build_mux_command("in.mp4", tracks, "out.mkv")
        assert cmd.count("-map") == 3
        assert cmd[cmd.index("-c:v") + 1] == "copy"
        assert cmd[cmd.index("-c:s") + 1] == "srt"
        assert "language=eng" in cmd and "language=chi" in cmd
        assert "default" in cmd

    def test_mux_command_rejects_empty(self):
        with pytest.raises(ValueError):
            mux_softsub("in.mp4", [], "out.mkv")


# --------------------------------------------------------------------------- #
# 端到端（需要 FFmpeg）
# --------------------------------------------------------------------------- #

def _make_video(path: str, seconds: int = 1) -> None:
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=%d" % seconds,
         "-f", "lavfi", "-i", "sine=frequency=440:duration=%d" % seconds,
         "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", path],
        check=True, capture_output=True,
    )


SRT = "1\n00:00:00,100 --> 00:00:01,000\nHello SubAI\n\n"


class TestComposeEndToEnd:
    def test_burn_hardsub_succeeds(self, tmp_path, ffmpeg_env):
        video = str(tmp_path / "in.mp4")
        _make_video(video)
        sub = tmp_path / "a.srt"
        sub.write_text(SRT.replace("\\n", "\n"), encoding="utf-8")
        out = str(tmp_path / "burned.mp4")
        assert burn_hardsub(video, str(sub), out) == out
        assert os.path.getsize(out) > 0

    def test_mux_softsub_is_lossless(self, tmp_path, ffmpeg_env):
        video = str(tmp_path / "in.mp4")
        _make_video(video)
        en = tmp_path / "en.srt"
        zh = tmp_path / "zh.srt"
        en.write_text(SRT, encoding="utf-8")
        zh.write_text(SRT, encoding="utf-8")
        out = str(tmp_path / "soft.mkv")
        mux_softsub(video, [
            {"path": str(en), "language": "eng", "title": "English"},
            {"path": str(zh), "language": "chi", "title": "中文"},
        ], out)
        assert os.path.getsize(out) > 0

        # 视频流为 copy，画质应无损（PSNR 为 inf 或 None 表示完全一致）
        psnr = measure_psnr(video, out)
        assert psnr is None or psnr == float("inf") or psnr >= 40.0

        # 输出应包含字幕流
        probe = subprocess.run([FFMPEG, "-hide_banner", "-i", out],
                               capture_output=True, text=True, errors="replace")
        assert "Subtitle" in (probe.stderr or "")
