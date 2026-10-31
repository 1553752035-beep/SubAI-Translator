# -*- coding: utf-8 -*-
"""字幕多格式编解码（纯函数，零第三方依赖）。

支持格式
--------
导入：srt / vtt / ass / ssa / lrc
导出：srt / vtt / ass / lrc / txt

设计要点
--------
1. **内部统一用秒（float）表示时间**，避免各格式精度差异累积误差。
   对外结构固定为 `[{"start": float, "end": float, "text": str}]`，
   与 `pipeline.asr_segments` 的产出同构，因此导入的字幕可直接进翻译/出片流程。
2. **纯函数**：不读盘、不写盘、不打印。读写由调用方负责，便于单测。
3. **容错优先**：任何一条无法解析就跳过该条，不整体失败——
   用户从各种来源拿到的字幕文件常有编码/格式瑕疵，因为一条坏数据丢掉整个文件更糟。

与 SmartSub 的对应关系
--------------------
同类项目支持 srt/vtt/ass/lrc/txt 五种，其中导入支持前四种（txt 无时间轴不可导入）。
本项目此前只有 SRT 导入（`_parse_srt`）与 srt/vtt/ass/json 导出，
本模块补齐 lrc/txt 导出与 vtt/ass/lrc 导入。
"""
from __future__ import annotations

import os
import re
from typing import Optional

SUPPORTED_FORMATS = ("srt", "vtt", "ass", "lrc", "txt")
IMPORTABLE_FORMATS = ("srt", "vtt", "ass", "lrc")

_EXT_TO_FORMAT = {
    ".srt": "srt", ".vtt": "vtt", ".ass": "ass", ".ssa": "ass",
    ".lrc": "lrc", ".txt": "txt",
}
_FORMAT_TO_EXT = {"srt": ".srt", "vtt": ".vtt", "ass": ".ass", "lrc": ".lrc", "txt": ".txt"}

# 时间戳：可选小时、必需分秒、可选小数（逗号或点均可）
_TS = r"(?:(\d{1,3}):)?(\d{1,2}):(\d{2})(?:[,.](\d{1,6}))?"
_TIMING_RE = re.compile(_TS + r"\s*-->\s*" + _TS)
_LRC_RE = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_ASS_TIME_RE = re.compile(r"(\d+):(\d{2}):(\d{2})[.:](\d{1,3})")


def detect_format_by_extension(path: str) -> Optional[str]:
    m = re.search(r"\.[^.\\/]+$", path or "")
    if not m:
        return None
    return _EXT_TO_FORMAT.get(m.group(0).lower())


def detect_format(path: str, content: Optional[str] = None) -> str:
    """先按扩展名判断；判断不出或内容明显不符时，按内容特征识别。

    内容识别存在的原因：用户常把 .ass 改名成 .txt，或把 srt 存成无扩展名文件。
    """
    ext_fmt = detect_format_by_extension(path)
    if content is None:
        return ext_fmt or "srt"
    head = content[:4000]
    if "[Script Info]" in head or "[V4+ Styles]" in head or "[Events]" in head:
        return "ass"
    if head.lstrip().startswith("WEBVTT"):
        return "vtt"
    if _LRC_RE.search(head) and "-->" not in head:
        return "lrc"
    if "-->" in head:
        return "srt"
    return ext_fmt or "srt"


def extension_for(fmt: str) -> str:
    return _FORMAT_TO_EXT.get((fmt or "srt").lower(), ".srt")


# --------------------------------------------------------------------------- #
# 时间戳工具
# --------------------------------------------------------------------------- #
def _ts_to_sec(m: re.Match, base: int = 1) -> float:
    """把 _TS 各分组（从 base 开始）转成秒。"""
    h = m.group(base)
    mi = m.group(base + 1)
    s = m.group(base + 2)
    frac = m.group(base + 3)
    total = int(mi) * 60 + int(s)
    if h:
        total += int(h) * 3600
    if frac:
        total += float("0." + frac)
    return float(total)


def _fmt_srt(sec: float) -> str:
    ms = int(round(max(0.0, float(sec)) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def _fmt_vtt(sec: float) -> str:
    return _fmt_srt(sec).replace(",", ".")


def _fmt_ass(sec: float) -> str:
    ms = int(round(max(0.0, float(sec)) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%d:%02d:%02d.%02d" % (h, m, s, ms // 10)


def _fmt_lrc(sec: float) -> str:
    sec = max(0.0, float(sec))
    m = int(sec // 60)
    s = sec - m * 60
    return "[%02d:%05.2f]" % (m, s)


# --------------------------------------------------------------------------- #
# 导入
# --------------------------------------------------------------------------- #
def parse_srt(content: str) -> list:
    """解析 SRT。容错：跳过无时间轴块；文本多行用 \\n 连接。"""
    out = []
    if not content:
        return out
    text = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n")]
        if not lines:
            continue
        idx = None
        for i, ln in enumerate(lines):
            if _TIMING_RE.search(ln):
                idx = i
                break
        if idx is None:
            continue
        m = _TIMING_RE.search(lines[idx])
        try:
            start = _ts_to_sec(m, 1)
            end = _ts_to_sec(m, 5)   # _TS 占 4 个分组，第二个时间戳从 5 开始
        except (TypeError, ValueError):
            continue
        body = "\n".join(lines[idx + 1:]).strip()
        if body:
            out.append({"start": start, "end": end, "text": body})
    return out


def parse_vtt(content: str) -> list:
    """解析 WebVTT。NOTE / STYLE 块与 cue 设置行（align:等）会被跳过。"""
    out = []
    if not content:
        return out
    text = content.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    # 去掉头部与 NOTE/STYLE/REGION 块
    text = re.sub(r"^WEBVTT[^\n]*\n", "", text)
    text = re.sub(r"(?m)^(NOTE|STYLE|REGION)\b[\s\S]*?(?=\n\s*\n|\Z)", "", text)
    for block in re.split(r"\n\s*\n", text):
        lines = block.split("\n")
        idx = None
        for i, ln in enumerate(lines):
            if _TIMING_RE.search(ln):
                idx = i
                break
        if idx is None:
            continue
        m = _TIMING_RE.search(lines[idx])
        try:
            start = _ts_to_sec(m, 1)
            end = _ts_to_sec(m, 5)
        except (TypeError, ValueError):
            continue
        body = "\n".join(lines[idx + 1:]).strip()
        # 去掉内联标签 <v 名字>、<c.yellow>、<00:00:01.000> 等
        body = re.sub(r"<[^>]{0,64}>", "", body).strip()
        if body:
            out.append({"start": start, "end": end, "text": body})
    return out


def parse_ass(content: str) -> list:
    """解析 ASS/SSA。只读 [Events] 段，按 Format 行动态取 Start/End/Text 列序号。

    动态取列序是关键：不同工具生成的 Format 行顺序不同（有的把 Text 放第 10 列，
    有的因加了 Layer/Marked 变成第 11 列），硬编码下标会取错列。
    """
    out = []
    if not content:
        return out
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    in_events = False
    cols = None
    for raw in text.split("\n"):
        line = raw.strip()
        if line.startswith("["):
            in_events = line.lower().startswith("[events]")
            continue
        if not in_events:
            continue
        if line.lower().startswith("format:"):
            cols = [c.strip().lower() for c in line.split(":", 1)[1].split(",")]
            continue
        if not line.lower().startswith("dialogue:"):
            continue
        # Dialogue 行可能含逗号（Text 里），按 cols 数量切分
        payload = line.split(":", 1)[1].lstrip()
        n = len(cols) if cols else 10
        parts = payload.split(",", n - 1)
        if len(parts) < n:
            continue
        try:
            if cols:
                si, ei, ti = cols.index("start"), cols.index("end"), cols.index("text")
            else:
                si, ei, ti = 1, 2, 9
        except ValueError:
            si, ei, ti = 1, 2, min(9, len(parts) - 1)
        ms = _ASS_TIME_RE.search(parts[si])
        me = _ASS_TIME_RE.search(parts[ei])
        if not (ms and me):
            continue
        start = int(ms.group(1)) * 3600 + int(ms.group(2)) * 60 + int(ms.group(3)) + int(ms.group(4)) / 100.0
        end = int(me.group(1)) * 3600 + int(me.group(2)) * 60 + int(me.group(3)) + int(me.group(4)) / 100.0
        body = parts[ti] if ti < len(parts) else ""
        # 去掉 ASS 覆盖标签 {\\pos(...)}、{\\an8} 等，以及 \\N 换行
        body = re.sub(r"\{[^}]{0,200}\}", "", body)
        body = body.replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ").strip()
        if body:
            out.append({"start": start, "end": end, "text": body})
    return out


def parse_lrc(content: str) -> list:
    """解析 LRC。LRC 只有起始时间，结束时间取「下一行起始 - 0.01」，末行 +4 秒。

    多时间标签行（`[00:01.00][00:31.00]副歌`）会展开成多条，这是 LRC 的合规写法。
    """
    out = []
    if not content:
        return out
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    items = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        stamps = list(_LRC_RE.finditer(line))
        if not stamps:
            continue
        body = _LRC_RE.sub("", line).strip()
        if not body:
            continue
        for m in stamps:
            mm = int(m.group(1))
            ss = int(m.group(2))
            frac = m.group(3)
            sec = mm * 60 + ss + (float("0." + frac) if frac else 0.0)
            items.append((sec, body))
    items.sort(key=lambda x: x[0])
    for i, (sec, body) in enumerate(items):
        if i + 1 < len(items):
            end = items[i + 1][0] - 0.01
            if end <= sec:
                end = sec + 0.5
        else:
            end = sec + 4.0
        out.append({"start": sec, "end": end, "text": body})
    return out


_PARSERS = {"srt": parse_srt, "vtt": parse_vtt, "ass": parse_ass, "lrc": parse_lrc}


def parse(content: str, fmt: str = "srt") -> list:
    """按格式解析字幕文本。fmt 未知时按内容自动识别。"""
    f = (fmt or "").lower()
    if f not in _PARSERS:
        f = detect_format("", content)
    parser = _PARSERS.get(f)
    if parser is None:
        # txt 与未知格式：整体当一行（无时间轴），由调用方决定是否可用
        body = (content or "").strip()
        return [{"start": 0.0, "end": 0.0, "text": body}] if body else []
    return parser(content)


def read_file(path: str) -> list:
    """读文件并解析。编码依次尝试 utf-8-sig / utf-8 / gbk（中文字幕常见 gbk）。"""
    raw = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "utf-16"):
        try:
            with open(path, "r", encoding=enc) as f:
                raw = f.read()
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if raw is None:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    return parse(raw, detect_format(path, raw))


# --------------------------------------------------------------------------- #
# 导出
# --------------------------------------------------------------------------- #
def serialize(rows: list, fmt: str = "srt", texts: Optional[list] = None) -> str:
    """把 [{"start","end","text"}] 序列化为指定格式文本。

    参数
    ----
    rows  : 时间轴（text 字段作为默认文本）
    texts : 可选，覆盖每行文本（翻译流程边译边写时用）
    """
    items = []
    for i, r in enumerate(rows or []):
        try:
            s = float(r["start"])
            e = float(r["end"])
        except (KeyError, TypeError, ValueError):
            continue
        t = (texts[i] if texts is not None and i < len(texts) else r.get("text")) or ""
        items.append((s, e, str(t)))

    f = (fmt or "srt").lower()
    if f == "vtt":
        lines = ["WEBVTT", ""]
        for s, e, t in items:
            lines.append("%s --> %s" % (_fmt_vtt(s), _fmt_vtt(e)))
            lines.append(t)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    if f == "ass":
        head = [
            "[Script Info]",
            "Title: SubAI Translator",
            "ScriptType: v4.00+",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding",
            "Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
            "0,0,0,0,100,100,0,0,1,2,0,2,10,10,10,1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
        body = []
        for s, e, t in items:
            one = t.replace("\n", "\\N")
            body.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (_fmt_ass(s), _fmt_ass(e), one))
        return "\n".join(head + body) + "\n"

    if f == "lrc":
        lines = []
        for s, _e, t in items:
            one = t.replace("\n", " ").strip()
            lines.append("%s%s" % (_fmt_lrc(s), one))
        return "\n".join(lines) + "\n"

    if f == "txt":
        # 纯文本：无时间轴，仅正文（去掉换行，一行一条）
        return "\n".join(t.replace("\n", " ").strip() for _s, _e, t in items) + "\n"

    # 默认 srt
    out = []
    for i, (s, e, t) in enumerate(items, 1):
        out.append("%d\n%s --> %s\n%s\n" % (i, _fmt_srt(s), _fmt_srt(e), t))
    return "\n".join(out)


def write_file(rows: list, path: str, fmt: Optional[str] = None,
               texts: Optional[list] = None) -> str:
    """写文件。fmt 缺省按扩展名推断。返回实际路径。"""
    f = (fmt or detect_format_by_extension(path) or "srt").lower()
    content = serialize(rows, f, texts)
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return path
