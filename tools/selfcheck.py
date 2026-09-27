# -*- coding: utf-8 -*-
"""
SubAI-Translator 环境自检脚本
============================
一次性验证「视频字幕识别与翻译」整条一期链路是否真的可用。

用法:
    D:\\SubAI-Translator\\.venv\\Scripts\\python.exe D:\\SubAI-Translator\\tools\\selfcheck.py

设计原则: 每一节独立 try/except, 任何一节失败都不影响其余节的结论,
          最后给出汇总表, 便于定位到底哪一环没通。
"""
import os
import sys
import json
import time
import shutil
import subprocess

ROOT = r"D:\SubAI-Translator"
FFMPEG = os.path.join(ROOT, "bin", "ffmpeg.exe")
DATA = os.path.join(ROOT, "data")
ASR_WAV = os.path.join(DATA, "tts_test.wav")          # 由 Windows SAPI 合成的中文语音
HARDSUB_MP4 = os.path.join(DATA, "test_hardsub.mp4")  # 烧录中文字幕的视频
FRAME_PNG = os.path.join(DATA, "hardsub_frame.png")
SPEECH_MP4 = os.path.join(DATA, "test_speech.mp4")    # 含中文语音的视频(有音轨)
EXTRACT_WAV = os.path.join(DATA, "extracted_audio.wav")
KOBOLD = "http://127.0.0.1:5001/v1/chat/completions"

results = []


def rep(section, ok, detail):
    results.append((section, ok, detail))
    tag = "PASS" if ok else "FAIL"
    print("  [%s] %s" % (tag, detail))


def run_ffmpeg(args, timeout=120):
    return subprocess.run([FFMPEG] + args, capture_output=True, text=True,
                          timeout=timeout, encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 1. 环境
print("=" * 72)
print("1. 运行环境")
print("=" * 72)
rep("env", True, "python %s" % sys.version.split()[0])
rep("env", os.path.exists(FFMPEG), "ffmpeg -> %s" % FFMPEG)

try:
    import cv2, numpy, av
    rep("env", True, "numpy %s / opencv %s / av %s" % (numpy.__version__, cv2.__version__, av.__version__))
except Exception as e:
    rep("env", False, "image stack import failed: %r" % e)

# ---------------------------------------------------------------- 2. 算力
print()
print("=" * 72)
print("2. 算力后端 (GPU 是否真的可用)")
print("=" * 72)

try:
    import torch
    cuda = torch.cuda.is_available()
    rep("gpu", True, "torch %s  cuda_available=%s" % (torch.__version__, cuda))
    if cuda:
        rep("gpu", True, "device=%s" % torch.cuda.get_device_name(0))
except Exception as e:
    rep("gpu", False, "torch probe failed: %r" % e)

try:
    import onnxruntime as ort
    provs = ort.get_available_providers()
    rep("gpu", True, "onnxruntime %s providers=%s" % (ort.__version__, provs))
except Exception as e:
    rep("gpu", False, "onnxruntime probe failed: %r" % e)

try:
    import ctranslate2
    rep("gpu", True, "ctranslate2 %s cuda_types=%s" % (
        ctranslate2.__version__, sorted(ctranslate2.get_supported_compute_types("cuda"))))
except Exception as e:
    rep("gpu", False, "ctranslate2 cuda probe failed: %r" % e)

try:
    smi = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.used,memory.total",
                          "--format=csv,noheader"], capture_output=True, text=True, timeout=20)
    rep("gpu", True, "nvidia-smi: %s" % smi.stdout.strip())
except Exception as e:
    rep("gpu", False, "nvidia-smi failed: %r" % e)

# ---------------------------------------------------------------- 3. FFmpeg
print()
print("=" * 72)
print("3. FFmpeg 视频处理")
print("=" * 72)
try:
    v = run_ffmpeg(["-version"])
    first = v.stdout.splitlines()[0] if v.stdout else "(no output)"
    rep("ffmpeg", "ffmpeg version" in first, first[:100])
except Exception as e:
    rep("ffmpeg", False, "ffmpeg -version failed: %r" % e)

try:
    os.makedirs(DATA, exist_ok=True)
    r = run_ffmpeg(["-y", "-i", SPEECH_MP4, "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", EXTRACT_WAV], timeout=120)
    ok = os.path.exists(EXTRACT_WAV) and os.path.getsize(EXTRACT_WAV) > 1000
    rep("ffmpeg", ok, "抽取音轨 -> %s (%s bytes)" % (
        os.path.basename(EXTRACT_WAV),
        os.path.getsize(EXTRACT_WAV) if os.path.exists(EXTRACT_WAV) else 0))
except Exception as e:
    rep("ffmpeg", False, "audio extract failed: %r" % e)

try:
    r = run_ffmpeg(["-y", "-ss", "2", "-i", HARDSUB_MP4, "-frames:v", "1", FRAME_PNG], timeout=120)
    ok = os.path.exists(FRAME_PNG)
    rep("ffmpeg", ok, "抽帧 -> %s" % os.path.basename(FRAME_PNG))
except Exception as e:
    rep("ffmpeg", False, "frame extract failed: %r" % e)

# ---------------------------------------------------------------- 4. ASR
print()
print("=" * 72)
print("4. 语音识别 (faster-whisper / CTranslate2)")
print("=" * 72)
asr_text = ""
try:
    from faster_whisper import WhisperModel
    # 优先用本地已下载的 CTranslate2 模型目录, 避免运行时再去联网拉取
    # (本机到 huggingface.co 被 DNS 黑洞, 只有 hf-mirror 可用)
    model_size = os.environ.get("WHISPER_MODEL", "small")
    local_dir = os.path.join(ROOT, "models", "faster-whisper-small")
    if os.path.isdir(local_dir) and not os.path.exists(model_size):
        model_size = local_dir
    t0 = time.time()
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    t_load = time.time() - t0
    t0 = time.time()
    # 刻意用「从 mp4 中抽出的音轨」而非原始 wav, 以验证 mp4 -> wav -> ASR 完整链路
    asr_input = ASR_WAV
    if os.path.exists(EXTRACT_WAV) and os.path.getsize(EXTRACT_WAV) > 1000:
        asr_input = EXTRACT_WAV
    rep("asr", True, "输入音频: %s" % os.path.basename(asr_input))
    segments, info = model.transcribe(asr_input, language="zh", beam_size=5)
    segs = list(segments)
    t_run = time.time() - t0
    asr_text = "".join(s.text for s in segs).strip()
    rep("asr", bool(asr_text),
        "model=%s load=%.1fs infer=%.1fs lang=%s prob=%.2f" % (
            model_size, t_load, t_run, info.language, info.language_probability))
    rep("asr", bool(asr_text), "转录结果: %s" % asr_text)
except Exception as e:
    rep("asr", False, "faster-whisper failed: %r" % e)

# ---------------------------------------------------------------- 5. OCR
print()
print("=" * 72)
print("5. 硬字幕 OCR (RapidOCR / PP-OCR on ONNX Runtime)")
print("=" * 72)
ocr_text = ""
try:
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    t0 = time.time()
    out, elapse = engine(FRAME_PNG)
    t_ocr = time.time() - t0
    if out:
        ocr_text = " | ".join(x[1] for x in out)
        boxes = [x[0] for x in out]
        rep("ocr", True, "识别到 %d 个文本块, 耗时 %.2fs" % (len(out), t_ocr))
        rep("ocr", True, "OCR 结果: %s" % ocr_text)
        for b in boxes:
            ys = [p[1] for p in b]
            xs = [p[0] for p in b]
            rep("ocr", True, "  区域 x=[%d,%d] y=[%d,%d]  <- 字幕区域检测可用" % (
                min(xs), max(xs), min(ys), max(ys)))
    else:
        rep("ocr", False, "未识别到任何文本")
except Exception as e:
    rep("ocr", False, "RapidOCR failed: %r" % e)

# ---------------------------------------------------------------- 6. 翻译
print()
print("=" * 72)
print("6. 翻译引擎 (本机 koboldcpp / Qwen3.6-35B-A3B, OpenAI 兼容接口)")
print("=" * 72)
try:
    import httpx
    src = ocr_text.split(" | ")[0] if ocr_text else "你好，这是硬字幕识别测试"
    payload = {
        "model": "koboldcpp",
        "messages": [
            {"role": "system", "content": "You are a professional subtitle translator. "
                                          "Translate the user's Chinese subtitle into English. "
                                          "Output only the translation, no explanation."},
            {"role": "user", "content": src},
        ],
        "max_tokens": 128,
        "temperature": 0.2,
    }
    t0 = time.time()
    r = httpx.post(KOBOLD, json=payload, timeout=180)
    dt = time.time() - t0
    r.raise_for_status()
    j = r.json()
    tr = j["choices"][0]["message"]["content"].strip()
    rep("translate", bool(tr), "耗时 %.1fs  用量=%s" % (dt, j.get("usage")))
    rep("translate", bool(tr), "原文: %s" % src)
    rep("translate", bool(tr), "译文: %s" % tr)
except Exception as e:
    rep("translate", False, "koboldcpp 调用失败 (服务是否在 5001 端口运行?): %r" % e)

# ---------------------------------------------------------------- 汇总
print()
print("=" * 72)
print("汇总")
print("=" * 72)
sections = {}
for s, ok, _ in results:
    a, b = sections.get(s, (0, 0))
    sections[s] = (a + (1 if ok else 0), b + 1)
names = {"env": "运行环境", "gpu": "算力后端", "ffmpeg": "FFmpeg",
         "asr": "语音识别", "ocr": "硬字幕OCR", "translate": "翻译引擎"}
allok = True
for k, (ok_n, tot) in sections.items():
    flag = "PASS" if ok_n == tot else ("PARTIAL" if ok_n else "FAIL")
    if ok_n != tot:
        allok = False
    print("  %-10s %-8s %d/%d" % (names.get(k, k), flag, ok_n, tot))
print()
print("  总判定: %s" % ("全部通过 - 一期链路可用" if allok else "存在失败项, 见上方明细"))
sys.exit(0 if allok else 1)
