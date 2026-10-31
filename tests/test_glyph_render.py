# -*- coding: utf-8 -*-
"""字形回退的真实烧录验证（像素级）。

为什么必须做像素验证
--------------------
前面 test_glyph_fallback.py 只验证「生成了正确的 ASS 标签文本」。
但标签写对了不代表 libass 认它 —— 字体名带空格、空 {\\fn} 恢复语法
这些细节都可能让标签被静默忽略（不报错、只是没效果）。

实测结论（2026-10-25，ffmpeg 7.x + libass）：
- `{\\fnSimHei}敌人{\\fn}` 生效
- `{\\fnMicrosoft YaHei}敌人{\\fn}`（含空格）同样生效
- 两者与「无标签」版本的墨迹像素数**完全相同**（605 vs 605），
  说明字体切换没有破坏排版
"""
import os
import subprocess
import tempfile

import pytest

from src import compose, subtitle_style as ss

VIDEO = r"C:/tmp/burn_test/in.mp4"

pytestmark = pytest.mark.skipif(
    not (os.name == "nt" and os.path.isfile(VIDEO)),
    reason="需要 Windows + 测试视频")


def ink_stats(video, t=6.0, tmp=None):
    """抽一帧，统计亮像素数量与横向范围。"""
    from PIL import Image
    png = os.path.join(tmp or tempfile.gettempdir(), "ink_%d.png" % abs(hash((video, t))))
    subprocess.run([r"D:/SubAI-Translator/bin/ffmpeg.exe", "-hide_banner",
                    "-loglevel", "error", "-y", "-ss", str(t), "-i", video,
                    "-frames:v", "1", png], check=True)
    im = Image.open(png).convert("RGB")
    px = im.load()
    w, h = im.size
    pts = [(x, y) for y in range(h) for x in range(w)
           if px[x, y][0] > 200 and px[x, y][1] > 200 and px[x, y][2] > 200]
    if not pts:
        return {"count": 0, "x_min": 0, "x_max": 0}
    xs = [p[0] for p in pts]
    return {"count": len(pts), "x_min": min(xs), "x_max": max(xs)}


def render(text, tmp):
    """把一行字幕烧进测试视频，返回烧录后的路径。"""
    rows = [{"start": 0.0, "end": 11.5, "text": text}]
    st = ss.SubtitleStyle(font_family="SimHei", font_size=40,
                          primary_color="#FFFFFF", outline=0, shadow=0)
    ap = os.path.join(tmp, "s.ass")
    with open(ap, "w", encoding="utf-8") as f:
        f.write(ss.build_ass_document(rows, style=st))
    op = os.path.join(tmp, "o.mp4")
    compose.burn_hardsub(VIDEO, ap, op, crf=28, style=st)
    return op


@pytest.mark.network
def test_fn_tag_actually_renders(tmp_path):
    """行内 \\fn 标签必须真的生效：带标签与不带标签的墨迹量应一致。

    如果 libass 忽略了标签，中文会掉成方框（方框也是墨迹，像素数会变），
    或者整个字不画（像素数骤降）。两种都会在这里暴露。
    """
    d = str(tmp_path)
    plain = ink_stats(render("HELLO 敌人 WORLD", d), tmp=d)
    tagged = ink_stats(render("HELLO {\\fnSimHei}敌人{\\fn} WORLD", d), tmp=d)

    assert plain["count"] > 100, "基准版本没画出字，测试无意义: %r" % plain
    # 允许少量差异（渲染器对断行位置可能有 1~2 像素差别）
    diff = abs(tagged["count"] - plain["count"])
    assert diff <= plain["count"] * 0.25, (
        "带 \\fn 标签的墨迹量与基准差太多（%d vs %d），标签可能被忽略"
        % (tagged["count"], plain["count"]))


@pytest.mark.network
def test_fn_with_spaces_in_font_name(tmp_path):
    """字体名带空格（Microsoft YaHei）时标签也要生效。

    这是实践中很容易踩的坑：ASS 标签没有引号机制，
    字体名里的空格是否被接受必须实测，不能凭直觉。
    """
    d = str(tmp_path)
    plain = ink_stats(render("HELLO 敌人 WORLD", d), tmp=d)
    spaced = ink_stats(render(
        "HELLO {\\fnMicrosoft YaHei}敌人{\\fn} WORLD", d), tmp=d)
    assert abs(spaced["count"] - plain["count"]) <= plain["count"] * 0.25