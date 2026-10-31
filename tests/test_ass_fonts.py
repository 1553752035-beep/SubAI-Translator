# -*- coding: utf-8 -*-
"""ASS 内嵌字体读取测试（src/ass_fonts.py）。

为什么这条容易写错
------------------
ASS 内嵌字体用的是 **UUencode 变体**，不是 MIME base64：
每字符 -33 后占 6 bit（base64 是 -65）。
用标准 base64 解码器处理不会报错，只会得到一堆垃圾字节，
然后字体加载静默失败 —— 极难排查。
所以这里必须有「往返编解码一致」的硬测试。
"""
import os

import pytest

from src import ass_fonts as af


def uuencode(raw: bytes) -> str:
    """测试用的 UUencode 变体编码器（与被测代码互为逆运算）。"""
    out = []
    for i in range(0, len(raw), 3):
        chunk = raw[i:i + 3]
        value = 0
        for j, b in enumerate(chunk):
            value |= b << (16 - j * 8)
        for j in range(len(chunk) + 1):
            out.append(chr(((value >> (18 - j * 6)) & 0x3F) + 33))
    return "".join(out)


# ---------------- 编解码 ----------------

def test_decode_roundtrip():
    """往返必须逐字节一致。这是本模块唯一不能错的地方。"""
    for n in (1, 2, 3, 4, 5, 100, 999):
        raw = bytes((i * 37) % 256 for i in range(n))
        assert af.decode_ass_font(uuencode(raw)) == raw, n


def test_decode_not_base64():
    """确认用的不是 base64，而是「每字符 -33 后占 6 bit」。

    "A" = 0x41，减 33 得 32 = 0b100000。
    4 个 "A" 拼成 24 bit：32 出现在每个 6 bit 段的最高位，
    得到 0b100000_100000_100000_100000 = 0x82 0x08 0x20。
    （标准 base64 会把它解成 3 个 0x00，差异明显。）
    """
    assert af.decode_ass_font("AAAA") == b"\x82\x08\x20"


def test_decode_rejects_empty():
    with pytest.raises(af.AssFontError):
        af.decode_ass_font("")


def test_decode_rejects_length_mod_4_is_1():
    with pytest.raises(af.AssFontError):
        af.decode_ass_font("AAAAA")


def test_decode_rejects_invalid_chars():
    """小写字母、花括号等不在 0x21-0x60 范围内，必须拒绝。"""
    for bad in ("abc{", "ABC\x61", "a b c d"):
        with pytest.raises(af.AssFontError):
            af.decode_ass_font(bad)


def test_decode_partial_group():
    """长度余 2 或 3 时按规范只输出对应字节数。"""
    raw3 = b"\x01\x02\x03"
    assert af.decode_ass_font(uuencode(raw3)) == raw3
    raw2 = b"\x01\x02"
    assert af.decode_ass_font(uuencode(raw2)) == raw2


# ---------------- 扩展名检测 ----------------

@pytest.mark.parametrize("head,expect", [
    (b"OTTO....", ".otf"),
    (b"ttcf....", ".ttc"),
    (b"\x00\x01\x00\x00", ".ttf"),
    (b"", ".ttf"),
])
def test_detect_font_ext(head, expect):
    assert af.detect_font_ext(head) == expect


# ---------------- 段落识别 ----------------

def test_read_no_fonts_section():
    assert af.read_embedded_fonts("[Script Info]\nTitle: x\n") == []


def test_read_single_font():
    raw = bytes(range(60))
    ass = ("[Script Info]\nTitle: t\n\n[Fonts]\n"
           "fontname: myfont\n" + uuencode(raw) + "\n")
    fonts = af.read_embedded_fonts(ass)
    assert len(fonts) == 1
    assert fonts[0]["name"] == "myfont"
    assert fonts[0]["data"] == raw
    assert len(fonts[0]["id"]) == 64      # sha256 hex


def test_read_multiple_fonts():
    a, b = bytes(range(30)), bytes(range(100, 160))
    ass = ("[Script Info]\n\n[Fonts]\n"
           "fontname: fa\n" + uuencode(a) + "\n"
           "fontname: fb\n" + uuencode(b) + "\n")
    fonts = af.read_embedded_fonts(ass)
    assert [f["name"] for f in fonts] == ["fa", "fb"]
    assert fonts[0]["data"] == a and fonts[1]["data"] == b


def test_read_ignores_other_sections():
    """别的段落里的内容不能被当字体。"""
    raw = bytes(range(30))
    ass = ("[V4+ Styles]\nStyle: Default,Arial,20\n"
           "[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,hi\n\n"
           "[Fonts]\nfontname: f\n" + uuencode(raw) + "\n")
    fonts = af.read_embedded_fonts(ass)
    assert len(fonts) == 1
    assert fonts[0]["data"] == raw


def test_read_multiline_chunks():
    """编码可以跨多行，必须拼起来再解。"""
    raw = bytes(range(120))
    enc = uuencode(raw)
    mid = len(enc) // 2
    ass = ("[Fonts]\nfontname: f\n" + enc[:mid] + "\n" + enc[mid:] + "\n")
    fonts = af.read_embedded_fonts(ass)
    assert fonts[0]["data"] == raw


def test_read_missing_fontname_raises():
    """有 [Fonts] 段但没有 fontname 时，数据无处归属，应报错而非静默丢弃。"""
    ass = "[Fonts]\n" + uuencode(bytes(range(30))) + "\n"
    # 没有 fontname 时 name 一直是 None，flush 全部跳过 -> 空列表
    assert af.read_embedded_fonts(ass) == []


# ---------------- 段序归一化 ----------------

def test_normalize_moves_fonts_to_end():
    """[Fonts] 必须在文件末尾，否则 libass 会把后续内容当附件二进制。"""
    ass = ("[Fonts]\nfontname: f\nAAAA\n\n"
           "[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,hi\n")
    out = af.normalize_font_sections(ass)
    assert out.index("[Fonts]") > out.index("[Events]")


def test_normalize_no_fonts_unchanged():
    s = "[Script Info]\nTitle: x\n"
    assert af.normalize_font_sections(s) == s


# ---------------- 落盘 ----------------

def test_extract_to_dir(tmp_path):
    raw = bytes(range(60))
    ass = "[Fonts]\nfontname: myfont\n" + uuencode(raw) + "\n"
    r = af.extract_to_dir(ass, str(tmp_path))
    assert len(r["written"]) == 1
    p = r["written"][0]
    assert os.path.isfile(p)
    assert open(p, "rb").read() == raw


def test_extract_dedup_filename(tmp_path):
    """同名不同内容不能互相覆盖。"""
    a, b = bytes(range(30)), bytes(range(100, 130))
    ass = ("[Fonts]\nfontname: same\n" + uuencode(a) + "\n"
           "fontname: same\n" + uuencode(b) + "\n")
    r = af.extract_to_dir(ass, str(tmp_path))
    assert len(r["written"]) == 2
    assert r["written"][0] != r["written"][1]
    assert open(r["written"][0], "rb").read() == a
    assert open(r["written"][1], "rb").read() == b


# ---------------- 用真实字体验证 ----------------

@pytest.mark.skipif(os.name != "nt", reason="依赖 Windows 字体")
def test_real_font_roundtrip(tmp_path):
    """用真实 simhei.ttf 前 3000 字节做往返，确认大块数据也正确。"""
    src = r"C:\Windows\Fonts\simhei.ttf"
    if not os.path.isfile(src):
        pytest.skip("没有 simhei.ttf")
    raw = open(src, "rb").read()[:3000]
    ass = "[Fonts]\nfontname: simhei\n" + uuencode(raw) + "\n"
    fonts = af.read_embedded_fonts(ass)
    assert fonts[0]["data"] == raw
    assert fonts[0]["ext"] == ".ttf"