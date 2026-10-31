# -*- coding: utf-8 -*-
"""波形峰值提取（纯计算 + 可选 ffmpeg 解码）。

为什么需要
----------
校对台有视频、有字幕行、有跳转，但用户看不出「这句话到底在哪一段声音上」。
波形图能把字幕行和真实音频对齐：一眼看出这行字幕是不是切早了/切晚了，
或者某段有声音却没字幕（配合已有的未覆盖告警，直接定位漏句位置）。

设计要点
----------
1. **只返回峰值，不返回原始采样**。一段 10 分钟视频按 44.1kHz 有 2600 万采样，
   传前端必然卡死。按像素桶取 min/max 后，1000 像素只要 2000 个数。
2. **峰值用 min/max 而不是均值**。均值会把短促的声音（枪声、爆破音）抹平，
   看不出「这里有声音」。min/max 是音频波形的标准画法。
3. **采样率降级**。用 8000Hz 单声道解码就够画波形 —— 省解码时间，
   波形形状不受影响（峰值包络与采样率无关）。
"""
from __future__ import annotations

import array
import math
import os
import subprocess
import tempfile
from typing import Optional


def _ffmpeg() -> str:
    """取 ffmpeg 路径。

    用 config.ffmpeg 属性（打包后自动指向 bin/ffmpeg.exe，
    源码运行时回落 PATH 里的 ffmpeg）—— 这是项目内的统一入口，
    不要自己拼路径或 import pipeline 里的其他名字。
    """
    from src.config import config
    return config.ffmpeg


def extract_peaks(media: str, buckets: int = 1000,
                  sample_rate: int = 8000,
                  start: Optional[float] = None,
                  end: Optional[float] = None,
                  timeout: int = 300) -> dict:
    """解码媒体并算出每桶的 (min, max) 峰值。

    返回
    ----
    结构：{"buckets": int, "duration": float, "peaks": [[min,max], ...]}

    peaks 的值域归一化到 [-1, 1]，前端直接按画布高度缩放即可。

    参数
    ----
    buckets : 桶数，通常等于画布像素宽度
    start/end : 只取一段（可选），用于放大局部
    """
    if not os.path.isfile(media):
        raise FileNotFoundError("媒体不存在: %s" % media)
    b = max(1, int(buckets))

    tmp = tempfile.NamedTemporaryFile(suffix=".pcm", delete=False)
    tmp.close()
    cmd = [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
    if start is not None:
        cmd += ["-ss", str(float(start))]
    cmd += ["-i", media]
    if end is not None:
        dur = float(end) - float(start or 0)
        if dur > 0:
            cmd += ["-t", "%.3f" % dur]
    # s16le 单声道：每采样 2 字节，解析最快
    cmd += ["-vn", "-ac", "1", "-ar", str(int(sample_rate)),
            "-f", "s16le", "-acodec", "pcm_s16le", tmp.name]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if r.returncode != 0:
            raise RuntimeError("音频解码失败: %s" % (r.stderr or b"").decode("utf-8", "replace")[:300])
        raw = open(tmp.name, "rb").read()
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass

    # 用 array 解析比 struct.unpack 逐项快一个量级
    samples = array.array("h")
    usable = len(raw) - (len(raw) % 2)
    samples.frombytes(raw[:usable])
    n = len(samples)
    if n == 0:
        return {"buckets": b, "duration": 0.0, "peaks": [[0.0, 0.0] for _ in range(b)],
                "sample_rate": sample_rate}

    per = max(1, n // b)
    peaks = []
    scale = 1.0 / 32768.0
    for i in range(b):
        lo = i * per
        hi = n if i == b - 1 else min(n, lo + per)
        if lo >= hi:
            peaks.append([0.0, 0.0])
            continue
        chunk = samples[lo:hi]
        peaks.append([round(min(chunk) * scale, 4), round(max(chunk) * scale, 4)])

    return {
        "buckets": len(peaks),
        "duration": round(n / float(sample_rate), 3),
        "peaks": peaks,
        "sample_rate": sample_rate,
    }


def peaks_from_samples(samples, buckets: int = 1000) -> list:
    """直接从采样序列算峰值（测试友好，不需要 ffmpeg）。"""
    b = max(1, int(buckets))
    n = len(samples)
    if n == 0:
        return [[0.0, 0.0] for _ in range(b)]
    per = max(1, n // b)
    out = []
    for i in range(b):
        lo = i * per
        hi = n if i == b - 1 else min(n, lo + per)
        if lo >= hi:
            out.append([0.0, 0.0])
            continue
        chunk = samples[lo:hi]
        out.append([round(min(chunk), 4), round(max(chunk), 4)])
    return out


def silence_ratio(peaks: list, threshold: float = 0.02) -> float:
    """估算静音占比（|峰值| 全部低于阈值的桶的比例）。

    用途：和「未覆盖区间」交叉验证。静音占比很高 + 未覆盖很长，
    说明那段本来就没声音，不是漏识别。
    """
    if not peaks:
        return 0.0
    quiet = sum(1 for lo, hi in peaks if max(abs(lo), abs(hi)) < threshold)
    return round(quiet / float(len(peaks)), 4)
