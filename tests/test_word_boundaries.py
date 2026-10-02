# -*- coding: utf-8 -*-
"""五期：_regroup 必须保留词级时间戳（拆分功能依赖它）。"""
from __future__ import annotations

from src.pipeline import _regroup


class W:
    def __init__(self, start, end, word):
        self.start = start
        self.end = end
        self.word = word


class Seg:
    def __init__(self, text, words):
        self.text = text
        self.start = words[0].start if words else 0.0
        self.end = words[-1].end if words else 0.0
        self.words = words


def test_words_kept():
    words = [W(0.0, 0.4, "我走"), W(0.4, 0.9, "东边"), W(0.9, 1.4, "你走"), W(1.4, 2.0, "西边")]
    rows = _regroup([Seg("我走东边你走西边", words)], max_chars=4, max_dur=10)
    assert rows, "至少产生一行"
    for r in rows:
        assert "words" in r, "每行都必须带 words"
        assert len(r["words"]) >= 2, "至少要有一个起点和一个终点"
        assert r["words"][0] >= 0 and r["words"][-1] <= 2.01
    # 所有词边界都应是递增的
    for r in rows:
        assert r["words"] == sorted(r["words"]), "词边界必须递增"


def test_without_words_still_works():
    class NoWords:
        pass
    seg = NoWords()
    seg.text = "没有词时间戳"
    seg.start = 1.0
    seg.end = 2.0
    rows = _regroup([seg])
    assert rows and rows[0]["words"] == [1.0, 2.0]
