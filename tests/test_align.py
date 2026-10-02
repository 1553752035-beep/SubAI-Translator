# -*- coding: utf-8 -*-
"""五期：打字自动对轴（src/align.py）单元测试。"""
from __future__ import annotations

from src.align import align_script_to_speech, line_weight


def seg(s, e, text="x"):
    return {"start": s, "end": e, "text": text}


class TestWeights:
    def test_cjk_counts_per_char(self):
        assert line_weight("你好世界") == 4.0

    def test_latin_counts_per_word(self):
        assert line_weight("hello world") == 2.0

    def test_longer_line_weighs_more(self):
        assert line_weight("这是一句很长很长的话") > line_weight("短")

    def test_empty_is_minimum(self):
        assert line_weight("") == 1.0


class TestAlign:
    def test_empty_inputs(self):
        assert align_script_to_speech([], [seg(0, 2)]) == []
        assert align_script_to_speech(["a"], []) == []

    def test_equal_counts_maps_one_to_one(self):
        rows = [seg(0.0, 2.0), seg(3.0, 5.0), seg(6.5, 8.0)]
        out = align_script_to_speech(["第一句", "第二句", "第三句"], rows)
        assert [s["text"] for s in out] == ["第一句", "第二句", "第三句"]
        assert (out[0]["start"], out[0]["end"]) == (0.0, 2.0)
        assert (out[2]["start"], out[2]["end"]) == (6.5, 8.0)

    def test_proportional_stays_inside_speech(self):
        # 两段语音（中间 2 秒空白），三行稿子
        rows = [seg(0.0, 4.0), seg(6.0, 10.0)]
        out = align_script_to_speech(["一句", "二句", "三句"], rows)
        assert len(out) == 3
        for s in out:
            inside = any(seg_s <= s["start"] <= seg_e or seg_s <= s["end"] <= seg_e
                         for seg_s, seg_e in [(0.0, 4.0), (6.0, 10.0)])
            assert inside, s

    def test_monotonic_and_non_overlapping(self):
        rows = [seg(0.0, 3.0), seg(3.0, 6.0)]
        out = align_script_to_speech(["一", "二", "三", "四", "五"], rows)
        for a, b in zip(out, out[1:]):
            assert a["end"] <= b["start"] + 1e-6, (a, b)

    def test_longer_line_gets_more_time(self):
        # 注意用 3 行 vs 2 段，避开"段数相等→一对一"的捷径，才会走比例分摊
        rows = [seg(0.0, 10.0), seg(10.0, 20.0)]
        out = align_script_to_speech(["短", "这是一句很长很长很长的话", "中等长度的话"], rows)
        short_dur = out[0]["end"] - out[0]["start"]
        long_dur = out[1]["end"] - out[1]["start"]
        assert long_dur > short_dur

    def test_min_duration_applied(self):
        rows = [seg(0.0, 1.0), seg(1.0, 2.0)]
        out = align_script_to_speech(["一", "二", "三", "四"], rows, min_duration=0.5)
        for s in out:
            assert s["end"] - s["start"] >= 0.3 - 1e-6

    def test_ignores_blank_lines(self):
        rows = [seg(0.0, 2.0), seg(3.0, 5.0)]
        out = align_script_to_speech(["  第一句  ", "", "  ", "第二句"], rows)
        assert [s["text"] for s in out] == ["第一句", "第二句"]

