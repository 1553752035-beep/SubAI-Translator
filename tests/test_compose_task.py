# -*- coding: utf-8 -*-
"""`_run_compose_task`（我已有字幕文件）的三条路径。

[P0 2026-10-24] 这条链路此前只有「直接套用」一种行为，现补了「先翻译再出片」，
必须把三种情况都钉死，否则很容易退化成「悄悄不翻译」或「拿错字幕出片」：
  1. 没有目标语言      → 不翻译，直接用原字幕出片（原行为不变）
  2. 有目标语言        → 跳过识别只翻译，用**双语**字幕出片
  3. 翻译抛异常        → 任务标记 failed，绝不带着原文静默出片
"""
from __future__ import annotations

import asyncio

import pytest

from src.api import server


class FakeTaskManager:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def update_task(self, **kwargs):
        self.calls.append(kwargs)

    def last(self) -> dict:
        return self.calls[-1] if self.calls else {}


@pytest.fixture
def srt_file(tmp_path):
    p = tmp_path / "clip.source.srt"
    p.write_text("1\n00:00:01,000 --> 00:00:02,000\n今天天气很好。\n\n", encoding="utf-8")
    return str(p)


@pytest.fixture
def patched(monkeypatch, tmp_path):
    tm = FakeTaskManager()
    monkeypatch.setattr(server, "task_manager", tm)
    box: dict = {}

    def fake_run_pipeline(**kwargs):
        box["pipeline_kwargs"] = kwargs
        if kwargs.get("_raise"):
            raise RuntimeError("LLM 挂了")
        bilingual = tmp_path / "clip.bilingual.srt"
        bilingual.write_text("1\n00:00:01,000 --> 00:00:02,000\n原文\n译文\n\n", encoding="utf-8")
        target_only = tmp_path / "clip.en.srt"
        target_only.write_text("1\n00:00:01,000 --> 00:00:02,000\n译文\n\n", encoding="utf-8")
        return [str(target_only), str(bilingual)]

    async def fake_produce(task_id, video_path, files, target_lang, output_video):
        box["produce_files"] = files
        box["produce_lang"] = target_lang
        return [str(tmp_path / "out.mp4")]

    monkeypatch.setattr("src.pipeline.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(server, "_produce_video", fake_produce)
    return tm, box


def test_no_target_lang_keeps_original_behaviour(patched, tmp_path, srt_file):
    tm, box = patched
    asyncio.run(server._run_compose_task("t1", "v.mp4", srt_file, "soft"))
    assert "pipeline_kwargs" not in box, "没给目标语言却调用了翻译"
    assert box["produce_files"] == [srt_file], "应当直接套用原字幕出片"
    assert tm.last()["status"] == "completed"


def test_target_lang_translates_and_burns_bilingual(patched, tmp_path, srt_file):
    tm, box = patched
    asyncio.run(server._run_compose_task("t2", "v.mp4", srt_file, "soft", "en"))
    kw = box["pipeline_kwargs"]
    assert kw["from_srt"] == srt_file, "必须走 from_srt（跳过识别）"
    assert kw["target_lang"] == "en"
    assert box["produce_files"][0].endswith(".bilingual.srt"), "出片应当优先用双语字幕"
    assert box["produce_lang"] == "en"
    assert tm.last()["status"] == "completed"


def test_no_translate_target_is_not_translated(patched, tmp_path, srt_file):
    tm, box = patched
    asyncio.run(server._run_compose_task("t3", "v.mp4", srt_file, "soft", "none"))
    assert "pipeline_kwargs" not in box, "target=none 表示不翻译"
    assert box["produce_files"] == [srt_file]


def test_translate_failure_marks_task_failed(monkeypatch, tmp_path, srt_file):
    tm = FakeTaskManager()
    monkeypatch.setattr(server, "task_manager", tm)

    def boom(**kwargs):
        raise RuntimeError("LLM 挂了")

    async def fake_produce(*a, **k):
        raise AssertionError("翻译失败后不应该继续出片")

    monkeypatch.setattr("src.pipeline.run_pipeline", boom)
    monkeypatch.setattr(server, "_produce_video", fake_produce)
    asyncio.run(server._run_compose_task("t4", "v.mp4", srt_file, "soft", "en"))
    assert tm.last()["status"] == "failed"
    assert "翻译已有字幕失败" in tm.last()["error_message"]


def test_missing_subtitle_file_fails_fast(patched, tmp_path):
    tm, box = patched
    asyncio.run(server._run_compose_task("t5", "v.mp4", str(tmp_path / "nope.srt"), "soft", "en"))
    assert tm.last()["status"] == "failed"
    assert "没有找到字幕文件" in tm.last()["error_message"]