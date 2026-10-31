# -*- coding: utf-8 -*-
"""
SubAI Translator —— 视频合成模块（四期 4.2）
=============================================

能力：
1. 硬字幕烧录（burn-in）：把 SRT 通过 FFmpeg libass 滤镜烧进画面
2. 软字幕封装（soft-sub）：把一条或多条字幕作为独立轨封装进 MKV
3. 画质测量：用 FFmpeg 的 psnr 滤镜给出平均 PSNR（dB）

设计约定：
- 复用 config.ffmpeg（打包后指向 bin/ffmpeg.exe）；纯 subprocess，无额外依赖
- 便于测试：命令构造函数（build_*）与执行函数（burn_hardsub/mux_softsub）分离
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Optional

from src.config import config

_FFMPEG_TIMEOUT = 3600


def _run(args: list[str], timeout: int = _FFMPEG_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


# --------------------------------------------------------------------------- #
# 硬字幕烧录
# --------------------------------------------------------------------------- #

def escape_filter_path(path: str) -> str:
    """转义为 FFmpeg subtitles 滤镜可用的路径。

    Windows 盘符冒号必须转义（C: -> C\\:），反斜杠统一为正斜杠，单引号转义。
    """
    p = os.path.abspath(path).replace("\\", "/")
    p = p.replace("'", "\\'")
    p = p.replace(":", "\\:")
    return p


def build_burn_command(
    video: str, subtitle: str, out_path: str, *,
    crf: int = 18, preset: str = "medium",
    font_name: Optional[str] = None, font_size: Optional[int] = None,
    hwaccel: Optional[str] = None,
    style: "object | None" = None,
) -> list[str]:
    """构造硬字幕烧录命令（不含 ffmpeg 可执行文件本身与全局参数）。

    [2026-10-25] 新增 `style` 参数：完整的 SubtitleStyle（颜色/描边/阴影/位置/
    背景框等）。不传时退回旧的 font_name/font_size 行为，**保证既有调用零改动**。

    样式串由 subtitle_style.build_force_style() 统一生成，
    与「生成 ASS 文件」走同一份代码，避免两条路径观感不一致。
    """
    filt = "subtitles='%s'" % escape_filter_path(subtitle)
    if style is not None:
        try:
            from src.subtitle_style import build_force_style
            filt += ":force_style='%s'" % build_force_style(style)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            # 样式构造失败不能让烧录整体失败：退回无样式（ffmpeg 用 SRT 隐含默认）
            pass
    else:
        style_parts = []
        if font_name:
            style_parts.append("FontName=%s" % font_name)
        if font_size:
            style_parts.append("FontSize=%d" % int(font_size))
        if style_parts:
            filt += ":force_style='%s'" % ",".join(style_parts)

    args: list[str] = []
    if hwaccel:
        args += ["-hwaccel", hwaccel]
    args += [
        "-i", video,
        "-vf", filt,
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-c:a", "copy",
        out_path,
    ]
    return args


def burn_hardsub(
    video: str, subtitle: str, out_path: str, *,
    crf: int = 18, preset: str = "medium",
    font_name: Optional[str] = None, font_size: Optional[int] = None,
    hwaccel: Optional[str] = None, timeout: int = _FFMPEG_TIMEOUT,
    style: "object | None" = None,
) -> str:
    """把字幕硬烧录进画面，返回输出路径；失败抛 RuntimeError。"""
    if not os.path.isfile(video):
        raise FileNotFoundError("视频不存在: %s" % video)
    if not os.path.isfile(subtitle):
        raise FileNotFoundError("字幕不存在: %s" % subtitle)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    cmd = build_burn_command(
        video, subtitle, out_path,
        crf=crf, preset=preset, font_name=font_name, font_size=font_size,
        hwaccel=hwaccel, style=style,
    )
    r = _run(cmd, timeout=timeout)
    if r.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("硬字幕烧录失败: %s" % (r.stderr or "").strip()[:500])
    return out_path


# --------------------------------------------------------------------------- #
# 软字幕封装
# --------------------------------------------------------------------------- #

def build_mux_command(video: str, tracks: list[dict], out_path: str,
                      fonts: Optional[list] = None) -> list[str]:
    """构造软字幕封装命令。

    tracks: [{"path": str, "language": str|None, "title": str|None, "default": bool|None}]
    fonts:  可选，要内嵌的字体文件路径列表（[2026-10-25] 新增）

    [2026-10-25] 字体内嵌：把 TTF/OTF 作为 attachment 塞进 MKV。
    动机：ASS 字幕只记录**字体名**，渲染时靠播放器去系统里找 ——
    自己做好的字幕发给别人，对方没这个字体就掉成默认字体，
    安卓电视/手机播放器字体集小，中文字幕经常掉成方框。
    内嵌后 libass/mpv/VLC 会自动加载，任何设备都能正确渲染。

    只在 MKV 生效（MP4 容器不支持 attachment）。非 .mkv 输出时静默忽略 fonts，
    而不是报错 —— 用户要 mp4 是他自己的选择，不该因此拿不到字幕。
    """
    args: list[str] = ["-i", video]
    for t in tracks:
        args += ["-i", t["path"]]

    args += ["-map", "0"]
    for i in range(len(tracks)):
        args += ["-map", str(i + 1)]

    # 视频/音频直接复制（无损），字幕统一转成 srt
    args += ["-c:v", "copy", "-c:a", "copy", "-c:s", "srt"]

    for i, t in enumerate(tracks):
        if t.get("language"):
            args += ["-metadata:s:s:%d" % i, "language=%s" % t["language"]]
        if t.get("title"):
            args += ["-metadata:s:s:%d" % i, "title=%s" % t["title"]]

    if tracks:
        args += ["-disposition:s:0", "default"]

    # 字体内嵌（仅 MKV）：attach 必须放在输出路径之前
    if fonts and out_path.lower().endswith((".mkv", ".mka")):
        try:
            from src.fonts import build_attach_args
            args += build_attach_args(list(fonts))
        except Exception:  # noqa: BLE001
            # 内嵌失败不能让出片失败：没有内嵌的字幕在本机照样能播
            pass

    args += [out_path]
    return args


def mux_softsub(video: str, tracks: list[dict], out_path: str, *,
                fonts: Optional[list] = None,
                timeout: int = _FFMPEG_TIMEOUT) -> str:
    """把一条或多条字幕封装成软字幕轨，返回输出路径；失败抛 RuntimeError。

    fonts: 可选，要内嵌进 MKV 的字体文件列表（仅 MKV 生效）。
    """
    if not tracks:
        raise ValueError("至少需要一条字幕轨")
    if not os.path.isfile(video):
        raise FileNotFoundError("视频不存在: %s" % video)
    for t in tracks:
        if not os.path.isfile(t["path"]):
            raise FileNotFoundError("字幕不存在: %s" % t["path"])
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    r = _run(build_mux_command(video, tracks, out_path, fonts=fonts), timeout=timeout)
    if r.returncode != 0 or not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("软字幕封装失败: %s" % (r.stderr or "").strip()[:500])
    return out_path


# --------------------------------------------------------------------------- #
# 画质测量
# --------------------------------------------------------------------------- #

def measure_psnr(reference: str, distorted: str, *, timeout: int = 1800) -> Optional[float]:
    """返回参考视频与目标视频的平均 PSNR（dB）；完全相同返回 float('inf')，无法测量返回 None。"""
    if not os.path.isfile(reference) or not os.path.isfile(distorted):
        raise FileNotFoundError("PSNR 输入文件不存在")

    r = subprocess.run(
        [config.ffmpeg, "-hide_banner", "-i", distorted, "-i", reference,
         "-lavfi", "psnr", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )
    m = re.search(r"average:([0-9.]+|inf)", r.stderr or "")
    if not m:
        return None
    return float("inf") if m.group(1) == "inf" else float(m.group(1))
