# -*- coding: utf-8 -*-
"""
SubAI Translator —— 硬字幕 OCR 端到端测试
==========================================

这是此前**唯一没有端到端测试**的主链路。本测试不依赖外部素材：
  1. 用 PIL 渲染带中文硬字幕的画面帧（白字黑底）
  2. 用 OpenCV 写成视频（MJPG/AVI，无需 FFmpeg）
  3. 真实调用 pipeline.hardsub_segments() 跑 RapidOCR

覆盖：引擎可用性、识别准确度、相邻去重与分句、时间戳合理性。
缺依赖或字体时自动跳过。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("cv2", reason="未安装 opencv")
pytest.importorskip("rapidocr_onnxruntime", reason="未安装 rapidocr")
pytest.importorskip("PIL", reason="未安装 Pillow")
np = pytest.importorskip("numpy")

import cv2  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from src import pipeline  # noqa: E402

FONT_CANDIDATES = ["msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"]
FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


def _find_font() -> str | None:
    for name in FONT_CANDIDATES:
        p = os.path.join(FONT_DIR, name)
        if os.path.isfile(p):
            return p
    return None


FONT = _find_font()
requires_ocr = pytest.mark.skipif(FONT is None, reason="找不到可渲染中文的字体")

SIZE = (640, 360)
FPS = 10.0


def _frame(text: str):
    """渲染一帧：黑底、白色中文、画面下方居中。"""
    img = Image.new("RGB", SIZE, (0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 44)
    bbox = d.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((SIZE[0] - w) // 2, SIZE[1] - h - 36), text, fill=(255, 255, 255), font=font)
    return np.array(img)[:, :, ::-1]   # RGB -> BGR


def _make_video(path: str, phases: list[tuple[str, float]]) -> str:
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), FPS, SIZE)
    assert vw.isOpened(), "VideoWriter 打开失败"
    for text, seconds in phases:
        frame = _frame(text)
        for _ in range(int(round(seconds * FPS))):
            vw.write(frame)
    vw.release()
    return path


def _overlap(recognized: str, expected: str) -> float:
    """字符集合重合度，用于容忍 OCR 的少量误识。"""
    a, b = set(recognized), set(expected)
    return len(a & b) / max(1, len(b))


@requires_ocr
class TestHardsubEndToEnd:
    def test_recognizes_burned_chinese_subtitle(self, tmp_path):
        expected = "硬字幕识别测试"
        video = _make_video(str(tmp_path / "one.avi"), [(expected, 2.0)])

        rows = pipeline.hardsub_segments(video, sample_fps=2)

        recognized = pipeline._norm(" ".join(r["text"] for r in rows))
        assert rows, "未识别到任何字幕行"
        assert _overlap(recognized, pipeline._norm(expected)) >= 0.8, (
            "识别结果与预期差异过大：实际=%r 预期=%r" % (recognized, pipeline._norm(expected))
        )

    def test_splits_two_consecutive_lines(self, tmp_path):
        first, second = "第一句字幕", "第二句字幕"
        video = _make_video(str(tmp_path / "two.avi"), [(first, 1.5), (second, 1.5)])

        rows = pipeline.hardsub_segments(video, sample_fps=2)

        assert len(rows) >= 2, "相邻但不同的字幕未被拆分：%r" % rows
        joined = pipeline._norm(" ".join(r["text"] for r in rows))
        assert _overlap(joined, pipeline._norm(first)) >= 0.7
        assert _overlap(joined, pipeline._norm(second)) >= 0.7
        # 时间顺序：后一行不早于前一行
        assert rows[-1]["start"] >= rows[0]["start"]

    def test_timestamps_are_sane(self, tmp_path):
        total = 2.0
        video = _make_video(str(tmp_path / "ts.avi"), [("时间戳校验", total)])

        rows = pipeline.hardsub_segments(video, sample_fps=2)

        assert rows
        for r in rows:
            assert r["start"] >= 0.0
            assert r["end"] >= r["start"] + 0.4      # 实现保证 ≥ start + 0.5
            assert r["end"] <= total + 0.6           # 不应超出视频时长太多
