# -*- coding: utf-8 -*-
"""字形回退注入 ASS 的测试（subtitle_style._apply_glyph_fallback）。

这条功能有一个**极易犯且极难发现**的 bug：
把缺字收进缓冲区后忘了写出去，结果「缺的那些字直接消失」。
测试里必须逐字比对「去标签后是否与原文完全一致」。
"""
import re

import pytest

from src.subtitle_style import _apply_glyph_fallback, build_ass_document

CFG = {"fallback_family": "SimHei", "chars": "敌人"}


def strip_tags(s: str) -> str:
    return re.sub(r"\{[^}]*\}", "", s)


# ---------------- 不丢字是硬约束 ----------------

@pytest.mark.parametrize("text", [
    "Hello 敌人 World",
    "敌人",
    "A敌B人C",
    "无敌",
    "敌人敌人",
    "没有缺字的一行",
    "  ",
    "",
    "敌",
    "人敌",
])
def test_never_loses_text(text):
    """去标签后必须与原文逐字一致。漏写字符的 bug 会在这里被抓到。"""
    assert strip_tags(_apply_glyph_fallback(text, CFG)) == text


# ---------------- 标签正确性 ----------------

def test_wraps_missing_chars():
    assert _apply_glyph_fallback("敌人", CFG) == "{\\fnSimHei}敌人{\\fn}"


def test_mixed():
    out = _apply_glyph_fallback("Hello 敌人 World", CFG)
    assert out == "Hello {\\fnSimHei}敌人{\\fn} World"


def test_consecutive_missing_merged():
    """连续缺字合成一段，不逐字包裹（逐字会让 ASS 体积膨胀数倍）。"""
    out = _apply_glyph_fallback("敌人敌人", CFG)
    assert out.count("{\\fnSimHei}") == 1
    assert out.count("{\\fn}") == 1


def test_separated_missing_two_runs():
    out = _apply_glyph_fallback("A敌B人C", CFG)
    assert out.count("{\\fnSimHei}") == 2
    assert out == "A{\\fnSimHei}敌{\\fn}B{\\fnSimHei}人{\\fn}C"


def test_no_missing_unchanged():
    """没有缺字时原样返回，不加任何标签。"""
    assert _apply_glyph_fallback("没有缺字", CFG) == "没有缺字"


def test_empty_config_returns_text():
    assert _apply_glyph_fallback("敌人", {}) == "敌人"
    assert _apply_glyph_fallback("敌人", None) == "敌人"
    assert _apply_glyph_fallback("敌人", {"fallback_family": "", "chars": "敌"}) == "敌人"
    assert _apply_glyph_fallback("敌人", {"fallback_family": "X", "chars": ""}) == "敌人"


def test_escape_chars_not_wrapped():
    r"""反斜杠和大括号是 ASS 标签语法字符，不能包进 {\fn} 段。

    否则 \N（硬换行）会被当成「缺字」包起来，标签结构坏掉。
    """
    cfg = {"fallback_family": "SimHei", "chars": "\\{}N"}
    out = _apply_glyph_fallback("A\\NB", cfg)
    assert "{\\fnSimHei}" not in out        # 反斜杠不该被包
    assert "A\\NB" in out


# ---------------- 与 build_ass_document 集成 ----------------

def test_build_ass_applies_fallback():
    rows = [{"start": 1.0, "end": 2.0, "text": "Hello 敌人"}]
    doc = build_ass_document(rows, glyph_fallback=CFG)
    line = [l for l in doc.splitlines() if l.startswith("Dialogue")][0]
    assert "{\\fnSimHei}敌人{\\fn}" in line
    assert "Hello " in line


def test_build_ass_without_fallback_unchanged():
    """不传 glyph_fallback 时输出与改动前完全一致（零回归）。"""
    rows = [{"start": 1.0, "end": 2.0, "text": "Hello 敌人"}]
    a = build_ass_document(rows)
    b = build_ass_document(rows, glyph_fallback=None)
    assert a == b
    assert "{\\fn" not in a
    assert "Hello 敌人" in a


def test_build_ass_fallback_preserves_all_lines():
    """多行时每行都要处理，且行数不变。"""
    rows = [{"start": i, "end": i + 1, "text": "行%d 敌人" % i} for i in range(5)]
    doc = build_ass_document(rows, glyph_fallback=CFG)
    assert doc.count("Dialogue:") == 5
    for i in range(5):
        assert "行%d" % i in doc


def test_build_ass_hard_newline_still_works():
    r"""硬换行 \N 与字形回退共存，不能互相破坏。"""
    rows = [{"start": 1.0, "end": 2.0, "text": "第一行\n敌人"}]
    doc = build_ass_document(rows, glyph_fallback=CFG)
    line = [l for l in doc.splitlines() if l.startswith("Dialogue")][0]
    assert "\\N" in line            # 硬换行还在
    assert "敌人" in strip_tags(line.split(",,", 1)[1])