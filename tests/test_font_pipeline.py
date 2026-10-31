# -*- coding: utf-8 -*-
"""字体管线测试（src/font_pipeline.py）。

这条把「解内嵌字体 → 加载字体 → 算缺字 → 选回退」串起来。
测试重点是**失败不能传染**：字体环节任何一步坏掉，
都必须退化成「不做回退」，而不是让整个出片失败。
"""
import os

import pytest

from src import font_pipeline as fp


WIN = os.name == "nt"
ARIAL = r"C:\Windows\Fonts\arial.ttf"
SIMHEI = r"C:\Windows\Fonts\simhei.ttf"

needs_fonts = pytest.mark.skipif(
    not WIN or not os.path.isfile(ARIAL) or not os.path.isfile(SIMHEI),
    reason="依赖 Windows 字体")


def uuencode(raw: bytes) -> str:
    out = []
    for i in range(0, len(raw), 3):
        chunk = raw[i:i + 3]
        value = 0
        for j, b in enumerate(chunk):
            value |= b << (16 - j * 8)
        for j in range(len(chunk) + 1):
            out.append(chr(((value >> (18 - j * 6)) & 0x3F) + 33))
    return "".join(out)


# ---------------- 空输入 ----------------

def test_empty_texts():
    r = fp.prepare([], "Arial", ["SimHei"])
    assert r["ok"] is True
    assert r["fallback_family"] is None


def test_blank_texts():
    r = fp.prepare(["", "   ", "\n"], "Arial", ["SimHei"])
    assert r["ok"] is True
    assert r["glyph_fallback"] is None


# ---------------- 需要回退 ----------------

@needs_fonts
def test_cjk_needs_fallback_from_arial():
    """Arial 没有中文，必须回退到黑体。"""
    r = fp.prepare(["Hello 敌人 World"], "Arial", ["SimHei"])
    assert r["ok"] is True
    assert r["fallback_family"] == "SimHei"
    assert r["glyph_fallback"]["chars"] == "敌人"
    assert r["missing_chars"] == []


@needs_fonts
def test_cjk_font_needs_no_fallback():
    """黑体本身有中文，不该画蛇添足加标签。"""
    r = fp.prepare(["敌人来了"], "SimHei", ["Arial"])
    assert r["ok"] is True
    assert r["fallback_family"] is None
    assert r["glyph_fallback"] is None


@needs_fonts
def test_picks_best_covering_font():
    """有多个候选时选覆盖最多的，不是第一个能补任意字的。

    理由：选错会引入一种字体却补不全，剩下的字仍然缺。
    """
    r = fp.prepare(["敌人"], "Arial", ["SimSun", "SimHei"])
    assert r["fallback_family"] in ("SimSun", "SimHei")
    # 两者都能覆盖中文，chars 必须包含全部缺字
    assert set(r["glyph_fallback"]["chars"]) == {"敌", "人"}


# ---------------- 谁都补不了 ----------------

@needs_fonts
def test_no_font_covers_emoji():
    """emoji 谁都覆盖不了时，如实报出来，不做假回退。"""
    r = fp.prepare(["敌人" + chr(0x1F600)], "Arial", ["SimHei"])
    assert r["ok"] is True
    # 中文能补，emoji 不能
    assert chr(0x1F600) in r["missing_chars"]
    assert "敌" in r["glyph_fallback"]["chars"]


@needs_fonts
def test_missing_chars_reported_when_nothing_covers():
    r = fp.prepare([chr(0x1F600) + chr(0x1F601)], "Arial", [])
    assert r["ok"] is True
    assert r["fallback_family"] is None
    assert set(r["missing_chars"]) == {chr(0x1F600), chr(0x1F601)}


# ---------------- 主字体不存在 ----------------

@needs_fonts
def test_unknown_primary_falls_back_silently():
    """样式里写了系统没有的字体名：退化成用第一个可用字体，不报错。"""
    r = fp.prepare(["敌人"], "完全不存在的字体XYZ", ["SimHei"])
    assert r["ok"] is True
    assert r["missing_chars"] == []


def test_no_fonts_at_all():
    """连一个字体都找不到时，ok=True 且不做回退（不是错误）。"""
    r = fp.prepare(["敌人"], "不存在的A", ["不存在的B"])
    assert r["ok"] is True
    assert r["fallback_family"] is None
    assert r["error"] is None


# ---------------- ASS 内嵌字体 ----------------

@needs_fonts
def test_embedded_font_extracted(tmp_path):
    """ASS 里自带的字体要能被解出来并参与判断。"""
    raw = open(SIMHEI, "rb").read()[:2000]     # 截断即可，只为验证提取链路
    ass = "[Fonts]\nfontname: embedded_test\n" + uuencode(raw) + "\n"
    r = fp.prepare(["敌人"], "Arial", [],
                   ass_content=ass, extract_dir=str(tmp_path))
    assert len(r["embedded_fonts"]) == 1
    assert os.path.isfile(r["embedded_fonts"][0])
    assert open(r["embedded_fonts"][0], "rb").read() == raw
    assert r["embedded_names"] == ["embedded_test"]


@needs_fonts
def test_broken_embedded_font_does_not_fail(tmp_path):
    """内嵌字体编码坏掉：只记 error，整体仍 ok。"""
    ass = "[Fonts]\nfontname: bad\nabc{\n"     # 含非法字符
    r = fp.prepare(["敌人"], "Arial", ["SimHei"],
                   ass_content=ass, extract_dir=str(tmp_path))
    assert r["ok"] is True
    assert r["error"] and "内嵌字体" in r["error"]
    # 系统字体照常工作
    assert r["fallback_family"] == "SimHei"


# ---------------- reports ----------------

@needs_fonts
def test_reports_include_primary():
    r = fp.prepare(["敌人"], "Arial", ["SimHei"])
    prim = [x for x in r["reports"] if x["family"] == "Arial"]
    assert prim and prim[0]["missing_count"] == 2


@needs_fonts
def test_reports_include_candidate_covers():
    r = fp.prepare(["敌人"], "Arial", ["SimHei"])
    cand = [x for x in r["reports"] if x["family"] == "SimHei"]
    assert cand and cand[0]["covers"] == 2 and cand[0]["needed"] == 2


# ---------------- 与 build_ass_document 串起来 ----------------

@needs_fonts
def test_end_to_end_with_ass_document():
    """管线算出的 glyph_fallback 必须能直接喂给 build_ass_document。"""
    from src.subtitle_style import build_ass_document
    r = fp.prepare(["Hello 敌人"], "Arial", ["SimHei"])
    assert r["glyph_fallback"]
    doc = build_ass_document(
        [{"start": 1.0, "end": 2.0, "text": "Hello 敌人"}],
        glyph_fallback=r["glyph_fallback"])
    line = [l for l in doc.splitlines() if l.startswith("Dialogue")][0]
    assert "{\\fnSimHei}" in line
    assert "敌人" in line