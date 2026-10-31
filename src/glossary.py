# -*- coding: utf-8 -*-
"""五期 P2：专有名词词表 + 同音纠正。

四条硬约束（真机实测 + 裁决得出，缺一条就会从「一致地错」变成「自动地错」）：
1. **编辑距离在拼音上算**，不在汉字上算。汉字距离对两字词几乎等于「任意近义词都命中」，
   会把真角色「队长」误纠成主播名「橘长」；拼音层面 dui≠ju，天然不命中。
2. **只有拼音全等才自动纠正**；近音（距离=1）只标记 suspect，交用户确认。
   同音是强信号，近音是弱信号——弱信号自动执行，误伤成本高于收益。
3. **多个词表词拼音相同时只标记不纠正**（主播「橘长」与角色「局长」可同时存在，
   系统无从判断这一处该是哪个）。
4. 纠正改的是 **ASR 输出的原文**，且必须发生在**摘要之前、缓存 key 之前**，
   否则双语字幕对不上、缓存会命中旧译文。

无 pypinyin 时自动降级为「原文全等」匹配（功能不缺失，只是同音纠正失效）。
"""
from __future__ import annotations

from typing import Optional

try:
    from pypinyin import Style, pinyin as _pinyin
    _HAS_PINYIN = True
except Exception:  # noqa: BLE001
    _HAS_PINYIN = False


def py_groups(s: str) -> list[frozenset]:
    """每个字的读音集合（多音字给多读音）；无 pypinyin 时退回单字符集合。"""
    if not s:
        return []
    if not _HAS_PINYIN:
        return [frozenset([ch]) for ch in s]
    try:
        return [frozenset(x) for x in _pinyin(s, style=Style.NORMAL, heteronym=True)]
    except Exception:  # noqa: BLE001
        return [frozenset([ch]) for ch in s]


def same_sound(a: list[frozenset], b: list[frozenset]) -> bool:
    """逐字读音有交集即视为同音（多音字任一读音对上就算）。"""
    if not a or not b or len(a) != len(b):
        return False
    return all(x & y for x, y in zip(a, b))


def sound_distance(a: list[frozenset], b: list[frozenset]) -> int:
    """以「字」为单位的读音编辑距离：同音字记 0 次替换。"""
    n, m = len(a), len(b)
    if n == 0:
        return m
    if m == 0:
        return n
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i]
        for j in range(1, m + 1):
            cost = 0 if (a[i - 1] & b[j - 1]) else 1
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost))
        prev = cur
    return prev[-1]


def correct_text(text: str, glossary: list[dict]) -> tuple[str, list[dict]]:
    """对一行原文做词表纠正。

    glossary: [{"src": "橘长", "type": "person"}, ...]
    返回 (新文本, 命中列表)；命中项 kind: auto（已自动纠正）/ suspect（仅提示）。
    """
    if not text or not glossary:
        return text, []
    entries = []
    force_map: list[tuple[str, str]] = []
    for g in glossary:
        src = (g.get("src") or "").strip() if isinstance(g, dict) else str(g or "").strip()
        if not src or len(src) < 2:
            continue
        entries.append({"src": src, "py": py_groups(src), "type": (g.get("type") if isinstance(g, dict) else None) or "term"})
        # [P1 2026-10-24] variants：用户**当面确认过**的误识别写法，直接子串替换。
        # 起因：真实素材里大量误识别既不同音也不同长度，拼音规则完全够不着——
        #   甲球→甲修(qiu/xiu)、小鸡→小金(ji/jin)、牛转→牛的(zhuan/de)、1414→M14(4字→3字)
        # 这些都是用户听完原片亲口确认的，属于强信号，没必要再用拼音去猜。
        # 注意：variants 不做任何推断，只做精确匹配替换，填错才会改错，因此只收人工确认过的。
        if isinstance(g, dict):
            for _v in (g.get("variants") or []):
                _v = str(_v or "").strip()
                if _v and _v != src:
                    force_map.append((_v, src))
    if not entries and not force_map:
        return text, []

    hits: list[dict] = []
    out = text

    # 1) 强制映射优先：长写法先替换，避免短变体把长串拆坏
    for _pat, _src in sorted(force_map, key=lambda x: -len(x[0])):
        if _pat and _pat in out:
            _cnt = out.count(_pat)
            out = out.replace(_pat, _src)
            hits.append({"pos": out.find(_src), "original": _pat, "corrected": _src,
                         "kind": "auto", "reason": "variant", "count": _cnt})
    for e in entries:
        n = len(e["src"])
        i = 0
        while n and i <= len(out) - n:
            win = out[i:i + n]
            wpy = py_groups(win)
            if win == e["src"]:
                i += n
                continue
            if same_sound(wpy, e["py"]):
                # 冲突：词表里还有别的词与它同音 → 无从判断，只提示
                clash = [x for x in entries if x is not e and same_sound(x["py"], e["py"])]
                if clash:
                    hits.append({"pos": i, "original": win, "corrected": e["src"],
                                 "kind": "suspect", "reason": "conflict"})
                else:
                    out = out[:i] + e["src"] + out[i + n:]
                    hits.append({"pos": i, "original": win, "corrected": e["src"],
                                 "kind": "auto", "reason": "homo"})
                    i += n
                    continue
            elif sound_distance(wpy, e["py"]) == 1:
                # 近音只提示；且必须与原词**至少共享一个汉字**，否则纯拼音巧合会误报
                # （实测：「据说」ju shuo 与「橘长」ju zhang 距离 1，但无共同汉字，
                #   而真实的同音变体「局长/区长/队长→橘长」都共享「长」字）。
                # 注意边界：单字专有名词（如游戏简称「洲」）会被这条规则误杀——
                # 同音的另一个单字（「周」）没有共同汉字。但主播名/游戏名极少是单字，
                # 暂不处理；若将来用户反馈「单字简称没纠正」，根因在这里。
                # [P1 2026-10-24] 收紧为「首字必须相同」。
                # 原先只要求「共享任一汉字」，词表扩到 22 条（含干员/地图）后噪音爆炸：
                # 实测「深蓝往蓝鞋那边」一条就冒出「往蓝→深蓝」「蓝往→蓝斜」「蓝斜→离斜」三条误报，
                # 把真正要看的「蓝鞋→蓝斜」淹没。真实误识别几乎都是首字对、尾字错
                # （甲球/甲修、小鸡/小金、雪包/血包），首字不同基本是纯拼音巧合。
                if win[:1] != e["src"][:1]:
                    i += 1
                    continue
                hits.append({"pos": i, "original": win, "corrected": e["src"],
                             "kind": "suspect", "reason": "near"})
            i += 1
    return out, hits


def apply_glossary(rows: list[dict], glossary: Optional[list[dict]]) -> list[dict]:
    """对整份字幕做词表纠正（原地改 text，并记录 correction 供确认页撤销）。"""
    if not rows or not glossary:
        return rows or []
    for r in rows:
        txt = r.get("text") or ""
        # 所有行都留「纠正前原文」：验收时要把「原始 ASR 文本 / 纠正日志 / 最终字幕」
        # 按**同一次运行**对齐，不能跨轮次比较（ASR 非确定性，每次输出不同）。
        r.setdefault("original_text", txt)
        new, hits = correct_text(txt, glossary)
        if not hits:
            continue
        if new != txt:
            r["original_text"] = txt          # 原文留档：撤销/展示「已纠正」用
            r["text"] = new
        r["corrections"] = hits
    return rows
