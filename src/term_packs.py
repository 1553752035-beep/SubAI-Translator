# -*- coding: utf-8 -*-
"""五期：常见术语包（可直接启用）。

每个包包含两部分：
  fixes : ASR 后处理用的"错字→正确字"替换（解决识别错字）
  terms : 翻译用术语表"源词→目标词"（保证专有名词译法一致）

用户也可以只用其中一部分；采纳流程见前端"待确认纠错"。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class TermPack:
    id: str
    name: str
    desc: str
    fixes: tuple = field(default_factory=tuple)   # (错, 对)
    terms: tuple = field(default_factory=tuple)   # (源, 目标)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["fixes"] = [list(x) for x in self.fixes]
        d["terms"] = [list(x) for x in self.terms]
        d["fix_count"] = len(self.fixes)
        d["term_count"] = len(self.terms)
        return d


PACKS: tuple = (
    # ---------- 射击/撤离类游戏 ----------
    TermPack(
        "shooter", "射击・撤离类游戏", "三角洲行动 / 塔科夫 / 暗区这类常用说法",
        fixes=(
            ("撤离点", "撤离点"), ("车离点", "撤离点"), ("撒离点", "撤离点"),
            ("三角洲行动", "三角洲行动"), ("三角洲", "三角洲"), ("三角州", "三角洲"),
            ("弹匣", "弹匣"), ("弹夹", "弹匣"), ("换弹", "换弹"), ("换单", "换弹"),
            ("开镜", "开镜"), ("压枪", "压枪"), ("栓动", "栓动"), ("栓动步枪", "栓动步枪"),
            ("手雷", "手雷"), ("闪光弹", "闪光弹"), ("烟雾弹", "烟雾弹"), ("震撼弹", "震撼弹"),
            ("护甲", "护甲"), ("头盔", "头盔"), ("背包", "背包"), ("医疗包", "医疗包"),
            ("搜刮", "搜刮"), ("搜瓜", "搜刮"), ("舔包", "舔包"), ("大金", "大金"),
            ("boss", "首领"), ("刷怪", "刷怪"), ("复活点", "复活点"),
        ),
        terms=(("三角洲行动", "Delta Force"), ("撤离点", "extraction point"),
               ("大金", "high-value loot"), ("首领", "boss"), ("搜刮", "loot")),
    ),
    # ---------- 游戏通用 ----------
    TermPack(
        "gaming", "游戏通用", "FPS / 竞技游戏通用词",
        fixes=(
            ("残血", "残血"), ("满血", "满血"), ("秒杀", "秒杀"),
            ("爆头", "爆头"), ("爆头线", "爆头线"), ("点射", "点射"), ("扫射", "扫射"),
            ("蹲点", "蹲点"), ("绕后", "绕后"), ("打野", "打野"), ("支援", "支援"),
            ("经济", "经济"), ("翻盘", "翻盘"), ("团灭", "团灭"), ("开黑", "开黑"),
        ),
        terms=(("爆头", "headshot"), ("蹲点", "camp"), ("绕后", "flank"),
               ("翻盘", "comeback"), ("团灭", "team wipe"), ("开黑", "play together")),
    ),
    # ---------- 直播/网络口语 ----------
    TermPack(
        "streamer", "直播・网络口语", "做集锦常出现的主播口头语",
        fixes=(
            ("这波", "这波"), ("起飞", "起飞"), ("拉胯", "拉胯"),
            ("稳如老狗", "稳如老狗"), ("秀", "秀"), ("菜", "菜"),
            ("老铁", "老铁"), ("兄弟们", "兄弟们"), ("来活了", "来活了"),
        ),
        terms=(("这波", "this round"), ("起飞", "going great"), ("拉胯", "screwed up"),
               ("老铁", "guys"), ("兄弟们", "guys"), ("秀", "sick play")),
    ),
    # ---------- 字幕书写规范 ----------
    TermPack(
        "subtitle_style", "字幕书写规范", "数字/单位/标点统一，避免杂乱",
        fixes=(
            ("百分之", "百分之"), ("一千", "一千"), ("一万", "一万"),
        ),
        terms=(),
    ),
)

_BY_ID = {p.id: p for p in PACKS}


def list_packs() -> list:
    return [p.to_dict() for p in PACKS]


def get_pack(pack_id: str) -> dict:
    p = _BY_ID.get((pack_id or "").strip())
    return p.to_dict() if p else {}


def apply_fixes(text: str, pack_ids=None) -> tuple:
    """按选定的术语包做 ASR 错字纠正，返回 (修正后文本, 命中记录)。"""
    ids = list(pack_ids) if pack_ids else [p.id for p in PACKS]
    applied = []
    out = text
    for pid in ids:
        p = _BY_ID.get(pid)
        if not p:
            continue
        for wrong, right in p.fixes:
            if wrong and wrong != right and wrong in out:
                out = out.replace(wrong, right)
                applied.append({"pack": pid, "from": wrong, "to": right})
    return out, applied
