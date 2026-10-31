# -*- coding: utf-8 -*-
"""字形覆盖解析测试（src/glyphs.py）。

这条功能的价值在于：ASS 只记字体名，字体缺字时 libass 会画方框，
用户只看到「字幕里冒出几个方块」却不知原因。
本模块在渲染前算出「缺哪些字」，切成独立 run 各自指定字体。

测试重点：
1. cmap format 4 与 12 都要能读（不同字体的选择不同）
2. TTC 子字体偏移（踩过的坑：表偏移是绝对偏移，不是相对子字体）
3. 不可见字符不能被当作「缺字」
4. 谁都覆盖不了时保持原样，不丢字
"""
import os
import struct

import pytest

from src import glyphs


WIN = os.name == "nt"
ARIAL = r"C:\Windows\Fonts\arial.ttf"
SIMHEI = r"C:\Windows\Fonts\simhei.ttf"
MSYH = r"C:\Windows\Fonts\msyh.ttc"


def need(path):
    if not WIN or not os.path.isfile(path):
        pytest.skip("依赖 Windows 字体: %s" % path)
    return path


# ---------------- 不可见字符 ----------------

@pytest.mark.parametrize("code,expect", [
    (0x00AD, True),    # 软连字符
    (0x200B, True),    # 零宽空格
    (0x200D, True),    # 零宽连接符
    (0xFEFF, True),    # BOM
    (0xFE0F, True),    # 变体选择符
    (0x41, False),     # A
    (0x4E2D, False),   # 中
    (0x1F600, False),  # emoji（可见，只是缺字形）
])
def test_is_invisible(code, expect):
    assert glyphs.is_invisible(code) is expect


# ---------------- 真实字体：format 4 ----------------

def test_format4_arial():
    f = glyphs.load_face(need(ARIAL))
    assert f.format == 4
    assert f.has_glyph(ord("A"))
    assert not f.has_glyph(ord("中"))


def test_format4_simhei_has_cjk():
    f = glyphs.load_face(need(SIMHEI))
    assert f.format == 4
    assert f.has_glyph(ord("中"))
    assert f.has_glyph(ord("文"))
    assert f.has_glyph(ord("龥"))       # 常用汉字区上界


def test_simhei_covers_common_cjk():
    """黑体应覆盖整个常用汉字区（CJK Unified Ideographs 基本区）。"""
    f = glyphs.load_face(need(SIMHEI))
    missing = [c for c in range(0x4E00, 0x9FA6) if not f.has_glyph(c)]
    assert missing == [], "黑体缺 %d 个常用汉字: %r" % (len(missing), missing[:10])


# ---------------- 真实字体：format 12 / TTC ----------------

def test_ttc_format12():
    """微软雅黑是 .ttc + cmap format 12。

    这里同时验证 TTC 偏移解析：如果偏移算错，会得到
    「雅黑缺『文』字」这种明显不合理的结论。
    """
    f = glyphs.load_face(need(MSYH))
    assert f.format == 12
    assert f.has_glyph(ord("中"))
    assert f.has_glyph(ord("文"))
    assert f.has_glyph(ord("龥"))
    assert f.has_glyph(ord("A"))


def test_ttc_face_index():
    """TTC 第二个子字体也要能读（越界时回落到 0）。"""
    f = glyphs.load_face(need(MSYH), face_index=1)
    assert f is not None
    assert f.has_glyph(ord("中"))


def test_ttc_index_out_of_range_falls_back():
    f = glyphs.load_face(need(MSYH), face_index=99)
    assert f is not None
    assert f.face_index == 0


# ---------------- 缺字识别 ----------------

def test_missing_codepoints():
    a = glyphs.load_face(need(ARIAL))
    assert a.missing_codepoints("敌人") == [ord("敌"), ord("人")]
    assert a.missing_codepoints("AB") == []


def test_missing_codepoints_dedup():
    """重复的字只报一次，且保持出现顺序。"""
    a = glyphs.load_face(need(ARIAL))
    assert a.missing_codepoints("敌人敌") == [ord("敌"), ord("人")]


def test_missing_skips_invisible():
    """不可见字符不算缺字 —— 否则每个带零宽字符的文本都会误报。"""
    a = glyphs.load_face(need(ARIAL))
    assert a.missing_codepoints("A\u200bB") == []


# ---------------- 切分 run ----------------

def test_split_runs_no_fallback_needed():
    """全都能覆盖时不切分，保持单一 run（避免无意义碎片）。"""
    c = glyphs.load_face(need(SIMHEI))
    runs = glyphs.split_runs("中文测试", c, [])
    assert len(runs) == 1
    assert runs[0]["text"] == "中文测试"
    assert runs[0]["font"] is c


def test_split_runs_mixed():
    """Arial 主字体 + 黑体回退：中文段被切出来。"""
    a = glyphs.load_face(need(ARIAL))
    c = glyphs.load_face(need(SIMHEI))
    runs = glyphs.split_runs("Hello 敌人 World", a, [c])
    assert [r["text"] for r in runs] == ["Hello ", "敌人", " World"]
    assert runs[0]["font"] is a
    assert runs[1]["font"] is c
    assert runs[2]["font"] is a


def test_split_runs_no_fallback_available():
    """谁也覆盖不了时保持原样，font=None。**不能丢字**。"""
    a = glyphs.load_face(need(ARIAL))
    runs = glyphs.split_runs("A中B", a, [])
    assert "".join(r["text"] for r in runs) == "A中B"
    mid = [r for r in runs if "中" in r["text"]]
    assert mid and mid[0]["font"] is None


def test_split_runs_preserves_text_exactly():
    """无论怎么切，拼起来必须与原文完全一致（不能丢字或改字）。"""
    a = glyphs.load_face(need(ARIAL))
    c = glyphs.load_face(need(SIMHEI))
    for text in ["abc", "敌人", "a敌b人c", "  空格  敌人  ", "😀敌人", ""]:
        runs = glyphs.split_runs(text, a, [c])
        assert "".join(r["text"] for r in runs) == text, text


def test_split_runs_invisible_stays_primary():
    """不可见字符留在主字体，不触发回退。"""
    a = glyphs.load_face(need(ARIAL))
    c = glyphs.load_face(need(SIMHEI))
    runs = glyphs.split_runs("A\u200bB", a, [c])
    assert len(runs) == 1
    assert runs[0]["font"] is a


def test_split_runs_empty_text():
    a = glyphs.load_face(need(ARIAL))
    assert glyphs.split_runs("", a, []) == []


# ---------------- 汇总 ----------------

def test_summarize_reports_missing():
    a = glyphs.load_face(need(ARIAL))
    runs = glyphs.split_runs("A中B", a, [])
    s = glyphs.summarize_runs(runs)
    assert s["missing_chars"] == ["中"]


def test_summarize_no_missing():
    a = glyphs.load_face(need(ARIAL))
    c = glyphs.load_face(need(SIMHEI))
    runs = glyphs.split_runs("A中B", a, [c])
    s = glyphs.summarize_runs(runs)
    assert s["missing_chars"] == []
    assert s["run_count"] == 3


# ---------------- 容错 ----------------

def test_load_face_bad_path():
    """文件不存在返回 None，不抛异常。"""
    assert glyphs.load_face("C:/nope/none.ttf") is None


def test_load_face_not_a_font(tmp_path):
    """不是字体的文件返回 None。"""
    p = tmp_path / "fake.ttf"
    p.write_bytes(b"this is not a font at all, just text")
    assert glyphs.load_face(str(p)) is None


def test_load_face_truncated(tmp_path):
    """截断文件也不能崩。"""
    p = tmp_path / "short.ttf"
    p.write_bytes(b"\x00\x01\x00\x00")
    assert glyphs.load_face(str(p)) is None


def test_font_face_rejects_tiny_file(tmp_path):
    p = tmp_path / "t.ttf"
    p.write_bytes(b"ab")
    with pytest.raises(ValueError):
        glyphs.FontFace(str(p))