# -*- coding: utf-8 -*-
"""五期：把「用户打的稿子」自动对到时间轴上。

为什么这么做：新手最怕的就是卡时间轴。用户只需要一行一句把话打出来，
这里负责把每句话落到"确实有人在说话"的时间段上，不需要他碰时间码。

算法（从准到稳，按顺序尝试）：
1. **段数正好相等** → 一对一直接对应（最常见也最准）；
2. 否则按每行的"说话量"（中日韩按字、西文按词）**按比例分摊**到语音段上，
   并且**只在有语音的时间段内推进**——这样字幕不会出现在没人说话的空白处。

已知边界（如实记录）：一行稿子对应好几段语音、或反过来多行挤在一段里时，
只能按比例摊，不会做真正的强制对齐；因此界面必须提供"改字幕"页给用户微调。
"""
from __future__ import annotations

import re

#: 中日韩文字范围（按字计权）
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
_WORD = re.compile(r"[A-Za-z0-9'\-]+")


def line_weight(text: str) -> float:
    """估算一句话"说起来要多久"：中日韩按字、西文按词，其它字符权重很低。"""
    if not text:
        return 1.0
    cjk = len(_CJK.findall(text))
    word_list = _WORD.findall(text)
    # 空白与标点不该按字符计入（否则 "hello world" 会因为空格多出权重）
    stripped = re.sub(r"\s+", "", text)
    other = max(0, len(stripped) - cjk - sum(len(w) for w in word_list))
    return max(1.0, cjk * 1.0 + len(word_list) * 1.0 + other * 0.2)


def _abs_time(segs: list, index: int, offset: float) -> float:
    index = max(0, min(index, len(segs) - 1))
    return segs[index][0] + offset


def align_script_to_speech(lines: list, rows: list, *, min_duration: float = 0.8) -> list:
    """把稿子按顺序对齐到语音时间段。

    Args:
        lines: 用户打的稿子（一行一句，空行会被忽略）
        rows: 识别结果 [{start, end, text}]，这里只取时间（不采用识别出的文字）
        min_duration: 每句最短时长（秒），避免出现一闪而过的字幕

    Returns:
        [{"start": float, "end": float, "text": str}]，按时间升序、互不重叠；
        没有稿子或没有语音时返回空列表。
    """
    cleaned = [str(x).strip() for x in (lines or []) if str(x).strip()]
    segs: list = []
    for r in (rows or []):
        try:
            s = max(0.0, float(r.get("start") or 0))
            e = float(r.get("end") or 0)
        except (TypeError, ValueError):
            continue
        if e > s:
            segs.append((s, e))
    if not cleaned or not segs:
        return []

    # 1) 段数相等：一对一（最准）
    if len(segs) == len(cleaned):
        return [{"start": round(s, 3), "end": round(e, 3), "text": t}
                for (s, e), t in zip(segs, cleaned)]

    # 2) 否则按"说话量"比例分摊，并且只在语音段内推进
    total_speech = sum(e - s for s, e in segs)
    weights = [line_weight(t) for t in cleaned]
    weight_sum = sum(weights) or 1.0
    index, offset = 0, 0.0
    out: list = []
    for text, weight in zip(cleaned, weights):
        need = max(min_duration, total_speech * (weight / weight_sum))
        start = _abs_time(segs, index, offset)
        while need > 1e-6 and index < len(segs):
            available = (segs[index][1] - segs[index][0]) - offset
            if available <= 1e-6:
                index += 1
                offset = 0.0
                continue
            take = min(available, need)
            offset += take
            need -= take
            if need > 1e-6:
                index += 1
                offset = 0.0
        if index >= len(segs):
            index = len(segs) - 1
            offset = segs[index][1] - segs[index][0]
        end = _abs_time(segs, index, offset)
        if end - start < 0.3:
            end = start + 0.3
        out.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    return out


def align_stats(segments: list) -> dict:
    """给日志/界面用的小结。"""
    if not segments:
        return {"count": 0, "span": 0.0}
    return {
        "count": len(segments),
        "span": round(segments[-1]["end"] - segments[0]["start"], 3),
    }
