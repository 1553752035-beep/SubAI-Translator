# -*- coding: utf-8 -*-
"""幻觉段过滤：whisper 在低信噪比/量化下会凭空生成句子。

[P0 2026-10-24] 实测依据：同一视频 GPU(float16) 首行是「没事我有大血包」（真实），
CPU(int8) 首行变成「而且卡不了星标」——用户人耳复核确认根本没说过。
认不全只是少内容，编造是脏数据，所以给一个可选强过滤。
"""
from __future__ import annotations

from types import SimpleNamespace

from src.pipeline import _filter_hallucination


def _seg(text, nsp=0.1, cr=1.5):
    return SimpleNamespace(text=text, no_speech_prob=nsp, compression_ratio=cr)


def test_drops_high_no_speech():
    segs = [_seg("真实的一句话"), _seg("而且卡不了星标", nsp=0.75)]
    kept, dropped = _filter_hallucination(segs)
    assert len(kept) == 1
    assert kept[0].text == "真实的一句话"
    assert len(dropped) == 1
    assert dropped[0][0] == "而且卡不了星标"


def test_drops_high_compression_ratio():
    segs = [_seg("正常"), _seg("重复重复重复重复", cr=3.0)]
    kept, dropped = _filter_hallucination(segs)
    assert len(kept) == 1 and len(dropped) == 1


def test_keeps_empty_out_of_both_buckets():
    segs = [_seg("   ", nsp=0.9)]
    kept, dropped = _filter_hallucination(segs)
    assert kept == [] and dropped == [], "空文本既不算保留也不算「幻觉」"


def test_thresholds_are_configurable():
    segs = [_seg("边界句", nsp=0.7)]
    kept, dropped = _filter_hallucination(segs, nsp_th=0.8)
    assert len(kept) == 1, "阈值调到 0.8 时 0.7 不该被丢"
    kept2, dropped2 = _filter_hallucination(segs, nsp_th=0.5)
    assert len(dropped2) == 1


def test_default_is_permissive_enough_for_real_speech():
    # 真实语音常见 nsp 0.05~0.4、压缩比 1.0~2.0，默认阈值不应误伤
    segs = [_seg("快拿快拿我拿不下了", nsp=0.38, cr=1.9)]
    kept, dropped = _filter_hallucination(segs)
    assert len(kept) == 1 and dropped == []