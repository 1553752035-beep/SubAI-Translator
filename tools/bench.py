# -*- coding: utf-8 -*-
"""
SubAI Translator 环境能力基准
=============================
回答一个自检回答不了的问题：**这套环境到底能跑多快、哪一环是瓶颈？**

自检（tools/selfcheck.py）只回答「通不通」，本脚本回答「够不够用」，
并顺手把 GPU 的可达性用**实测**给出定论（而不是靠推断）。

用法：
    python tools/bench.py            # 在源码目录下，用当前环境的 Python

每节独立 try/except，任何一节失败都不影响其余节。
"""
import os
import re
import sys
import time
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = os.path.join(ROOT, "bin", "ffmpeg.exe")
DATA = os.path.join(ROOT, "data")
MODEL_DIR = os.path.join(ROOT, "models", "faster-whisper-small")
ASR_WAV = os.path.join(DATA, "tts_test.wav")
HARDSUB_MP4 = os.path.join(DATA, "test_hardsub.mp4")
KOBOLD = "http://127.0.0.1:5001/v1/chat/completions"


def head(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


# ---------------------------------------------------------------- A. GPU 可达性
head("A. GPU 可达性（当前 koboldcpp 已占用大部分显存）")
gpu_free = None
try:
    out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total,memory.free",
                          "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
    line = out.stdout.strip()
    print("  nvidia-smi: %s" % line)
    m = re.findall(r"(\d+)\s*MiB", line)
    if len(m) >= 3:
        gpu_free = int(m[2])
        print("  -> 空闲显存 %d MiB" % gpu_free)
except Exception as e:
    print("  nvidia-smi 失败: %r" % e)

try:
    import torch
    print("  torch %s  cuda_available=%s" % (torch.__version__, torch.cuda.is_available()))
except Exception as e:
    print("  torch 探测失败: %r" % e)

try:
    import onnxruntime as ort
    provs = ort.get_available_providers()
    print("  onnxruntime %s providers=%s" % (ort.__version__, provs))
    print("  -> OCR 可用的加速后端: %s" % (
        "CUDA" if "CUDAExecutionProvider" in provs else "仅 CPU（未装 onnxruntime-gpu）"))
except Exception as e:
    print("  onnxruntime 探测失败: %r" % e)

try:
    import ctranslate2
    print("  ctranslate2 %s 编译支持的 cuda 计算类型: %s"
          % (ctranslate2.__version__, sorted(ctranslate2.get_supported_compute_types("cuda"))))
except Exception as e:
    print("  ctranslate2 探测失败: %r" % e)

# ------------------------------------------------- B. Whisper 上 GPU 的实测结论
head("B. faster-whisper 能否直接跑 GPU（实测，不推断）")
for dev, ct in (("cuda", "float16"), ("cpu", "int8")):
    try:
        from faster_whisper import WhisperModel
        t0 = time.time()
        WhisperModel(MODEL_DIR, device=dev, compute_type=ct)
        print("  device=%-5s compute=%-8s -> 可用（加载 %.2fs）" % (dev, ct, time.time() - t0))
    except Exception as e:
        msg = re.sub(r"\s+", " ", str(e))[:220]
        print("  device=%-5s compute=%-8s -> 不可用: %s: %s"
              % (dev, ct, type(e).__name__, msg))

# ---------------------------------------------------------------- C. ASR 吞吐
head("C. 语音识别吞吐（CPU / int8 / beam=5）")
try:
    from faster_whisper import WhisperModel
    dur = None
    pr = subprocess.run([FFMPEG, "-hide_banner", "-i", ASR_WAV], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", pr.stderr or "")
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))

    t0 = time.time()
    model = WhisperModel(MODEL_DIR, device="cpu", compute_type="int8", cpu_threads=8)
    t_load = time.time() - t0
    t0 = time.time()
    segments, info = model.transcribe(ASR_WAV, language="zh", beam_size=5,
                                      vad_filter=True, word_timestamps=True)
    text = "".join(s.text for s in segments).strip()
    t_infer = time.time() - t0
    print("  模型加载        %.2fs" % t_load)
    print("  推理耗时        %.2fs" % t_infer)
    if dur:
        print("  音频时长        %.2fs" % dur)
        print("  实时率 RTF      %.3f  （%.1fx 实时，越小越快）" % (t_infer / dur, dur / t_infer))
        print("  => 10 分钟视频约需 %.1f 分钟" % (t_infer / dur * 10))
    print("  转录: %s" % text)

    t0 = time.time()
    segs1, _ = model.transcribe(ASR_WAV, language="zh", beam_size=1)
    list(segs1)                       # 生成器惰性求值，必须消费掉才计时有效
    t_beam1 = time.time() - t0
    print("  beam=1 再推理      %.2fs（对比 beam=5 的 %.2fs，模型已驻留）"
          % (t_beam1, t_infer))
except Exception as e:
    print("  ASR 基准失败: %r" % e)

# ---------------------------------------------------------------- D. OCR 吞吐
head("D. 硬字幕 OCR 吞吐（CPU / ONNX Runtime / 1280x720）")
try:
    import cv2
    from rapidocr_onnxruntime import RapidOCR

    t0 = time.time()
    engine = RapidOCR()
    print("  引擎加载        %.2fs" % (time.time() - t0))

    cap = cv2.VideoCapture(HARDSUB_MP4)
    frames = []
    while len(frames) < 10:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()

    t0 = time.time()
    n = 0
    for f in frames:
        engine(f)
        n += 1
    dt = time.time() - t0
    if n:
        print("  单帧耗时        %.3fs（%d 帧 / %.2fs）" % (dt / n, n, dt))
        print("  => 2fps 抽帧时，每 1 分钟视频约需 %.1fs 纯 OCR" % (60 * 2 * dt / n))
        print("  => 10 分钟视频约需 %.1f 分钟纯 OCR" % (600 * 2 * dt / n / 60))
except Exception as e:
    print("  OCR 基准失败: %r" % e)

# ---------------------------------------------------------------- E. 翻译吞吐
head("E. 翻译吞吐（本机 koboldcpp, OpenAI 兼容接口, 批量 10 行/请求）")
try:
    import httpx

    lines = ["第%d句：今天的天气非常好，适合出去散步。" % (i + 1) for i in range(10)]
    block = "\n".join("%d. %s" % (i + 1, t) for i, t in enumerate(lines))
    prompt = ("Translate each numbered Chinese subtitle line into English. "
              "Keep the same numbering, one line per input line, output nothing else.\n\n" + block)
    payload = {
        "model": "koboldcpp",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512, "temperature": 0.2,
    }
    t0 = time.time()
    r = httpx.post(KOBOLD, json=payload, timeout=300)
    dt = time.time() - t0
    r.raise_for_status()
    j = r.json()
    usage = j.get("usage") or {}
    out = j["choices"][0]["message"]["content"].strip()
    comp = usage.get("completion_tokens") or 0
    print("  HTTP %d   总耗时 %.2fs   用量=%s" % (r.status_code, dt, usage))
    if comp and dt:
        print("  解码吞吐        %.1f tok/s（含预填充）" % (comp / dt))
    print("  => 10 行字幕一次请求 %.1fs，约 %.2fs/行" % (dt, dt / len(lines)))
    print("  译文首行: %s" % out.splitlines()[0][:120])
except Exception as e:
    print("  翻译基准失败（koboldcpp 是否在 5001 端口？）: %r" % e)

print()
print("=" * 72)
print("基准结束")
print("=" * 72)
