# -*- coding: utf-8 -*-
from __future__ import annotations

from src.pipeline import _regroup


class W:
    def __init__(self, s, e, w):
        self.start, self.end, self.word = s, e, w


class Seg:
    def __init__(self, text, words):
        self.text = text
        self.start = words[0].start if words else 0.0
        self.end = words[-1].end if words else 0.0
        self.words = words


def test_fragment_merge_keeps_end():
    rows = _regroup([
        Seg("静默", [W(0.0, 0.5, "静"), W(0.5, 1.0, "默")]),
        Seg("哎", [W(4.0, 4.4, "哎")]),
    ], max_chars=10, max_dur=10)
    assert rows
    assert rows[0]["end"] <= 1.01, "结束时间不该被推到碎片处，实际 %s" % rows[0]["end"]
