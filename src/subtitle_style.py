# -*- coding: utf-8 -*-
"""字幕样式与 ASS 生成（纯函数，零第三方依赖）。

为什么要有这个模块
------------------
原来烧硬字幕只能给 ffmpeg 传 `force_style=FontName=...,FontSize=...`，
样式能力等于「换个字体、调个字号」。做成品视频时这远远不够——
颜色、描边、阴影、位置、背景框都是刚需，观众一眼能看出是不是机器做的。

同类项目 SmartSub 有一套完整的 ASS 样式链路（`assStyleBuilder` / `assFonts` /
`assCanvas` / `fontResolver`）。本模块按同样的思路实现本项目需要的子集，
但**刻意不引入字体文件解析**（见下）。

设计取舍
--------
1. **不自研字体文件解析**。SmartSub 会读字体文件算字形覆盖来做逐字回退
   （中文缺字时回退到另一个字体）。这需要解析 TTF/OTF 的 cmap 表，
   还要处理 CJK 异体字，坑极深。本项目采用**系统字体 + 显式回退链**：
   `font_family` 用一个候选列表，libass 自己按顺序找第一个能用的。
   libass 内建这个能力，效果接近且零维护成本。

2. **脚本空间固定为 384×288**（`PlayResX/Y`）。这不是随便定的：
   ffmpeg 把 SRT 隐式转 ASS 时用的就是这个空间，libass 默认值也是它。
   沿用它可以保证「用户之前保存的字号/边距/描边数值，烧录观感完全不变」——
   语义从「隐式默认」变成「显式声明」，零回归。

3. **颜色用 CSS 语义**（`#RRGGBB` 或 `rrggbb`），内部转 ASS 的 `&HAABBGGRR`。
   ASS 的颜色是 BGR 且 alpha 语义反转（00=不透明），这里封装掉，调用方不用记。

4. **全部纯函数**：给定输入必得同一字符串，便于单测与「预览=烧录」一致性。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Optional

# ASS 脚本空间：与 ffmpeg 的 SRT 隐式转换 / libass 默认一致（见模块注释第 2 点）
ASS_PLAY_RES_X = 384
ASS_PLAY_RES_Y = 288

# 对齐方式（numpad 风格 1-9，与前端 UI 一致：7/8/9 上排，4/5/6 中排，1/2/3 下排）
ALIGN_VALUES = {
    1: 1, 2: 2, 3: 3,      # 底部左/中/右
    4: 9, 5: 10, 6: 11,    # 中部左/中/右（SSA legacy 编码）
    7: 5, 8: 6, 9: 7,      # 顶部左/中/右
}

# 边框样式：1=描边+阴影，3=背景框（libass 用 OutlineColour 画框）
BORDER_OUTLINE = 1
BORDER_BOX = 3


@dataclass
class SubtitleStyle:
    """字幕样式。默认值刻意对齐 ffmpeg 的 SRT 隐式样式，保证零回归。

    字段命名尽量贴近用户认知（font_size 就是「字号」），
    转换到 ASS 的那些别扭细节（BGR、alpha 反转、legacy 对齐码）都在本类内部处理。
    """
    font_family: str = "Microsoft YaHei"     # 可给候选链："Microsoft YaHei,Arial"
    font_size: int = 20                      # 脚本空间 288 下的字号
    primary_color: str = "#FFFFFF"           # 文字色（CSS）
    outline_color: str = "#000000"           # 描边色
    back_color: str = "#000000"              # 背景/阴影色
    outline: float = 2.0                     # 描边宽度（0=无描边）
    shadow: float = 0.0                      # 阴影距离（0=无阴影）
    alignment: int = 2                       # numpad 对齐（默认底部居中）
    margin_l: int = 10
    margin_r: int = 10
    margin_v: int = 10
    bold: bool = False
    italic: bool = False
    underline: bool = False
    border_style: int = BORDER_OUTLINE       # 1=描边，3=背景框
    back_opacity: int = 50                   # 背景不透明度（0-100，仅 border_style=3 有意义）
    spacing: float = 0.0                     # 字间距
    scale_x: int = 100
    scale_y: int = 100

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "SubtitleStyle":
        """从 dict 构造；未知字段忽略、类型错误回落默认值。

        容错是必需的：样式会从 JSON 配置/API 表单来，字段缺失或类型不对
        不应该让整个烧录任务失败。
        """
        base = cls()
        if not isinstance(d, dict):
            return base
        for f in base.__dataclass_fields__:  # type: ignore[attr-defined]
            if f not in d:
                continue
            v = d[f]
            cur = getattr(base, f)
            try:
                if isinstance(cur, bool):
                    setattr(base, f, bool(v))
                elif isinstance(cur, int):
                    setattr(base, f, int(v))
                elif isinstance(cur, float):
                    setattr(base, f, float(v))
                elif isinstance(cur, str):
                    setattr(base, f, str(v))
            except (TypeError, ValueError):
                continue
        return base


# --------------------------------------------------------------------------- #
# 颜色
# --------------------------------------------------------------------------- #
_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def parse_hex_color(css: str) -> Optional[tuple]:
    """`#RGB` / `#RRGGBB` / 无井号 → (r, g, b)。无法解析返回 None。

    注意 3 位形式的陷阱：`bad` 的 b/a/d 全是合法十六进制字符，
    会被当成 `#BBAADD` —— 用户显然不是这个意思。所以**无井号的 3 位形式一律不认**：
    `#f00` 是颜色缩写，而 `bad` / `abc` 这类裸词几乎总是笔误。
    """
    s = (css or "").strip()
    m = _HEX_RE.match(s)
    if not m:
        return None
    h = m.group(1)
    if len(h) == 3:
        if not s.startswith("#"):
            return None          # 裸 3 位不认，避免把单词当颜色
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def css_to_ass_color(css: str, opacity_pct: int = 100) -> str:
    """CSS 颜色 → ASS `&HAABBGGRR`。

    两个反直觉点必须在这里封装掉：
    - ASS 是 **BGR** 顺序，不是 RGB
    - ASS 的 alpha 是 **反转** 的：`00` = 完全不透明，`FF` = 全透明
    解析失败时返回白色不透明（宁可用默认色，也不要生成非法值让 libass 静默错渲）。
    """
    rgb = parse_hex_color(css)
    if rgb is None:
        rgb = (255, 255, 255)
    r, g, b = rgb
    try:
        op = max(0, min(100, int(opacity_pct)))
    except (TypeError, ValueError):
        op = 100
    alpha = int(round((1 - op / 100.0) * 255))
    return "&H%02X%02X%02X%02X" % (alpha, b, g, r)


# --------------------------------------------------------------------------- #
# 字体
# --------------------------------------------------------------------------- #
def sanitize_font_family(name: str) -> str:
    """清掉会破坏 ASS CSV 的字符。

    Style 行是逗号分隔的定长表，字体名里出现逗号会让后面所有字段错位，
    libass 会静默按错位的值渲染（不报错，只是画面不对）。
    ASS 没有转义语法，只能剥离。
    """
    s = (name or "").strip()
    s = s.replace(",", " ").replace("\n", " ").replace("\r", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s or "Arial"


def resolve_font_chain(chain: str) -> str:
    """候选字体链归一化：`"A, B , C"` → `"A, B, C"`，去掉空项与非法字符。

    libass 会按顺序找第一个可用字体，所以候选链本身就是回退机制，
    不需要我们自己解析字体文件判断字形覆盖。
    """
    parts = [sanitize_font_family(p) for p in (chain or "").split(",")]
    seen = []
    for p in parts:
        if p and p not in seen:
            seen.append(p)
    return ", ".join(seen) or "Arial"


# --------------------------------------------------------------------------- #
# 样式行
# --------------------------------------------------------------------------- #
def build_style_line(style: SubtitleStyle, name: str = "Default") -> str:
    """生成 `[V4+ Styles]` 的 Style 行。

    BorderStyle=3（背景框）时 libass 的实际取色语义：
    - 背景框由 **OutlineColour** 绘制，阴影区由 BackColour 绘制
    - 因此两者都取 back_color，否则 shadow>0 会露出异色边
    - 该模式下 libass 不画文字描边，Outline 数值被复用为「框的 padding」
    """
    is_box = style.border_style == BORDER_BOX
    back_alpha = style.back_opacity if is_box else 100

    primary = css_to_ass_color(style.primary_color, 100)
    if is_box:
        outline_c = css_to_ass_color(style.back_color, back_alpha)
    else:
        outline_c = css_to_ass_color(style.outline_color, 100)
    back_c = css_to_ass_color(style.back_color, back_alpha)

    eff_outline = max(style.outline, 1) if is_box else max(0, style.outline)
    eff_shadow = 0 if is_box else max(0, style.shadow)

    return (
        "Style: {name},{font},{size},{pri},{sec},{out},{back},{bold},{italic},"
        "{under},{strike},100,100,{spacing},0,{bs},{ol},{sh},{align},"
        "{ml},{mr},{mv},1"
    ).format(
        name=sanitize_font_family(name),
        font=sanitize_font_family(resolve_font_chain(style.font_family)),
        size=max(1, int(style.font_size)),
        pri=primary,
        sec=primary,
        out=outline_c,
        back=back_c,
        bold=-1 if style.bold else 0,
        italic=-1 if style.italic else 0,
        under=-1 if style.underline else 0,
        strike=0,
        spacing=float(style.spacing),
        bs=style.border_style if style.border_style in (1, 3) else 1,
        ol=eff_outline,
        sh=eff_shadow,
        align=ALIGN_VALUES.get(int(style.alignment), 2),
        ml=max(0, int(style.margin_l)),
        mr=max(0, int(style.margin_r)),
        mv=max(0, int(style.margin_v)),
    )


STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
    "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
    "Alignment, MarginL, MarginR, MarginV, Encoding"
)


def fmt_ass_time(sec: float) -> str:
    """秒 → ASS 时间 `H:MM:SS.cc`（注意是 2 位百分秒，不是毫秒）。"""
    s = max(0.0, float(sec))
    total_cs = int(round(s * 100))
    h, rem = divmod(total_cs, 360000)
    m, rem = divmod(rem, 6000)
    ss, cs = divmod(rem, 100)
    return "%d:%02d:%02d.%02d" % (h, m, ss, cs)


def build_ass_document(rows: list, texts: Optional[list] = None,
                       style: Optional[SubtitleStyle] = None,
                       title: str = "SubAI Translator",
                       glyph_fallback: Optional[dict] = None) -> str:
    """把字幕行渲染成完整 ASS 文档。

    参数
    ----
    rows  : [{"start","end","text"}]
    texts : 可选，覆盖文本（翻译流程边译边写用）
    style : 样式，None 用默认
    glyph_fallback : 可选，字形回退配置（[2026-10-25] 新增）

    glyph_fallback 结构（由调用方按 src/glyphs.py 计算好）：
        {"fallback_family": "SimHei",     # 回退字体族名，写进 ASS 的 \fn
         "chars": "敌人龘"}               # 主字体缺这些字时才切

    为什么需要：ASS 只记录**字体名**。主字体缺字时 libass 会画方框，
    用户只看到「字幕里冒出几个方块」却不知原因。
    处理方式是把缺的字用 {\fn回退字体} 包起来 —— ASS 的行内样式覆盖，
    不需要拆成多行，也不需要改 Style。

    为什么要求调用方算好、而不是这里自己算：
    算字形覆盖要读字体文件（几十 MB），放渲染路径里会让纯文本生成变慢，
    且 build_ass_document 应保持无 I/O 的纯函数性质（便于测试）。
    """
    st = style or SubtitleStyle()
    head = [
        "[Script Info]",
        "Title: %s" % (title or "SubAI Translator"),
        "ScriptType: v4.00+",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        # 固定脚本空间（见模块注释第 2 点）
        "PlayResX: %d" % ASS_PLAY_RES_X,
        "PlayResY: %d" % ASS_PLAY_RES_Y,
        "",
        "[V4+ Styles]",
        STYLE_FORMAT,
        build_style_line(st),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    body = []
    for i, r in enumerate(rows or []):
        try:
            s = float(r["start"])
            e = float(r["end"])
        except (KeyError, TypeError, ValueError):
            continue
        t = (texts[i] if texts is not None and i < len(texts) else r.get("text")) or ""
        t = str(t).replace("\n", "\\N")   # ASS 用 \N 表示硬换行
        # [2026-10-25] 字形回退：把主字体缺的字用 {\fn回退字体} 包起来。
        # 只替换真正缺失的字符，正常文字保持原样 —— 否则每行都带一堆
        # 行内样式标签，既难读也会拖慢 libass 解析。
        if glyph_fallback:
            t = _apply_glyph_fallback(t, glyph_fallback)
        body.append("Dialogue: 0,%s,%s,Default,,0,0,0,,%s" % (fmt_ass_time(s), fmt_ass_time(e), t))
    return "\n".join(head + body) + "\n"




def _apply_glyph_fallback(text: str, cfg: dict) -> str:
    """把 text 中属于「主字体缺字集合」的连续字符用 {\\fn字体} 包裹。

    ASS 行内覆盖的写法是 `{\\fnSimHei}敌人{\\fn}`，末尾空 \\fn 表示恢复样式字体的字体。
    连续缺字合成一段而不是逐字包裹 —— 逐字会产生大量标签，
    实测在长行上明显拖慢 libass 解析且让 ASS 文件体积膨胀数倍。
    """
    family = str((cfg or {}).get("fallback_family") or "").strip()
    chars = (cfg or {}).get("chars") or ""
    if not family or not chars:
        return text
    missing = set(chars)
    out: list = []
    in_run = False
    # ASS 的转义序列：反斜杠 + 紧跟的一个字母（\N 硬换行、\n 软换行、\h 空格）。
    # 这类组合必须整体跳过，否则会把 "\N" 拆成 "\" + 被包裹的 "N"，
    # 标签结构坏掉，表现为「换行消失」——实测确实会这样。
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        is_escape = (ch == "\\" and i + 1 < n)
        if is_escape:
            if in_run:
                out.append("{\\fn}")
                in_run = False
            out.append(ch)
            out.append(text[i + 1])
            i += 2
            continue
        i += 1
        # 反斜杠和大括号是 ASS 的转义/标签语法字符，绝不能包进 {\fn} 段。
        need = (ch in missing) and (ch not in ("\\", "{"))
        if need:
            if not in_run:
                out.append("{\\fn%s}" % family)
                in_run = True
            out.append(ch)          # 字符本身必须写出去，这一步漏了会丢字
        else:
            if in_run:
                out.append("{\\fn}")   # 空 \fn 恢复样式字体
                in_run = False
            out.append(ch)
    if in_run:
        out.append("{\\fn}")
    return "".join(out)


# --------------------------------------------------------------------------- #
# force_style（兼容旧路径：不想生成 ASS 文件时直接喂 ffmpeg）
# --------------------------------------------------------------------------- #
def build_force_style(style: SubtitleStyle) -> str:
    """生成 ffmpeg `subtitles=...:force_style='...'` 用的样式串。

    与 build_style_line 同源，保证「预览 / 生成 ASS / 直接 force_style」
    三条路径观感一致 —— 这是最容易被忽略的一致性要求。
    """
    line = build_style_line(style)
    payload = line.split(":", 1)[1].strip()
    # Style 行的列序是：Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,
    # OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY,
    # Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
    # 第一列 Name 不属于 force_style，必须跳过 —— 否则整串右移一位，
    # ffmpeg 会把样式名字符串当 FontName、把字号当 FontSize 之后的字段，
    # 实测表现为「字体名变成一个叫 Default 的字体、字号失效」，且 ffmpeg 不报错。
    vals = payload.split(",")
    if vals:
        vals = vals[1:]
    keys = [
        "FontName", "FontSize", "PrimaryColour", None, "OutlineColour",
        "BackColour", "Bold", "Italic", "Underline", None, "ScaleX", "ScaleY",
        "Spacing", None, "BorderStyle", "Outline", "Shadow", "Alignment",
        "MarginL", "MarginR", "MarginV",
    ]
    out = []
    for k, v in zip(keys, vals):
        if not k:
            continue
        if k in ("PrimaryColour", "OutlineColour", "BackColour"):
            out.append("%s=%s&" % (k, v))
        else:
            out.append("%s=%s" % (k, v))
    return ",".join(out)
