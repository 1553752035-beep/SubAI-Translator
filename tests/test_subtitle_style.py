# -*- coding: utf-8 -*-
"""字幕样式与 ASS 生成测试（src/subtitle_style.py）。

重点固定四类容易被无声破坏的行为：

1. **颜色语义**：ASS 是 BGR 且 alpha 反转（00=不透明）。搞反了画面就是错的，
   但 ffmpeg/libass 都不会报错 —— 只能靠测试盯住。
2. **force_style 列对齐**：Style 行第一列是 Name，不属于 force_style。
   整串右移一位会让字体名变成 "Default"、字号失效，同样不报错。
3. **零回归**：不传 style 时，烧录命令必须与改动前逐字一致。
4. **ASS 时间精度**：是 2 位百分秒，不是毫秒。
"""
import pytest

from src.subtitle_style import (
    ASS_PLAY_RES_X, ASS_PLAY_RES_Y, SubtitleStyle,
    build_ass_document, build_force_style, build_style_line,
    css_to_ass_color, fmt_ass_time, parse_hex_color, resolve_font_chain,
    sanitize_font_family,
)


# ---------------- 颜色 ----------------

@pytest.mark.parametrize("css,rgb", [
    ("#FFFFFF", (255, 255, 255)),
    ("#000000", (0, 0, 0)),
    ("#FF0000", (255, 0, 0)),
    ("#f00", (255, 0, 0)),
    ("FFD700", (255, 215, 0)),
])
def test_parse_hex_color(css, rgb):
    assert parse_hex_color(css) == rgb


def test_parse_hex_rejects_bare_three_letter_words():
    """`bad` / `abc` 的字符恰好都是合法十六进制，但不能当颜色。

    这是真实踩过的坑：用户把 `#bad` 打成 `bad`，如果按 3 位缩写解析
    会得到 `#bbaadd`（淡紫），完全不是用户想要的黑/白系。
    """
    assert parse_hex_color("bad") is None
    assert parse_hex_color("abc") is None
    assert parse_hex_color("") is None
    assert parse_hex_color("红色") is None


@pytest.mark.parametrize("css,expect", [
    ("#FFFFFF", "&H00FFFFFF"),   # 白：不透明 alpha=00
    ("#FF0000", "&H000000FF"),   # 红：BGR 顺序，红在最后两位
    ("#00FF00", "&H0000FF00"),   # 绿
    ("#0000FF", "&H00FF0000"),   # 蓝：BGR 顺序，蓝在最前
])
def test_css_to_ass_color_is_bgr(css, expect):
    """ASS 颜色是 BGR 顺序 —— 写成 RGB 会让红蓝互换，且不报错。"""
    assert css_to_ass_color(css, 100) == expect


def test_css_to_ass_color_alpha_is_inverted():
    """ASS alpha 反转：00=不透明，FF=全透明。写反了字幕会直接看不见。"""
    assert css_to_ass_color("#FFFFFF", 100) == "&H00FFFFFF"
    assert css_to_ass_color("#FFFFFF", 0) == "&HFFFFFFFF"
    mid = css_to_ass_color("#FFFFFF", 50)
    assert mid.startswith("&H80")   # 50% 不透明 -> alpha≈0x80


def test_css_to_ass_color_falls_back_to_white():
    """非法颜色回落白色，绝不生成非法值让 libass 静默错渲。"""
    assert css_to_ass_color("not-a-color", 100) == "&H00FFFFFF"


# ---------------- 字体 ----------------

def test_font_family_strips_comma():
    """Style 行是逗号分隔定长表，字体名含逗号会让后面所有字段错位。"""
    out = sanitize_font_family("Microsoft YaHei, SimHei")
    assert "," not in out


def test_font_chain_dedup_and_trim():
    assert resolve_font_chain("Arial, Arial , Microsoft YaHei") == "Arial, Microsoft YaHei"
    assert resolve_font_chain("") == "Arial"
    assert resolve_font_chain("  ,  ") == "Arial"


# ---------------- 样式行 ----------------

def test_style_line_field_count():
    """Style 行必须是 23 列，少一列 libass 就会按错位的值渲染。"""
    line = build_style_line(SubtitleStyle())
    payload = line.split(":", 1)[1]
    assert len(payload.split(",")) == 23


def test_style_line_box_mode_uses_back_color_for_outline():
    """BorderStyle=3（背景框）时 libass 用 OutlineColour 画框。

    如果这里仍填描边色，用户选「黑色描边 + 半透明背景框」会得到一个
    不透明的黑框（而不是想要的半透明背景）。这是 SmartSub 明确指出过的坑。
    """
    st = SubtitleStyle(border_style=3, back_color="#000000",
                       outline_color="#FF0000", back_opacity=50)
    cols = build_style_line(st).split(":", 1)[1].split(",")
    outline_col, back_col = cols[5], cols[6]
    assert outline_col == back_col, "背景框模式：框色与阴影色必须同色"
    assert not outline_col.startswith("&H00"), "背景框应带用户设定的不透明度"


def test_style_line_outline_mode_keeps_outline_color():
    """BorderStyle=1 时 OutlineColour 就是描边色，不能被背景色顶掉。"""
    st = SubtitleStyle(border_style=1, outline_color="#FF0000", back_color="#000000")
    cols = build_style_line(st).split(":", 1)[1].split(",")
    assert cols[5] == "&H000000FF"   # 红（BGR）
    assert cols[6] == "&H00000000"   # 黑


def test_style_line_bold_uses_ass_minus_one():
    """ASS 的 Bold/Italic 是「-1 为真，0 为假」，不是布尔 true/false。"""
    cols = build_style_line(SubtitleStyle(bold=True, italic=False)).split(":", 1)[1].split(",")
    assert cols[7] == "-1"
    assert cols[8] == "0"


@pytest.mark.parametrize("numpad,ass", [
    (1, 1), (2, 2), (3, 3),
    (4, 9), (5, 10), (6, 11),
    (7, 5), (8, 6), (9, 7),
])
def test_alignment_numpad_to_ass_legacy(numpad, ass):
    """numpad 风格（7/8/9 上排）→ ASS legacy 编码（9/10/11 中排）。

    映射错了字幕会跑到画面中间或顶部，是最容易被用户一眼发现的 bug。
    """
    cols = build_style_line(SubtitleStyle(alignment=numpad)).split(":", 1)[1].split(",")
    assert cols[18] == str(ass)


# ---------------- force_style ----------------

def test_force_style_skips_name_column():
    """force_style 的第一项必须是 FontName，不能是样式名。

    实测症状：整串右移一位 → ffmpeg 试图用一个叫 "Default" 的字体，
    字号字段被吃掉，最终输出「字体不对且大小没变」，并且全程无报错。
    """
    fs = build_force_style(SubtitleStyle(font_family="Arial", font_size=30))
    assert fs.startswith("FontName=Arial,")
    assert "FontSize=30," in fs
    assert "Default" not in fs


def test_force_style_has_no_style_name():
    """样式名不应出现在 force_style 里（它不是可设置项）。"""
    fs = build_force_style(SubtitleStyle())
    keys = [p.split("=")[0] for p in fs.split(",")]
    assert "Name" not in keys


def test_force_style_color_has_trailing_ampersand():
    """ASS 颜色值在 force_style 里需要结尾的 `&`，否则解析截断。"""
    fs = build_force_style(SubtitleStyle(primary_color="#FFD700"))
    assert "PrimaryColour=&H0000D7FF&" in fs


# ---------------- ASS 时间 ----------------

@pytest.mark.parametrize("sec,expect", [
    (0.0, "0:00:00.00"),
    (1.5, "0:00:01.50"),
    (61.25, "0:01:01.25"),
    (3600.0, "1:00:00.00"),
    (3661.99, "1:01:01.99"),
])
def test_fmt_ass_time(sec, expect):
    """ASS 时间是 2 位**百分秒**，不是毫秒 —— 写成毫秒会慢 10 倍。"""
    assert fmt_ass_time(sec) == expect


def test_fmt_ass_time_negative_clamped():
    assert fmt_ass_time(-5) == "0:00:00.00"


# ---------------- 完整文档 ----------------

def test_ass_document_has_fixed_play_res():
    """固定 384×288 脚本空间：与 ffmpeg 的 SRT 隐式转换一致，保证零回归。"""
    doc = build_ass_document([{"start": 0, "end": 1, "text": "x"}])
    assert "PlayResX: %d" % ASS_PLAY_RES_X in doc
    assert "PlayResY: %d" % ASS_PLAY_RES_Y in doc


def test_ass_document_escapes_newline():
    """正文换行要转成 ASS 的 \\N，否则整行被截断。"""
    doc = build_ass_document([{"start": 0, "end": 1, "text": "第一行\n第二行"}])
    assert "第一行\\N第二行" in doc


def test_ass_document_texts_override():
    doc = build_ass_document([{"start": 0, "end": 1, "text": "原文"}], texts=["译文"])
    assert "译文" in doc and "原文" not in doc


def test_ass_document_skips_bad_rows():
    """坏行跳过，好行保留。"""
    doc = build_ass_document([
        {"start": "坏", "end": 1, "text": "x"},
        {"start": 1, "end": 2, "text": "好的"},
    ])
    assert "好的" in doc
    assert doc.count("Dialogue:") == 1


# ---------------- 零回归 ----------------

def test_style_from_dict_tolerates_garbage():
    """样式来自 JSON/表单，字段缺失或类型错误要回落默认值而不是抛异常。"""
    st = SubtitleStyle.from_dict({"font_size": "not-a-number", "unknown_field": 1})
    assert st.font_size == SubtitleStyle().font_size
    assert st.font_family == SubtitleStyle().font_family


def test_style_from_dict_none():
    assert SubtitleStyle.from_dict(None).font_size == 20


def test_burn_command_unchanged_without_style():
    """不传 style 时烧录命令必须与改动前完全一致（旧调用零改动）。"""
    from src.compose import build_burn_command
    cmd = build_burn_command("v.mp4", "s.srt", "o.mp4", font_name="Arial", font_size=24)
    vf = cmd[cmd.index("-vf") + 1]
    assert vf.endswith("force_style='FontName=Arial,FontSize=24'")


def test_burn_command_with_style():
    from src.compose import build_burn_command
    st = SubtitleStyle(font_family="Microsoft YaHei", font_size=28, primary_color="#FFD700")
    cmd = build_burn_command("v.mp4", "s.srt", "o.mp4", style=st)
    vf = cmd[cmd.index("-vf") + 1]
    assert "FontName=Microsoft YaHei" in vf
    assert "&H0000D7FF" in vf
