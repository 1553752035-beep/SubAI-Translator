# -*- coding: utf-8 -*-
"""字幕字体内嵌：把字体文件打进 MKV，保证播放端不会缺字体。

为什么需要
----------
ASS 字幕只记录**字体名**，渲染时靠播放器去系统里找。于是：
- 用户在自己机器上看着正常，发给别人就变成默认字体（对方没装）
- 安卓电视 / 手机播放器常见的字体集很小，中文字幕经常掉成方框
- 术语里用了特殊字体（如手写体标题），换机器必然丢

字体内嵌把 TTF/OTF 作为 **attachment** 轨塞进 MKV，
libass / mpv / VLC 会自动加载，任何设备都能正确渲染。
这是 MKV 容器特有的能力，MP4 不支持 —— 所以只在 MKV 输出时启用。

实测（ffmpeg 7.x + matroska muxer）
-----------------------------------
    ffmpeg -i in.mp4 -attach simhei.ttf \
        -metadata:s:t mimetype=font/ttf \
        -metadata:s:t filename=simhei.ttf \
        -map 0 -c copy out.mkv
检查输出能看到 `Stream #0:2: Attachment` 且 `mimetype: font/ttf`。

设计要点
--------
1. **mimetype 必须显式写**。不写的话 libass 认不出这是字体，
   内嵌等于白嵌（文件变大了，效果一点没有）。
2. **filename 必须写**，且要与 ASS 里 `Style: ...,字体名,...` 一致，
   否则 libass 匹配不上这份字体。
3. **字体缺失不能中断出片**。找不到字体就跳过内嵌并记日志 ——
   没有内嵌的字幕在**本机**照样能播，只是换个环境可能掉字体，
   这比整个任务失败好得多。
"""
from __future__ import annotations

import os
import shutil
from typing import Optional

# 常见字体名 -> 系统字体文件候选（Windows）
# 只做「能对上就用」的映射，不追求覆盖全家桶：
# 找不到就让用户自己指定路径，比维护一张永远不全的表更实在。
_WIN_FONT_CANDIDATES = {
    "microsoft yahei": ["msyh.ttc", "msyhbd.ttc"],
    "微软雅黑": ["msyh.ttc", "msyhbd.ttc"],
    "simhei": ["simhei.ttf"],
    "黑体": ["simhei.ttf"],
    "simsun": ["simsun.ttc"],
    "宋体": ["simsun.ttc"],
    "kaiti": ["simkai.ttf"],
    "楷体": ["simkai.ttf"],
    "fangsong": ["simfang.ttf"],
    "仿宋": ["simfang.ttf"],
    "arial": ["arial.ttf"],
    "times new roman": ["times.ttf"],
}

_FONT_EXTS = (".ttf", ".otf", ".ttc")


def font_dirs() -> list:
    """系统字体目录（按优先级）。"""
    out = []
    if os.name == "nt":
        win = os.environ.get("WINDIR") or r"C:\Windows"
        out.append(os.path.join(win, "Fonts"))
        # 用户自己装的字体（不装到系统也能用）
        local = os.environ.get("LOCALAPPDATA") or ""
        if local:
            out.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    else:
        out += ["/usr/share/fonts", "/usr/local/share/fonts",
                os.path.expanduser("~/.fonts")]
    return [d for d in out if os.path.isdir(d)]


def resolve_font_file(font_family: str,
                      search_dirs: Optional[list] = None) -> Optional[str]:
    """按字体族名找系统里的字体文件。找不到返回 None。

    family 可以是候选链（"Microsoft YaHei, SimHei"），取第一个能找到的 ——
    与 ASS 里 libass 的字体回退顺序保持一致。
    """
    dirs = search_dirs if search_dirs is not None else font_dirs()
    if not dirs:
        return None

    names = [n.strip().lower() for n in (font_family or "").split(",") if n.strip()]
    if not names:
        return None

    for name in names:
        # 1) 查表：字体族名 -> 已知文件名
        for fname in _WIN_FONT_CANDIDATES.get(name, []):
            for d in dirs:
                p = os.path.join(d, fname)
                if os.path.isfile(p):
                    return p
        # 2) 直接按族名找同名文件（"Arial" -> arial.ttf）
        for d in dirs:
            try:
                entries = os.listdir(d)
            except OSError:
                continue
            want = name.replace(" ", "")
            for e in entries:
                if not e.lower().endswith(_FONT_EXTS):
                    continue
                stem = os.path.splitext(e)[0].lower().replace(" ", "")
                if stem == want:
                    return os.path.join(d, e)
    return None


def mimetype_for(path: str) -> str:
    """按扩展名给 attachment 定 mimetype。

    这个字段决定 libass 认不认这份字体，写错等于白嵌。
    """
    ext = os.path.splitext(path or "")[1].lower()
    if ext == ".otf":
        return "font/otf"
    if ext == ".ttc":
        return "font/collection"
    return "font/ttf"


def build_attach_args(font_paths: list) -> list:
    """构造 ffmpeg 的 attach 参数片段（纯函数，可单测）。

    每份字体要三条：-attach、-metadata:s:t mimetype、-metadata:s:t filename。
    t 是通用的「附件流」选择器，ffmpeg 会按顺序对上刚才 attach 的那份。
    """
    args: list = []
    seen = set()
    for p in font_paths or []:
        if not p or not os.path.isfile(p):
            continue
        real = os.path.abspath(p)
        if real in seen:          # 同一份字体只嵌一次
            continue
        seen.add(real)
        args += ["-attach", real]
        args += ["-metadata:s:t", "mimetype=%s" % mimetype_for(real)]
        # filename 用原文件名，libass 会按名字匹配字体族
        args += ["-metadata:s:t", "filename=%s" % os.path.basename(real)]
    return args


def collect_fonts(font_families: list,
                  search_dirs: Optional[list] = None) -> dict:
    """按字体族名列表找出对应的字体文件。

    返回 {"resolved": {family: path}, "missing": [family, ...]}。
    缺失的族**不报错**，由调用方决定是否提示 —— 见模块开头「字体缺失不能中断出片」。
    """
    resolved: dict = {}
    missing: list = []
    for fam in font_families or []:
        if not fam or fam in resolved or fam in missing:
            continue
        p = resolve_font_file(fam, search_dirs)
        if p:
            resolved[fam] = p
        else:
            missing.append(fam)
    return {"resolved": resolved, "missing": missing}


def copy_font_to_dir(font_path: str, dest_dir: str) -> str:
    """把字体复制到目标目录（用于打包分发时收集要内嵌的字体）。"""
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(font_path))
    if os.path.abspath(font_path) != os.path.abspath(dest):
        shutil.copy2(font_path, dest)
    return dest