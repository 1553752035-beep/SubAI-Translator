# -*- coding: utf-8 -*-
"""字体内嵌测试（src/fonts.py）。

为什么这条重要却容易被漏
-------------------------
字体内嵌是「用户自己看不出问题」的功能：在他机器上一切正常，
发给别人或换到电视上才发现字幕掉成方框/默认字体。
所以必须靠测试固定住两个最容易写错的点：

1. **mimetype 不写 = 白嵌**。文件变大了，libass 却认不出这是字体。
2. **filename 必须写**，libass 靠它匹配字体族名。
3. **MP4 不支持 attachment**，只能 MKV。
"""
import os

import pytest

from src import fonts
from src.compose import build_mux_command


# ---------------- 字体解析 ----------------

def test_font_dirs_nonempty():
    """系统字体目录必须能找到至少一个，否则内嵌功能等于关闭。"""
    if os.name != "nt":
        pytest.skip("仅在 Windows 上断言字体目录")
    assert fonts.font_dirs()
    assert any(os.path.isdir(d) for d in fonts.font_dirs())


def test_resolve_known_windows_fonts():
    if os.name != "nt":
        pytest.skip("依赖 Windows 字体")
    for fam in ("SimHei", "Arial"):
        p = fonts.resolve_font_file(fam)
        assert p and os.path.isfile(p), "应能找到 %s" % fam


def test_resolve_unknown_returns_none():
    """找不到字体必须返回 None，不能瞎给一个不存在的路径。"""
    assert fonts.resolve_font_file("完全不存在的字体XYZ") is None


def test_resolve_accepts_font_chain():
    """候选链取第一个能找到的，与 ASS 里 libass 的回退顺序一致。"""
    if os.name != "nt":
        pytest.skip("依赖 Windows 字体")
    p = fonts.resolve_font_file("不存在的, SimHei")
    assert p and p.lower().endswith((".ttf", ".ttc"))


def test_resolve_with_explicit_search_dir(tmp_path):
    """能指定搜索目录（打包时把字体放在程序目录里）。"""
    fake = tmp_path / "MyFont.ttf"
    fake.write_bytes(b"FAKE")
    p = fonts.resolve_font_file("MyFont", search_dirs=[str(tmp_path)])
    assert p == str(fake)


# ---------------- mimetype ----------------

@pytest.mark.parametrize("name,expect", [
    ("a.ttf", "font/ttf"),
    ("a.TTF", "font/ttf"),
    ("a.otf", "font/otf"),
    ("a.ttc", "font/collection"),
])
def test_mimetype_for(name, expect):
    """mimetype 写错 libass 就不认这份字体，等于白嵌。"""
    assert fonts.mimetype_for(name) == expect


# ---------------- attach 参数 ----------------

def test_build_attach_args_has_three_parts(tmp_path):
    f = tmp_path / "t.ttf"
    f.write_bytes(b"x")
    args = fonts.build_attach_args([str(f)])
    assert args[0] == "-attach"
    assert "mimetype=font/ttf" in args
    assert "filename=t.ttf" in args


def test_build_attach_args_dedup(tmp_path):
    """同一份字体只嵌一次（重复 attach 会让文件白白变大）。"""
    f = tmp_path / "t.ttf"
    f.write_bytes(b"x")
    args = fonts.build_attach_args([str(f), str(f)])
    assert args.count("-attach") == 1


def test_build_attach_args_skips_missing(tmp_path):
    """不存在的路径跳过，不能把无效参数塞给 ffmpeg。"""
    assert fonts.build_attach_args([str(tmp_path / "nope.ttf")]) == []
    assert fonts.build_attach_args([]) == []
    assert fonts.build_attach_args(None) == []


# ---------------- 与封装命令的配合 ----------------

def test_mux_command_includes_attach_for_mkv(tmp_path):
    f = tmp_path / "t.ttf"
    f.write_bytes(b"x")
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nx\n", encoding="utf-8")
    cmd = build_mux_command("v.mp4", [{"path": str(srt)}], str(tmp_path / "o.mkv"),
                            fonts=[str(f)])
    assert "-attach" in cmd
    assert str(f) in cmd
    # attach 必须在输出路径之前
    assert cmd.index("-attach") < cmd.index(str(tmp_path / "o.mkv"))


def test_mux_command_ignores_fonts_for_mp4(tmp_path):
    """MP4 容器不支持 attachment，必须静默忽略而不是报错。"""
    f = tmp_path / "t.ttf"
    f.write_bytes(b"x")
    srt = tmp_path / "s.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nx\n", encoding="utf-8")
    cmd = build_mux_command("v.mp4", [{"path": str(srt)}], str(tmp_path / "o.mp4"),
                            fonts=[str(f)])
    assert "-attach" not in cmd


def test_mux_command_without_fonts_unchanged(tmp_path):
    """不传 fonts 时命令与改动前一致（旧调用零改动）。"""
    srt = tmp_path / "s.srt"
    srt.write_text("x", encoding="utf-8")
    cmd = build_mux_command("v.mp4", [{"path": str(srt)}], str(tmp_path / "o.mkv"))
    assert "-attach" not in cmd


# ---------------- 收集 ----------------

def test_collect_fonts_reports_missing():
    r = fonts.collect_fonts(["不存在的字体ABC"])
    assert r["missing"] == ["不存在的字体ABC"]
    assert r["resolved"] == {}


def test_collect_fonts_dedup():
    if os.name != "nt":
        pytest.skip("依赖 Windows 字体")
    r = fonts.collect_fonts(["SimHei", "SimHei"])
    assert list(r["resolved"]) == ["SimHei"]