# -*- coding: utf-8 -*-
"""语音覆盖率 / 未覆盖区间（漏句提示）测试。

背景：这段逻辑原本只把结果写进日志，用户看不到。同类项目 SmartSub 会把
「这段有人说话但没识别出内容」提示到界面。我们是「算法早有、数据没露面」——
本组测试固定住三件事：口径正确、边界安全、warn 判据不误报。
"""
import pytest

from src.pipeline import compute_coverage, probe_duration, COVERAGE_WARN_PCT


def R(start, end, text="x"):
    return {"start": start, "end": end, "text": text}


# ---------------- 基本口径 ----------------

def test_coverage_basic():
    """覆盖时长 / 百分比 / 空白 三个基础量必须自洽。"""
    c = compute_coverage([R(0, 10), R(10, 20)], 40)
    assert c["duration"] == 40
    assert c["covered"] == 20
    assert c["coverage_pct"] == 50.0
    assert c["blank"] == 20
    assert c["covered"] + c["blank"] == c["duration"]


def test_coverage_zero_duration_returns_empty():
    """duration<=0 时返回空 dict —— 调用方据此跳过展示，不能除零。"""
    assert compute_coverage([R(0, 10)], 0) == {}
    assert compute_coverage([R(0, 10)], -5) == {}
    assert compute_coverage([R(0, 10)], None) == {}


def test_coverage_empty_rows():
    """没有字幕行时整体算作空白。"""
    c = compute_coverage([], 30)
    assert c["covered"] == 0
    assert c["coverage_pct"] == 0.0
    assert len(c["gaps"]) == 1
    assert c["gaps"][0]["start"] == 0
    assert c["gaps"][0]["end"] == 30


# ---------------- 空洞检测 ----------------

def test_gap_between_rows():
    """两行之间的长静默算一处空洞。"""
    c = compute_coverage([R(0, 10), R(20, 30)], 30)
    assert len(c["gaps"]) == 1
    g = c["gaps"][0]
    assert (g["start"], g["end"], g["sec"]) == (10, 20, 10)


def test_gap_below_threshold_ignored():
    """短于阈值的静默不算空洞（正常换气/停顿）。"""
    c = compute_coverage([R(0, 10), R(11, 20)], 20)
    assert c["gaps"] == []


def test_gap_at_tail():
    """尾部静默算空洞（最容易被忽略的一种）。"""
    c = compute_coverage([R(0, 10)], 40)
    assert len(c["gaps"]) == 1
    assert c["gaps"][0]["start"] == 10
    assert c["gaps"][0]["end"] == 40


def test_gap_threshold_configurable():
    """阈值可配置：同一份数据，阈值放小后能检出更多空洞。"""
    rows = [R(0, 10), R(12, 20), R(22, 30)]
    assert len(compute_coverage(rows, 30, gap_min_sec=3)["gaps"]) == 0
    assert len(compute_coverage(rows, 30, gap_min_sec=1.5)["gaps"]) == 2


def test_overlapping_rows_do_not_double_count():
    """重叠行不该让 covered 超过 duration，也不该产生负空洞。"""
    c = compute_coverage([R(0, 15), R(5, 20)], 20)
    assert c["gaps"] == []
    assert c["coverage_pct"] <= 100.0


# ---------------- warn 判据 ----------------

def test_warn_when_coverage_low():
    """覆盖率低于阈值 → warn。"""
    c = compute_coverage([R(0, 10)], 100)   # 10%
    assert c["coverage_pct"] < COVERAGE_WARN_PCT
    assert c["warn"] is True


def test_warn_when_many_gaps():
    """覆盖率够高但空洞过多 → 也要 warn（密集断开同样影响观感）。"""
    rows = [R(i * 10, i * 10 + 8) for i in range(4)]  # 8/10 覆盖 = 80%
    c = compute_coverage(rows, 40, gap_min_sec=2)
    assert c["coverage_pct"] >= COVERAGE_WARN_PCT
    assert len(c["gaps"]) >= 3
    assert c["warn"] is True


def test_no_warn_when_healthy():
    """覆盖率高、空洞少 → 不打扰用户。"""
    rows = [R(i * 10, i * 10 + 9.5) for i in range(4)]
    c = compute_coverage(rows, 40)
    assert c["warn"] is False


# ---------------- 时长探测 ----------------

def test_probe_duration_missing_file_returns_zero():
    """文件不存在时返回 0，不能抛异常（否则整条任务因统计挂掉）。"""
    assert probe_duration("Z:/definitely/not/here.wav") == 0.0


def test_probe_duration_real_wav(monkeypatch):
    """有音频时能取到接近真实的时长（绿色版只有 ffmpeg.exe，靠 Duration 行回退）。"""
    import os
    wav = os.getenv("SUBAI_TEST_WAV")
    if not wav or not os.path.isfile(wav):
        pytest.skip("需要 SUBAI_TEST_WAV")
    d = probe_duration(wav)
    assert d > 0, "时长探测失败：ffprobe 与 ffmpeg 回退都没拿到 Duration"
