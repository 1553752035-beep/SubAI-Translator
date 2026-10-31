# -*- coding: utf-8 -*-
"""字体字形覆盖解析（逐字回退）。

要解决的问题
------------
ASS 字幕只记录**字体名**。如果指定的字体缺少某些字（典型案例：
标题用 Arial，正文里混了"敌人"两个字），libass 会用默认字体画——
而默认字体常常也没有该字，结果是**方框（tofu）**。
用户看到的是「字幕里冒出几个方块」，却不知道原因。

解法：渲染前先算出「这段文字里，主字体缺哪些字」，
再把缺的字切成独立的文本 run，各自指定一个**确定覆盖该字**的字体。

为什么不用 fontTools
-------------------
我们只需要一个信息：**某码位在这份字体里有没有字形**。
不需要字形轮廓、不需要 hinting、不需要变体。
纯标准库解析 sfnt 表目录 + cmap（format 4 / 12）即可，约 100 行。
`requirements.txt` 里没有 fontTools，引入它等于给打包加一个
隐式依赖（PyInstaller 对它的数据文件处理也常有坑），不划算。

已用真实字体验证（2026-10-25）
------------------------------
| 字体 | cmap 格式 | 常用汉字覆盖 | Arial 有中文? |
|---|---|---|---|
| msyh.ttc（微软雅黑） | 12 | 20902/20902 | 否 |
| simhei.ttf（黑体） | 4 | 20902/20902 | 否 |
| simsun.ttc（宋体） | 4 | 20902/20902 | 否 |
| arial.ttf | 4 | 0 | 是（0 个） |

踩过的坑（写在这里免得重犯）：
TTC（字体集合）里每个子字体的表目录中，「表偏移」字段是**相对文件开头**的
绝对偏移，**不是**相对子字体起始位置。按子字体加 base 会取到错误的 cmap，
症状是「微软雅黑缺『文』字」这种明显不合理的判定。
"""
from __future__ import annotations

import os
import struct
from typing import Optional

# 不可见字符：不绘制任何东西，换字体没有意义，留在原字体上。
# 范围与 SmartSub 一致（软连字符、零宽、方向控制符、变体选择符等）。
INVISIBLE_RANGES = (
    (0x00AD, 0x00AD), (0x200B, 0x200F), (0x2028, 0x202E),
    (0x2060, 0x206F), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
    (0xE0100, 0xE01EF),
)


def is_invisible(code: int) -> bool:
    """该码位是否不绘制任何内容（换字体没意义）。"""
    for lo, hi in INVISIBLE_RANGES:
        if lo <= code <= hi:
            return True
    return False


class FontFace:
    """一份字体的字形覆盖查询。

    构造时只读表目录，cmap 数据按需在内存里查（整个字体已读入）。
    """

    __slots__ = ("path", "face_index", "format", "_data", "_lookup", "_cache")

    def __init__(self, path: str, face_index: int = 0):
        self.path = path
        self.face_index = face_index
        self.format = None
        self._lookup = None
        self._cache: dict = {}
        with open(path, "rb") as f:
            self._data = f.read()
        self._parse(face_index)

    def _parse(self, face_index: int) -> None:
        data = self._data
        if len(data) < 12:
            raise ValueError("文件太小，不是字体: %s" % self.path)

        base = 0
        if data[:4] == b"ttcf":
            num = struct.unpack(">I", data[8:12])[0]
            if num == 0:
                raise ValueError("TTC 子字体数为 0: %s" % self.path)
            if face_index >= num:
                face_index = 0
            self.face_index = face_index
            offs = struct.unpack(">%dI" % num, data[12:12 + num * 4])
            base = offs[face_index]

        num_tables = struct.unpack(">H", data[base + 4:base + 6])[0]
        cmap_off = None
        for i in range(num_tables):
            p = base + 12 + i * 16
            if p + 12 > len(data):
                break
            if data[p:p + 4] == b"cmap":
                # 关键：文件内的表偏移是绝对偏移（见模块开头「踩过的坑」）
                cmap_off = struct.unpack(">I", data[p + 8:p + 12])[0]
                break
        if cmap_off is None or cmap_off + 4 > len(data):
            raise ValueError("字体没有 cmap 表: %s" % self.path)

        n_sub = struct.unpack(">H", data[cmap_off + 2:cmap_off + 4])[0]
        best = None
        for i in range(n_sub):
            p = cmap_off + 4 + i * 8
            if p + 8 > len(data):
                break
            _pid, _eid, off = struct.unpack(">HHI", data[p:p + 8])
            sub = cmap_off + off
            if sub + 2 > len(data):
                continue
            fmt = struct.unpack(">H", data[sub:sub + 2])[0]
            if fmt == 12:
                best = (12, sub)
                break            # format 12 支持全部 Unicode，优先
            if fmt == 4 and best is None:
                best = (4, sub)
        if best is None:
            raise ValueError("字体没有 format 4/12 的 cmap: %s" % self.path)

        self.format, sub = best
        self._lookup = self._make_lookup(self.format, sub)

    def _make_lookup(self, fmt: int, sub: int):
        data = self._data
        if fmt == 4:
            seg_x2 = struct.unpack(">H", data[sub + 6:sub + 8])[0]
            seg = seg_x2 // 2
            end_p = sub + 14
            start_p = end_p + seg_x2 + 2
            delta_p = start_p + seg_x2
            range_p = delta_p + seg_x2
            ends = struct.unpack(">%dH" % seg, data[end_p:end_p + seg_x2])
            starts = struct.unpack(">%dH" % seg, data[start_p:start_p + seg_x2])
            deltas = struct.unpack(">%dh" % seg, data[delta_p:delta_p + seg_x2])
            ranges = struct.unpack(">%dH" % seg, data[range_p:range_p + seg_x2])

            def has_format4(code: int) -> bool:
                if code > 0xFFFF:
                    return False
                for i in range(seg):
                    if starts[i] <= code <= ends[i]:
                        if ranges[i] == 0:
                            return ((code + deltas[i]) & 0xFFFF) != 0
                        glyph = (code + deltas[i]) & 0xFFFF
                        if glyph == 0:
                            return False
                        gp = range_p + i * 2 + ranges[i] + glyph * 2
                        if gp + 2 > len(data):
                            return False
                        return struct.unpack(">H", data[gp:gp + 2])[0] != 0
                return False
            return has_format4

        n_groups = struct.unpack(">I", data[sub + 12:sub + 16])[0]
        groups = []
        for i in range(n_groups):
            p = sub + 16 + i * 12
            if p + 12 > len(data):
                break
            s, e = struct.unpack(">II", data[p:p + 8])
            groups.append((s, e))

        def has_format12(code: int) -> bool:
            lo, hi = 0, len(groups) - 1
            while lo <= hi:              # groups 已按码位升序，二分更快
                mid = (lo + hi) // 2
                s, e = groups[mid]
                if code < s:
                    hi = mid - 1
                elif code > e:
                    lo = mid + 1
                else:
                    return True
            return False
        return has_format12

    def has_glyph(self, code: int) -> bool:
        """该码位在这份字体里有没有字形。结果缓存（同一行文字会重复问）。"""
        cached = self._cache.get(code)
        if cached is not None:
            return cached
        ok = bool(self._lookup(code))
        self._cache[code] = ok
        return ok

    def missing_codepoints(self, text: str) -> list:
        """text 里这份字体缺哪些码位（去重、保持出现顺序、跳过不可见字符）。"""
        out = []
        seen = set()
        for ch in text:
            code = ord(ch)
            if code in seen or is_invisible(code):
                continue
            seen.add(code)
            if not self.has_glyph(code):
                out.append(code)
        return out


def load_face(path: str, face_index: int = 0) -> Optional[FontFace]:
    """安全加载：失败返回 None（字体坏了不该让出片失败）。"""
    try:
        return FontFace(path, face_index)
    except Exception:  # noqa: BLE001
        return None


def split_runs(text: str, primary: FontFace,
               fallbacks: Optional[list] = None) -> list:
    """把 text 切成 [{text, font}] run 列表。

    primary：主字体（Style 里写的那个）。
    fallbacks：候选回退字体列表，按顺序找第一个覆盖该字的。

    返回值里 font 为 None 表示「所有字体都没有这个字」，
    此时保持原样（由 libass 画方框），由调用方决定是否告警 ——
    这与「静默把字丢掉」有本质区别。
    """
    fallbacks = [f for f in (fallbacks or []) if f is not None]
    runs: list = []          # [{text, font}]

    def push(ch: str, font: Optional[FontFace]) -> None:
        if runs and runs[-1]["font"] is font:
            runs[-1]["text"] += ch
        else:
            runs.append({"text": ch, "font": font})

    for ch in text:
        code = ord(ch)
        # 不可见字符留在主字体上：换字体画不出任何东西，只会白白增加 run
        if is_invisible(code) or primary.has_glyph(code):
            push(ch, primary)
            continue
        picked = None
        for fb in fallbacks:
            if fb.has_glyph(code):
                picked = fb
                break
        push(ch, picked)         # None = 谁都没有，保持原样
    return runs


def summarize_runs(runs: list) -> dict:
    """统计切分结果，供 UI 提示「这些字所有字体都没有」。"""
    missing = {}
    runs_out = []
    for r in runs:
        font = r["font"]
        name = os.path.basename(getattr(font, "path", "") or "")
        runs_out.append({"text": r["text"], "font": name})
        if font is None:
            for ch in r["text"]:
                if not is_invisible(ord(ch)):
                    missing[ch] = missing.get(ch, 0) + 1
    return {
        "runs": runs_out,
        "run_count": len(runs_out),
        "missing_chars": list(missing),
        "needs_fallback": any(r["font"] is not None and r["text"]
                              for r in runs) and len(runs_out) > 0,
    }