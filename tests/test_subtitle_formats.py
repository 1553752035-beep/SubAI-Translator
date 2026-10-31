# -*- coding: utf-8 -*-
"""多格式字幕编解码测试（src/subtitle_formats.py）。

背景：本项目此前只能导入 SRT、只能导出 srt/vtt/ass/json。
同类项目 SmartSub 支持 srt/vtt/ass/lrc/txt 五种、导入支持前四种。
本模块补齐差距，测试重点固定住三件事：

1. **往返精度**：srt/vtt/ass 的时间必须无损往返（这是能直接进翻译流程的前提）
2. **格式固有局限**：lrc 不带结束时间、txt 没有时间轴 —— 这不是 bug，测的是「行为符合格式定义」
3. **容错**：真实字幕文件常有编码/标签/改名瑕疵，坏一条不能拖垮整个文件
"""
import pytest

from src import subtitle_formats as sf


def R(s, e, t="文本"):
    return {"start": s, "end": e, "text": t}


ROWS = [
    R(1.5, 4.0, "第一句"),
    R(5.0, 8.25, "第二句"),
    R(3600.75, 3602.5, "一小时后的句子"),   # 跨小时，验证时间格式
]


# ---------------- 往返精度（有结束时间的三种格式） ----------------

@pytest.mark.parametrize("fmt", ["srt", "vtt", "ass"])
def test_roundtrip_lossless(fmt):
    """srt/vtt/ass 必须时间无损往返 —— 这三格式带完整起止时间。"""
    back = sf.parse(sf.serialize(ROWS, fmt), fmt)
    assert len(back) == len(ROWS)
    for a, b in zip(ROWS, back):
        assert b["start"] == pytest.approx(a["start"], abs=0.02), fmt
        assert b["end"] == pytest.approx(a["end"], abs=0.02), fmt
        assert b["text"] == a["text"], fmt


def test_roundtrip_cross_hour():
    """跨小时时间戳不能算错（分组偏移写错时最容易在这里暴露）。"""
    back = sf.parse(sf.serialize([R(3600.75, 3602.5, "x")], "srt"), "srt")
    assert back[0]["start"] == pytest.approx(3600.75, abs=0.02)
    assert back[0]["end"] == pytest.approx(3602.5, abs=0.02)


# ---------------- 格式固有局限 ----------------

def test_lrc_has_no_end_time_by_design():
    """LRC 格式本身只有起始时间。

    实现约定：结束时间取下一行起点 - 0.01，末行 +4 秒。
    这是「符合格式定义的行为」，不是精度缺陷 —— 断言要写清这一点，
    避免以后有人把它当 bug"修"成假的精确。
    """
    back = sf.parse(sf.serialize([R(1.0, 9.0, "a"), R(5.0, 9.0, "b")], "lrc"), "lrc")
    assert back[0]["start"] == pytest.approx(1.0, abs=0.02)
    assert back[0]["end"] == pytest.approx(4.99, abs=0.02)   # 下一行起点 - 0.01
    assert back[1]["start"] == pytest.approx(5.0, abs=0.02)
    assert back[1]["end"] == pytest.approx(9.0, abs=0.02)    # 末行 +4 秒


def test_lrc_multi_timestamp_line_expands():
    """LRC 合规写法：一行多个时间标签要展开成多条。"""
    content = "[00:01.00][00:31.00]副歌\n"
    back = sf.parse(content, "lrc")
    assert len(back) == 2
    assert back[0]["start"] == pytest.approx(1.0, abs=0.02)
    assert back[1]["start"] == pytest.approx(31.0, abs=0.02)
    assert all(b["text"] == "副歌" for b in back)


def test_txt_export_is_plain_text():
    """txt 导出只保留正文、不带时间轴。"""
    out = sf.serialize([R(1.0, 2.0, "第一句"), R(3.0, 4.0, "第二句")], "txt")
    assert out.strip().split("\n") == ["第一句", "第二句"]
    assert "-->" not in out


# ---------------- 导入容错 ----------------

def test_parse_srt_tolerates_blank_and_bom():
    """BOM、多余空行、缺序号 都要能读。"""
    content = "\ufeff\n1\n00:00:01,000 --> 00:00:02,000\n你好\n\n\n\n00:00:03,000 --> 00:00:04,000\n再见\n"
    back = sf.parse_srt(content)
    assert [b["text"] for b in back] == ["你好", "再见"]


def test_parse_vtt_strips_inline_tags_and_header():
    """VTT 的 WEBVTT 头、NOTE 块、<v 名字>/<c> 标签都要清掉。"""
    content = (
        "WEBVTT\n\n"
        "NOTE 这是注释\n应该被忽略\n\n"
        "00:00:01.000 --> 00:00:02.000 align:start\n"
        "<v 张三>你好</v>\n\n"
        "00:00:03.000 --> 00:00:04.000\n<c.yellow>再见</c>\n"
    )
    back = sf.parse_vtt(content)
    assert [b["text"] for b in back] == ["你好", "再见"]


def test_parse_ass_reads_format_line_column_order():
    """ASS 必须按 Format 行的实际列序取 Start/End/Text，不能硬编码下标。

    这里刻意把 Text 放在最后一列、并在前面插入 Marked 列，
    硬编码 parts[9] 的实现会取到错误内容。
    """
    content = (
        "[Script Info]\nTitle: t\n\n"
        "[V4+ Styles]\nFormat: Name\nStyle: Default\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Marked, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,1,你好\n"
    )
    back = sf.parse_ass(content)
    assert len(back) == 1
    assert back[0]["text"] == "你好"
    assert back[0]["start"] == pytest.approx(1.0, abs=0.02)
    assert back[0]["end"] == pytest.approx(2.5, abs=0.02)


def test_parse_ass_strips_override_tags():
    """ASS 的 {\\pos()} 等覆盖标签要去掉，\\N 要还原成换行。"""
    content = (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\\pos(1,2)}第一行\\N第二行\n"
    )
    back = sf.parse_ass(content)
    assert back[0]["text"] == "第一行\n第二行"


def test_parse_skips_malformed_block():
    """坏条目跳过，好条目保留 —— 不能因为一条脏数据丢掉整个文件。"""
    content = "1\n00:00:01,000 --> 00:00:02,000\n好的\n\n2\n这不是时间轴\n坏的\n\n"
    back = sf.parse_srt(content)
    assert [b["text"] for b in back] == ["好的"]


# ---------------- 格式识别 ----------------

def test_detect_by_extension():
    assert sf.detect_format_by_extension("a.srt") == "srt"
    assert sf.detect_format_by_extension("a.SSA") == "ass"
    assert sf.detect_format_by_extension("a.lrc") == "lrc"
    assert sf.detect_format_by_extension("a.unknown") is None


def test_detect_by_content_when_extension_lies():
    """用户把 .ass 改名成 .txt 很常见，内容识别要能纠正。"""
    ass = "[Script Info]\nTitle: x\n"
    assert sf.detect_format("a.txt", ass) == "ass"
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nhi\n"
    assert sf.detect_format("a.txt", vtt) == "vtt"
    lrc = "[00:01.00]歌词\n[00:05.00]第二句\n"
    assert sf.detect_format("a.txt", lrc) == "lrc"


def test_extension_for_export():
    assert sf.extension_for("ass") == ".ass"
    assert sf.extension_for("unknown") == ".srt"


# ---------------- texts 覆盖（翻译流程边译边写） ----------------

def test_serialize_with_texts_override():
    """传入 texts 时必须用译文而非原 text（翻译流程依赖这个语义）。"""
    out = sf.serialize([R(1.0, 2.0, "原文")], "srt", texts=["译文"])
    assert "译文" in out
    assert "原文" not in out
