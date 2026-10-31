# -*- coding: utf-8 -*-
"""两段式拆分：验证 `from_srt` 只翻译、绝不触发识别。

[P0 2026-10-24] 覆盖 `run_pipeline(from_srt=...)`：
  1. 必须跳过 ASR（这里把 asr_segments 换成抛异常的桩来证明）；
  2. 时间轴必须沿用原字幕，不能被重排；
  3. 必须产出目标语言字幕与双语字幕。
"""
from __future__ import annotations

import os

import pytest

from src import pipeline


SRT = """1
00:00:01,000 --> 00:00:02,500
今天天气很好。

2
00:00:03,000 --> 00:00:04,200
欢迎使用字幕翻译软件。

"""


@pytest.fixture
def srt_file(tmp_path):
    p = tmp_path / "clip.source.srt"
    p.write_text(SRT, encoding="utf-8")
    return str(p)


def _forbid_asr(*_a, **_k):
    raise AssertionError("from_srt 模式下不允许调用 ASR")


def test_from_srt_skips_asr_and_translates(monkeypatch, tmp_path, srt_file):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(pipeline, "OUT_DIR", str(out_dir))
    # ASR 一旦被调用就失败 → 证明这条路径完全不碰识别
    monkeypatch.setattr(pipeline, "asr_segments", _forbid_asr)
    monkeypatch.setattr(pipeline, "extract_audio", _forbid_asr)
    # 摘要与翻译都替换成桩，避免依赖 LLM/网络
    monkeypatch.setattr(pipeline, "build_video_context", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "translate",
                        lambda texts, *a, **k: ["EN:" + t for t in texts])

    outs = pipeline.run_pipeline("fake.mp4", target_lang="en",
                                 from_srt=srt_file, output_format="srt")

    names = sorted(os.path.basename(p) for p in outs)
    assert "fake.en.srt" in names
    assert "fake.bilingual.srt" in names

    en = (out_dir / "fake.en.srt").read_text(encoding="utf-8")
    assert "EN:今天天气很好。" in en
    # 时间轴沿用原文件（3.000s 起），没有被重排
    assert "00:00:03,000 --> 00:00:04,200" in en


def test_from_srt_empty_file_returns_nothing(monkeypatch, tmp_path):
    empty = tmp_path / "empty.srt"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setattr(pipeline, "OUT_DIR", str(tmp_path / "out2"))
    monkeypatch.setattr(pipeline, "asr_segments", _forbid_asr)
    outs = pipeline.run_pipeline("fake.mp4", target_lang="en",
                                 from_srt=str(empty), output_format="srt")
    assert outs == []