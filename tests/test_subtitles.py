# -*- coding: utf-8 -*-
"""
SubAI Translator —— 字幕解析/写回与翻译后端状态测试
=====================================================

覆盖联调修复新增的两块后端能力：
1. src/subtitles.py：SRT 解析、双语/单语/JSON 装载、编辑后写回
2. src/llm.py：端点推导与状态结构（不依赖真实 LLM 在线）
"""
from __future__ import annotations

import json
import os

from src import llm as llm_module
from src.config import config
from src.subtitles import (
    _seconds_to_ts,
    _ts_to_seconds,
    load_task_segments,
    parse_srt,
    save_task_segments,
)

BILINGUAL = (
    "1\n"
    "00:00:01,000 --> 00:00:02,500\n"
    "你好世界\n"
    "Hello world\n"
    "\n"
    "2\n"
    "00:00:03,000 --> 00:00:04,000\n"
    "第二句\n"
    "Second line\n"
    "\n"
)


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


class TestTimestamps:
    def test_roundtrip(self):
        assert _seconds_to_ts(3661.5) == "01:01:01,500"
        assert _ts_to_seconds("01:01:01,500") == 3661.5

    def test_dot_separator_accepted(self):
        assert _ts_to_seconds("00:00:02.250") == 2.25

    def test_invalid_returns_zero(self):
        assert _ts_to_seconds("garbage") == 0.0


class TestParseSrt:
    def test_counts_cues(self, tmp_path):
        p = _write(tmp_path, "a.srt", BILINGUAL)
        cues = parse_srt(p)
        assert len(cues) == 2
        assert cues[0]["start"] == 1.0
        assert cues[0]["end"] == 2.5

    def test_handles_crlf(self, tmp_path):
        p = _write(tmp_path, "crlf.srt", BILINGUAL.replace("\n", "\r\n"))
        assert len(parse_srt(p)) == 2


class TestLoadTaskSegments:
    def test_prefers_json(self, tmp_path):
        data = [{"id": 1, "start": 0.0, "end": 1.0, "source": "甲", "translation": "A"}]
        j = tmp_path / "out.json"
        j.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        s = _write(tmp_path, "out.bilingual.srt", BILINGUAL)
        loaded = load_task_segments([s, str(j)])
        assert loaded["kind"] == "json"
        assert loaded["segments"][0]["translation"] == "A"

    def test_bilingual_pairs(self, tmp_path):
        s = _write(tmp_path, "out.bilingual.srt", BILINGUAL)
        loaded = load_task_segments([s])
        assert loaded["kind"] == "bilingual"
        assert loaded["segments"][0]["source"] == "你好世界"
        assert loaded["segments"][0]["translation"] == "Hello world"

    def test_mono_srt(self, tmp_path):
        mono = "1\n00:00:01,000 --> 00:00:02,000\nOnly target\n\n"
        s = _write(tmp_path, "out.en.srt", mono)
        loaded = load_task_segments([s])
        assert loaded["kind"] == "mono"
        assert loaded["segments"][0]["translation"] == "Only target"

    def test_missing_files(self):
        loaded = load_task_segments([r"Z:\nope\missing.srt"])
        assert loaded["kind"] is None and loaded["segments"] == []


class TestSaveTaskSegments:
    def test_bilingual_roundtrip_with_edit(self, tmp_path):
        p = _write(tmp_path, "b.bilingual.srt", BILINGUAL)
        loaded = load_task_segments([p])
        segs = loaded["segments"]
        segs[0]["translation"] = "Hi there"
        save_task_segments(loaded["file"], loaded["kind"], segs)
        again = load_task_segments([p])
        assert again["segments"][0]["translation"] == "Hi there"
        assert again["segments"][0]["source"] == "你好世界"
        assert len(again["segments"]) == 2

    def test_json_roundtrip(self, tmp_path):
        data = [{"id": 1, "start": 0.0, "end": 1.0, "source": "甲", "translation": "A"}]
        p = tmp_path / "c.json"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        loaded = load_task_segments([str(p)])
        loaded["segments"][0]["translation"] = "AA"
        save_task_segments(loaded["file"], loaded["kind"], loaded["segments"])
        reread = json.loads(p.read_text(encoding="utf-8"))
        assert reread[0]["translation"] == "AA"
        assert reread[0]["start_ts"] == "00:00:00,000"


class TestLlmStatus:
    def test_models_url_derivation(self):
        assert llm_module._models_url("http://x/v1/chat/completions") == "http://x/v1/models"
        assert llm_module._models_url("") == ""

    def test_probe_unconfigured(self):
        r = llm_module.probe("")
        assert r["configured"] is False and r["reachable"] is False

    def test_status_shape(self):
        s = llm_module.status()
        assert s["mode"] in ("local", "cloud", "hybrid")
        assert s["modes"] == ["local", "cloud", "hybrid"]
        assert set(s["local"].keys()) >= {"url", "model", "reachable", "detail"}
        assert "has_key" in s["cloud"] and "reachable" in s["cloud"]
        # 绝不泄露密钥
        assert "api_key" not in json.dumps(s)
