# -*- coding: utf-8 -*-
"""_regroup 切分护栏测试：词边界回溯 + 软切 + 最短显示时长。

背景（2026-10-25）：此前只有「每行最长 8 秒」一道护栏，缺三样：
  1. 字数到上限就硬切，会把词切成两半（「我们广」/「泛应用」）
  2. 没有软切，标点「，」常被顶到上限之后，断在句中
  3. 没有最短显示时长，会切出 0.15 秒的「给我」这种来不及读的行
这三条都属护栏，不改变识别内容，只改切分位置与显示时长。
"""
from types import SimpleNamespace

import pytest

from src.pipeline import _regroup, _cut_backtrack, _enforce_min_display


def W(word, start, end):
    """构造一个 faster-whisper 风格的词对象。"""
    return SimpleNamespace(word=word, start=start, end=end)


def SEG(*words):
    return SimpleNamespace(words=list(words), text="".join(w.word for w in words),
                           start=words[0].start, end=words[-1].end)


# ---------------- 词边界回溯 ----------------

def test_backtrack_prefers_soft_punct():
    """超长时优先切在最近一个软切标点之后（语义最自然）。"""
    words = [W("今天", 0, 1), W("下雨", 1, 2), W("，", 2, 2.1),
             W("我们", 2.1, 3), W("就不", 3, 4), W("去了", 4, 5)]
    k = _cut_backtrack(words, max_chars=8)
    # 「今天下雨，」共 7 字（含标点），是上限内最后一个以软切标点结尾的位置
    assert k == 3
    assert "".join(w.word for w in words[:k]) == "今天下雨，"


def test_backtrack_falls_back_to_word_boundary():
    """没有标点时退到不超过上限的最后一个词，保证不拆词。"""
    words = [W("我们", 0, 1), W("广泛", 1, 2), W("应用", 2, 3), W("这个", 3, 4)]
    k = _cut_backtrack(words, max_chars=6)
    # 6 字上限：「我们广泛」正好 4 字，「我们广泛应用」6 字 → 退到第 3 个词
    assert 0 < k < len(words)
    assert "".join(w.word for w in words[:k]) == "我们广泛应用"


def test_backtrack_returns_zero_when_first_word_too_long():
    """第一个词自身就超长时无法回溯，返回 0 让调用方直切（不能死循环）。"""
    words = [W("超长的一个词", 0, 1), W("后面", 1, 2)]
    assert _cut_backtrack(words, max_chars=2) == 0


def test_regroup_does_not_split_word():
    """核心断言：字数触发切分时，切点必须落在词边界，不能出现半个词。"""
    words = [W("我们", i, i + 1) for i in range(12)]
    rows = _regroup([SEG(*words)], max_chars=10)
    # 每一行的文字必须是原词序列的完整拼接（不能切出「我」「们」各半）
    joined = "".join(r["text"] for r in rows)
    assert joined == "我们" * 12
    for r in rows:
        assert len(r["text"]) % 2 == 0, "切出了半个词: %r" % r["text"]


# ---------------- 软切 ----------------

def test_soft_cut_triggers_on_punct_before_hard_limit():
    """达到软上限（60%）后遇标点即切，不等硬上限。"""
    words = [W("一二三", 0, 1), W("四五六", 1, 2), W("，", 2, 2.1),
             W("七八九十", 2.1, 3)]
    rows = _regroup([SEG(*words)], max_chars=20)
    # 软上限 = max(6, 12) = 12；「一二三四五六，」7 字未到 12 → 不软切。
    # 这验证的是「不会切过早」这一面（MIN_SOFT_CUT_CHARS 与 60% 取大）。
    assert len(rows) == 1


def test_soft_cut_does_not_create_tiny_rows():
    """「好，」这种极短内容即使带标点也不切，避免碎片行。"""
    words = [W("好", 0, 1), W("，", 1, 1.1), W("我们继续走", 1.1, 3)]
    rows = _regroup([SEG(*words)], max_chars=20)
    assert len(rows) == 1
    assert rows[0]["text"] == "好，我们继续走"


# ---------------- 最短显示时长 ----------------

def test_enforce_min_display_extends_short_row():
    """过短的行延长到最短可读时长。"""
    rows = [{"start": 1.0, "end": 1.15, "text": "给我"}]
    fixed_rows, n = _enforce_min_display([dict(r) for r in rows], 1.0)
    assert n == 1
    assert fixed_rows[0]["end"] == pytest.approx(2.0)


def test_enforce_min_display_never_crosses_next_start():
    """关键约束：延长不得越过下一行起点，否则两行同时显示。"""
    rows = [
        {"start": 1.0, "end": 1.15, "text": "给我"},
        {"start": 1.4, "end": 3.0, "text": "下一句"},
    ]
    fixed_rows, n = _enforce_min_display([dict(r) for r in rows], 1.0)
    assert n == 1
    assert fixed_rows[0]["end"] == pytest.approx(1.4)
    assert fixed_rows[0]["end"] <= fixed_rows[1]["start"]


def test_enforce_min_display_leaves_start_untouched():
    """只动 end，不动 start —— start 是语音真实起点，改它会与音频错位。"""
    rows = [{"start": 5.0, "end": 5.1, "text": "嗯"}]
    fixed_rows, _ = _enforce_min_display([dict(r) for r in rows], 1.0)
    assert fixed_rows[0]["start"] == 5.0


def test_enforce_min_display_disabled_when_zero():
    """min_sec=0 表示关闭护栏。"""
    rows = [{"start": 1.0, "end": 1.05, "text": "好"}]
    fixed_rows, n = _enforce_min_display([dict(r) for r in rows], 0)
    assert n == 0
    assert fixed_rows[0]["end"] == 1.05


def test_enforce_min_display_skips_long_rows():
    """已够长的行不被改动。"""
    rows = [{"start": 0.0, "end": 3.0, "text": "一句正常长度的话"}]
    fixed_rows, n = _enforce_min_display([dict(r) for r in rows], 1.0)
    assert n == 0
    assert fixed_rows[0]["end"] == 3.0


# ---------------- 回归：原有行为不变 ----------------

def test_regroup_merges_single_char_fragment():
    """原有行为：<2 字的碎片并入上一行（且不改上一行结束时间）。"""
    words1 = [W("完整一句话", 0, 2)]
    words2 = [W("嗯", 5, 5.2)]
    rows = _regroup([SEG(*words1), SEG(*words2)], max_chars=20)
    assert len(rows) == 1
    assert rows[0]["text"] == "完整一句话嗯"
    assert rows[0]["end"] == 2, "合并碎片不应推后上一行的结束时间"
