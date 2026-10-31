# -*- coding: utf-8 -*-
"""把「字体解析 / ASS 内嵌字体 / 字形回退」串成一个入口。

为什么需要一个统一入口
----------------------
这三件事单独看都不复杂，但它们的**调用顺序和失败处理**互相牵连：

1. 别人给的 `.ass` 里可能自带字体（`[Fonts]` 段）。
   这些字体必须先解出来，才能参与「哪个字体覆盖哪个字」的判断。
2. 有了可用字体集合，才能算出主字体缺哪些字。
3. 算出缺字后才能注入行内 `{\fn}` 标签。

如果让调用方自己拼这三步，很容易漏掉第 1 步（于是「明明字幕包里带了字体，
却还是显示方框」），或者把顺序搞反。

失败策略（重要）
----------------
字体相关的环节**任何一步失败都不能让出片失败**：
- 字体文件损坏 → 跳过该字体，继续用其它字体
- ASS 内嵌字体解码失败 → 忽略内嵌，用系统字体
- 字形解析失败 → 不做回退（退化成改动前行为，而不是报错）

理由：字体缺字只会让个别字显示成方框，
而任务的失败会让用户拿不到任何成品。两者严重程度差一个量级。
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

from src import glyphs


def _load_by_family(families: list) -> tuple:
    """按字体族名加载 FontFace。返回 (faces, loaded_names)。"""
    from src import fonts as fonts_module
    faces: list = []
    names: list = []
    for fam in families or []:
        if not fam:
            continue
        try:
            path = fonts_module.resolve_font_file(fam)
        except Exception:  # noqa: BLE001
            path = None
        if not path:
            continue
        face = glyphs.load_face(path)
        if face is not None:
            faces.append(face)
            names.append(fam)
    return faces, names


def prepare(
    texts: list,
    primary_family: str,
    fallback_families: Optional[list] = None,
    ass_content: Optional[str] = None,
    extract_dir: Optional[str] = None,
) -> dict:
    """一次算好渲染需要的字体信息。

    参数
    ----
    texts            : 全部字幕文本（用来统计缺字）
    primary_family   : 样式里的主字体族名
    fallback_families: 候选回退字体族名（按优先级）
    ass_content      : 可选，原始 ASS 文本（用于提取内嵌字体）
    extract_dir      : 内嵌字体解到哪个目录（None 用临时目录）

    返回
    ----
    {
      "fallback_family": str|None,   # 注入 ASS 用的回退字体族名
      "glyph_fallback": dict|None,   # 直接喂 build_ass_document
      "missing_chars": [str],        # 所有字体都缺的字（给用户告警）
      "embedded_fonts": [str],       # 从 ASS 里解出来的字体路径
      "embedded_names": [str],
      "reports": [dict],             # 每个候选字体的覆盖统计
      "ok": bool,
      "error": str|None,
    }
    """
    result = {
        "fallback_family": None,
        "glyph_fallback": None,
        "missing_chars": [],
        "embedded_fonts": [],
        "embedded_names": [],
        "reports": [],
        "ok": False,
        "error": None,
    }

    all_text = "".join(str(t or "") for t in (texts or []))
    if not all_text.strip():
        result["ok"] = True
        return result

    try:
        # ---- 第 1 步：解出 ASS 自带字体（若提供） ----
        embedded_paths: list = []
        embedded_names: list = []
        if ass_content:
            try:
                from src import ass_fonts
                dest = extract_dir or tempfile.mkdtemp(prefix="assfont_")
                got = ass_fonts.extract_to_dir(ass_content, dest)
                embedded_paths = got["written"]
                embedded_names = [f["name"] for f in got["fonts"]]
            except Exception as e:  # noqa: BLE001
                # 内嵌字体坏了不影响主流程，只是少了一种字体来源
                result["error"] = "内嵌字体解析失败: %s" % (str(e)[:120],)
        result["embedded_fonts"] = embedded_paths
        result["embedded_names"] = embedded_names

        # ---- 第 2 步：加载字体 ----
        primary_faces, primary_names = _load_by_family([primary_family])
        fb_faces, fb_names = _load_by_family(list(fallback_families or []))

        # 内嵌字体也能当回退用（优先级排系统字体之前：
        # 创作者内嵌的字体就是想让字幕用它的）
        for p in embedded_paths:
            face = glyphs.load_face(p)
            if face is not None:
                fb_faces.insert(0, face)
                fb_names.insert(0, os.path.splitext(os.path.basename(p))[0])

        if not primary_faces and not fb_faces:
            result["ok"] = True          # 没字体可用 = 不做回退，不是错误
            return result

        primary = primary_faces[0] if primary_faces else fb_faces[0]

        # ---- 第 3 步：算缺字 ----
        missing = primary.missing_codepoints(all_text)
        result["reports"].append({
            "family": primary_names[0] if primary_names else "(内嵌)",
            "path": primary.path,
            "format": primary.format,
            "missing_count": len(missing),
        })

        if not missing:
            result["ok"] = True
            return result

        # ---- 第 4 步：找能覆盖的回退字体 ----
        # 逐个候选算「能补掉多少缺字」，取覆盖最多的那个。
        # 不按顺序取第一个能补任意字的：那样可能选到只补一个字的字体，
        # 剩下的字仍然缺，却白白多引入一种字体。
        best = None
        for face, name in zip(fb_faces, fb_names):
            if face.path == primary.path:
                continue
            covered = [c for c in missing if face.has_glyph(c)]
            result["reports"].append({
                "family": name,
                "path": face.path,
                "format": face.format,
                "covers": len(covered),
                "needed": len(missing),
            })
            if covered and (best is None or len(covered) > best[1]):
                best = (name, len(covered), covered)

        if best is None:
            # 没有任何候选能补 —— 如实报出来，让用户自己装字体
            result["missing_chars"] = sorted({chr(c) for c in missing})
            result["ok"] = True
            return result

        name, _count, covered = best
        still_missing = sorted({chr(c) for c in missing if c not in covered})
        result["fallback_family"] = name
        result["glyph_fallback"] = {
            "fallback_family": name,
            "chars": "".join(chr(c) for c in covered),
        }
        result["missing_chars"] = still_missing
        result["ok"] = True
        return result

    except Exception as e:  # noqa: BLE001
        # 字体处理整体失败：退化成「不做回退」，绝不让出片失败
        result["ok"] = False
        result["error"] = "%s: %s" % (type(e).__name__, str(e)[:160])
        result["fallback_family"] = None
        result["glyph_fallback"] = None
        return result