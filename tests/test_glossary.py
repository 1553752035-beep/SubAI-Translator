# -*- coding: utf-8 -*-
"""五期 P2：专有名词词表 + 同音纠正（四条硬约束的回归测试）"""
import pytest
from src.glossary import correct_text, sound_distance, py_groups, apply_glossary


GL = [{"src": "橘长", "type": "person"}]


def test_homophone_auto_corrected():
    """拼音全等 → 自动纠正，并改的是原文。"""
    out, hits = correct_text("局长你看这里", GL)
    assert out == "橘长你看这里"
    assert hits[0]["kind"] == "auto" and hits[0]["reason"] == "homo"


def test_near_sound_never_auto():
    """近音（距离 1）只能标记 suspect，绝不自动改 —— 汉字距离会让「队长」被误纠成「橘长」。

    [P1 2026-10-24] 判定已收紧为「首字必须相同」，所以这里改用首字相同的近音例：
    「甲秋」(jia qiu) 与词表词「甲修」(jia xiu) 距离 1、首字同为「甲」→ 只标记不改。
    """
    gl = [{"src": "甲修", "type": "item"}]
    out, hits = correct_text("甲秋在那边", gl)
    assert out == "甲秋在那边", "近音被自动改了：甲秋 -> %s" % out
    assert hits and hits[0]["kind"] == "suspect" and hits[0]["reason"] == "near"


def test_near_sound_requires_same_first_char():
    """首字不同的近音一律不标记 —— 词表扩容到 22 条后，仅靠「共享任一汉字」会噪音爆炸。

    实测：「深蓝往蓝鞋那边」一条就冒出「往蓝→深蓝」「蓝往→蓝斜」「蓝斜→离斜」三条误报，
    把真正要看的「蓝鞋→蓝斜」淹没。真实的误识别几乎都是首字对、尾字错。
    """
    for src in ("队长快跑", "区长说两句"):
        out, hits = correct_text(src, GL)
        assert out == src
        assert hits == [], "首字不同不该标记：%s -> %s" % (src, hits)


def test_pinyin_distance_blocks_false_positive():
    """拼音距离：队长(dui) 与 橘长(ju) 距离 1；但同音字之间距离 0。"""
    assert sound_distance(py_groups("队长"), py_groups("橘长")) == 1
    assert sound_distance(py_groups("局长"), py_groups("橘长")) == 0
    assert sound_distance(py_groups("传送门"), py_groups("橘长")) > 1


def test_conflict_only_flags():
    """词表里同时有同音的「橘长」「局长」时，无从判断 → 只标记 conflict，不自动改。"""
    g = [{"src": "橘长", "type": "person"}, {"src": "局长", "type": "role"}]
    out, hits = correct_text("局长你看这里", g)
    assert out == "局长你看这里"
    assert any(h["reason"] == "conflict" and h["kind"] == "suspect" for h in hits)


def test_already_correct_untouched():
    out, hits = correct_text("橘长牛逼", GL)
    assert out == "橘长牛逼" and hits == []


def test_apply_glossary_keeps_original():
    """apply_glossary 改原文，同时把原始文本留在 original_text（撤销/展示用）。"""
    rows = [{"text": "局长你看这里"}, {"text": "没关系"}]
    out = apply_glossary(rows, GL)
    assert out[0]["text"] == "橘长你看这里"
    assert out[0]["original_text"] == "局长你看这里"
    # 所有行都留原文（验收要对齐「原始 ASR 文本」，不只是被纠正的行）
    assert out[1]["original_text"] == "没关系"


def test_glossary_empty_noop():
    rows = [{"text": "局长你看这里"}]
    assert apply_glossary(rows, None)[0]["text"] == "局长你看这里"
    assert apply_glossary(rows, [])[0]["text"] == "局长你看这里"


def test_cache_key_includes_glossary():
    """词表必须进缓存 key：否则「填了词表」会静默命中旧缓存。"""
    from src.pipeline import _cache_key_of
    ctx = {"key": "abc123"}
    assert _cache_key_of(ctx, "g1") != _cache_key_of(ctx, "g2"), "词表不同但 key 相同"
    assert _cache_key_of(ctx, "") != _cache_key_of(ctx, "g1"), "词表有无但 key 相同"
    assert _cache_key_of(ctx, "g1") == _cache_key_of({"key": "abc123"}, "g1")
    assert _cache_key_of(None, "g1") != _cache_key_of(None, ""), "无摘要时词表也要进 key"
