# -*- coding: utf-8 -*-
"""波形提取测试（src/waveform.py）。

为什么要测
----------
波形图的正确性无法靠肉眼在测试里判断，但它的几个**不变式**可以精确断言：
1. 桶数恒定（画布宽度固定时，波形不能忽长忽短）
2. 峰值落在 [-1, 1]（超出会导致画面画到画布外）
3. 静音段峰值接近 0，声音段明显非 0（否则波形图没有信息量）
4. 用 min/max 而非均值（均值会抹平枪声/爆破音这类短促声音）
"""
import array
import math
import os
import wave

import pytest

from src.waveform import extract_peaks, peaks_from_samples, silence_ratio


def _sine(n: int, amp: float = 0.8, freq: float = 440.0, sr: int = 16000):
    return [amp * math.sin(2 * math.pi * freq * i / sr) for i in range(n)]


def _write_wav(path: str, samples, sr: int = 16000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(
            int(max(-1.0, min(1.0, s)) * 32767).to_bytes(2, "little", signed=True)
            for s in samples
        ))


# ---------------- 纯计算：peaks_from_samples ----------------

def test_peaks_count_is_constant():
    """桶数必须恒等于请求值，不管输入多长。

    画布宽度固定时，桶数变化会让波形忽宽忽窄、和字幕块对不上。
    """
    for n in (0, 10, 1000, 12345):
        assert len(peaks_from_samples(_sine(n), buckets=200)) == 200


def test_peaks_in_range():
    peaks = peaks_from_samples(_sine(5000, amp=0.9), buckets=100)
    assert all(-1.0 <= lo <= hi <= 1.0 for lo, hi in peaks)


def test_peaks_use_min_max_not_mean():
    """必须保留极值 —— 均值会把单点尖峰抹成 0。

    构造：一个桶里大部分是 0，只有一个采样点是满幅。
    若实现用均值，该桶会接近 0（看不出这里有声音）；
    用 min/max 则能看到 ±1。
    """
    samples = [0.0] * 99 + [1.0]
    peaks = peaks_from_samples(samples, buckets=1)
    assert peaks[0] == [0.0, 1.0]


def test_peaks_silence_is_zero():
    peaks = peaks_from_samples([0.0] * 1000, buckets=50)
    assert all(lo == 0.0 and hi == 0.0 for lo, hi in peaks)


def test_peaks_empty_input():
    peaks = peaks_from_samples([], buckets=10)
    assert len(peaks) == 10
    assert all(p == [0.0, 0.0] for p in peaks)


def test_peaks_buckets_min_one():
    assert len(peaks_from_samples([0.5], buckets=0)) == 1


# ---------------- 静音占比 ----------------

def test_silence_ratio_all_quiet():
    assert silence_ratio([[0.0, 0.0]] * 100) == 1.0


def test_silence_ratio_all_loud():
    assert silence_ratio([[0.5, 0.6]] * 100) == 0.0


def test_silence_ratio_mixed():
    peaks = [[0.0, 0.001]] * 30 + [[0.5, 0.7]] * 70
    assert silence_ratio(peaks) == pytest.approx(0.3, abs=0.01)


def test_silence_ratio_empty():
    assert silence_ratio([]) == 0.0


# ---------------- 真实解码（需要 ffmpeg） ----------------

def test_extract_peaks_from_wav(tmp_path):
    """端到端：写 wav → 解码 → 出峰值。

    前半段正弦、后半段静音，断言静音占比约 50%。
    这同时验证了「ffmpeg 解码路径通」和「静音检测语义正确」。
    """
    p = str(tmp_path / "t.wav")
    samples = _sine(16000, amp=0.8) + [0.0] * 16000
    _write_wav(p, samples)

    d = extract_peaks(p, buckets=100)
    assert d["buckets"] == 100
    assert d["duration"] == pytest.approx(2.0, abs=0.1)
    assert len(d["peaks"]) == 100
    ratio = silence_ratio(d["peaks"])
    assert 0.35 < ratio < 0.65, "后半段静音应约占一半，实测 %.2f" % ratio


def test_extract_peaks_missing_file():
    with pytest.raises(FileNotFoundError):
        extract_peaks("C:/definitely_missing_audio.wav")


def test_extract_peaks_segment(tmp_path):
    """start/end 应只取一段，时长随之缩短。"""
    p = str(tmp_path / "t2.wav")
    _write_wav(p, _sine(48000, amp=0.7))    # 3 秒
    d = extract_peaks(p, buckets=50, start=0.0, end=1.0)
    assert d["duration"] == pytest.approx(1.0, abs=0.15)
