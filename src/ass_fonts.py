# -*- coding: utf-8 -*-
"""ASS 内嵌字体：读取别人 ASS 里自带的字体。

场景
----
下载的字幕包（尤其日文/多语种番剧）经常把字体直接嵌在 .ass 里，
放在文件末尾的 `[Fonts]` 段。我们如果只用自己的字体，
创作者精心选的字体就全丢了，排版效果和原作差很远。
读出来直接参与渲染，是最省事也最忠实原意的做法。

编码格式（关键，容易写错）
-------------------------
ASS 的内嵌字体**不是** MIME base64，而是 UUencode 变体：
- 每 4 个字符压 3 个字节
- 每个字符占 **6 bit**，值 = 字节值 + **33**（不是 base64 的 65）
- 合法字符范围是 `!`(0x21) 到 `` ` ``(0x60)，即「可打印但非小写字母」
- 长度 l 的编码串解出 floor(l*3/4) 字节

拿标准 base64 解码器处理会得到一堆乱码 —— 而且**不会报错**，
只是字体加载失败，排查起来很费时间。

安全上限（防止恶意/损坏文件撑爆内存）
------------------------------------
- 单份字体 32 MiB
- 全部合计 64 MiB
- 最多 64 份
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Optional

MAX_FONT_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FONTS = 64

_HEADING = re.compile(r"^\s*\[([^\]\r\n]+)\]\s*$")
_FONTNAME = re.compile(r"^fontname:\s*(.*)$", re.IGNORECASE)
_KNOWN_SECTIONS = re.compile(
    r"^(script info|v4\+? styles|events|fonts|graphics)$", re.IGNORECASE)

# 合法的 UUencode 字符范围
_VALID_CHARS = re.compile(r"[\x21-\x60]+")


class AssFontError(ValueError):
    """ASS 内嵌字体解析失败。"""


def decode_ass_font(encoded: str) -> bytes:
    """解码 ASS 内嵌字体的 UUencode 变体。

    每 4 字符 -> 3 字节；每字符 -33 后占 6 bit。
    长度余 1 是非法的（无法构成完整字节）。
    """
    if not encoded:
        raise AssFontError("空的字体编码")
    if len(encoded) % 4 == 1:
        raise AssFontError("字体编码长度 %d 非法（余 1）" % len(encoded))
    if not _VALID_CHARS.fullmatch(encoded):
        raise AssFontError("字体编码含非法字符（应为 0x21-0x60）")

    size = (len(encoded) * 3) // 4
    if size > MAX_FONT_BYTES:
        raise AssFontError("单份字体超过 %d MiB" % (MAX_FONT_BYTES // 1048576))

    out = bytearray()
    for i in range(0, len(encoded), 4):
        chunk = encoded[i:i + 4]
        value = 0
        for j, ch in enumerate(chunk):
            value |= (ord(ch) - 33) << (18 - j * 6)
        out.append((value >> 16) & 0xFF)
        if len(chunk) >= 3:
            out.append((value >> 8) & 0xFF)
        if len(chunk) == 4:
            out.append(value & 0xFF)
    return bytes(out)


def _heading(line: str, nxt: str = "") -> Optional[str]:
    """识别段落标题。

    难点：字体编码行看起来也像 `[AB]`，会被误判成新段落，
    导致把字体数据切断。所以只在「标题内容像人类可读的段名」，
    或下一行不是编码内容时才认。
    """
    m = _HEADING.match(line)
    if not m:
        return None
    name = m.group(1)
    # 已知段名一定认
    if _KNOWN_SECTIONS.match(name.strip()):
        return name.strip().lower()
    # 含控制字符或中文等 → 是编码行，不是段名
    if re.search(r"[\x00-\x20\x7f-\uffff]", name):
        return None
    # 下一行如果还是编码内容且不是 fontname，就认为这是字体数据
    if nxt and _VALID_CHARS.fullmatch(nxt.strip() or " ") and not _FONTNAME.match(nxt):
        return None
    return name.strip().lower()


def normalize_font_sections(content: str) -> str:
    """把 `[Fonts]` 段挪到文件末尾。

    libass 的读取规则：`[Fonts]` 之后的未知段落会被当成附件二进制，
    所以字体段必须放最后，否则会污染后续解析。
    没有 `[Fonts]` 段时原样返回。
    """
    lines = content.splitlines()
    kept: list = []
    fonts: list = []
    section = ""
    for i, line in enumerate(lines):
        h = _heading(line, lines[i + 1] if i + 1 < len(lines) else "")
        if h:
            section = h
            if h == "fonts":
                continue
        (fonts if section == "fonts" else kept).append(line)
    if not fonts:
        return content
    while kept and kept[-1] == "":
        kept.pop()
    while fonts and fonts[-1] == "":
        fonts.pop()
    return "\n".join(kept) + "\n\n[Fonts]\n" + "\n".join(fonts) + "\n"


def read_embedded_fonts(content: str) -> list:
    """从 ASS 文本里读出内嵌字体。

    返回 [{"name": str, "data": bytes, "id": sha256, "ext": ".ttf"/".otf"}]。
    没有字体段返回 []。超限或编码非法抛 AssFontError。
    """
    fonts: list = []
    total = 0
    section = ""
    name: Optional[str] = None
    chunks: list = []
    chunk_len = 0

    def flush() -> None:
        nonlocal name, chunks, chunk_len, total
        if name is None:
            return
        estimate = (chunk_len * 3) // 4
        if total + estimate > MAX_TOTAL_BYTES or len(fonts) >= MAX_FONTS:
            raise AssFontError("ASS 内嵌字体超过总量上限")
        data = decode_ass_font("".join(chunks))
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise AssFontError("ASS 内嵌字体超过总量上限")
        fonts.append({
            "name": name,
            "data": data,
            "id": hashlib.sha256(data).hexdigest(),
            "ext": detect_font_ext(data),
        })
        name = None
        chunks = []
        chunk_len = 0

    lines = content.splitlines()
    for i, line in enumerate(lines):
        h = _heading(line, lines[i + 1] if i + 1 < len(lines) else "")
        if h:
            flush()
            section = h
            continue
        if section != "fonts":
            continue
        m = _FONTNAME.match(line)
        if m:
            flush()
            name = m.group(1).strip()
            if not name:
                raise AssFontError("内嵌字体缺少名称")
        elif name is not None and line.strip():
            body = line.strip()
            chunk_len += len(body)
            if chunk_len > (MAX_FONT_BYTES * 4) // 3 + 64:
                raise AssFontError("单份内嵌字体超过 %d MiB"
                                   % (MAX_FONT_BYTES // 1048576))
            chunks.append(body)
    flush()
    return fonts


def detect_font_ext(data: bytes) -> str:
    """按文件头判断扩展名。TTF/OTF 的 sfnt tag 不同。"""
    if len(data) < 4:
        return ".ttf"
    tag = data[:4]
    if tag in (b"OTTO",):
        return ".otf"
    if tag in (b"ttcf",):
        return ".ttc"
    return ".ttf"


def extract_to_dir(content: str, dest_dir: str) -> dict:
    """把内嵌字体解出来写到目录里。返回 {fonts, written}。

    文件名用 `<字体名>.<ext>`；重名的按 id 前 8 位加后缀，避免互相覆盖。
    """
    fonts = read_embedded_fonts(content)
    os.makedirs(dest_dir, exist_ok=True)
    written: list = []
    used = set()
    for f in fonts:
        safe = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]+", "_", f["name"]).strip("_")
        if not safe:
            safe = "font_%s" % f["id"][:8]
        fname = safe + f["ext"]
        if fname.lower() in used:
            fname = "%s_%s%s" % (safe, f["id"][:8], f["ext"])
        used.add(fname.lower())
        path = os.path.join(dest_dir, fname)
        with open(path, "wb") as fh:
            fh.write(f["data"])
        written.append(path)
    return {"fonts": fonts, "written": written}