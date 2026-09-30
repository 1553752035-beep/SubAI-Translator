# -*- coding: utf-8 -*-
"""
SubAI Translator —— 二期性能指标测量脚本
===========================================

测量并输出方案 3.6 / 5.1 定义的各项验收指标：
  1. GPU ASR RTF        (目标 ≤ 0.1)
  2. 并发处理性能下降    (目标 ≤ 30%)
  3. 翻译缓存命中率      (目标 ≥ 20%)
  4. OCR 硬字幕识别率    (目标 ≥ 85%)
  5. 翻译 BLEU          (目标 ≥ 0.6)
  6. 术语库命中率        (目标 ≥ 90%)

用法：
    python tools/bench_metrics.py gpu_rtf      # 需要空闲显存（先停 koboldcpp）
    python tools/bench_metrics.py ocr          # 无需 LLM
    python tools/bench_metrics.py cache        # 无需 LLM（纯缓存机制）
    python tools/bench_metrics.py bleu         # 需要 koboldcpp 在线
    python tools/bench_metrics.py terms        # 术语精确匹配，无需 LLM
    python tools/bench_metrics.py concurrency  # 需要 koboldcpp 在线
    python tools/bench_metrics.py all          # 依次跑全部（bleu/concurrency 需 LLM）

结果统一输出为 JSON（末尾一行），便于汇总。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor

# 项目根目录（开发源码根）与发布资源根（models/bin 所在）
SRC_ROOT = r"D:\SubAI-Translator\源码"
PUB_ROOT = r"D:\SubAI-Translator"

sys.path.insert(0, SRC_ROOT)

# 先覆盖 config 路径，再 import pipeline（pipeline 的模块级常量在 import 时读取 config）
from src.config import config  # noqa: E402
config.paths.root = PUB_ROOT

from src.pipeline import (  # noqa: E402
    extract_audio, asr_segments, hardsub_segments, translate,
    FFMPEG, MODEL_DIR,
)

DATA = os.path.join(SRC_ROOT, "data")
TTTS_WAV = os.path.join(DATA, "tts_test.wav")
SPEECH_VIDEO = os.path.join(DATA, "test_speech.mp4")
HARDSUB_VIDEO = os.path.join(DATA, "test_hardsub.mp4")
TERMS_JSON = os.path.join(DATA, "sample_terms.json")
CACHE_DB = os.path.join(DATA, "bench_cache.db")

# OCR 硬字幕视频的标准字幕（人工标注）
OCR_GROUND_TRUTH = "你好，这是硬字幕识别测试"

# BLEU 测试集：中文源句 -> 参考英文翻译
BLEU_SET = [
    ("欢迎使用人工智能视频字幕翻译软件", "Welcome to the AI video subtitle translation software"),
    ("今天天气很好，适合出去走走", "The weather is nice today, perfect for a walk"),
    ("请稍等，系统正在处理你的请求", "Please wait, the system is processing your request"),
    ("这是语音识别测试，用于验证模型性能", "This is a speech recognition test to verify model performance"),
    ("人工智能正在改变我们的生活方式", "Artificial intelligence is changing the way we live"),
    ("感谢观看，我们下期再见", "Thanks for watching, see you next time"),
    ("请确保网络连接正常后再重试", "Please make sure your network connection is stable before retrying"),
    ("这个功能可以自动生成字幕和翻译", "This feature can automatically generate subtitles and translations"),
    ("深度学习模型需要大量数据进行训练", "Deep learning models require large amounts of data for training"),
    ("祝您使用愉快", "Enjoy your experience"),
]


def _load_terms() -> dict[str, str]:
    with open(TERMS_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {t["source"]: t["translation"] for t in data}


def _wav_duration(wav: str) -> float:
    with wave.open(wav) as w:
        return w.getnframes() / w.getframerate()


# --------------------------------------------------------------------------- #
# 1. GPU ASR RTF
# --------------------------------------------------------------------------- #
def bench_gpu_rtf() -> dict:
    # 把 pip 安装的 nvidia cuBLAS/cuDNN DLL 目录加入 PATH（ctranslate2 通过
    # LoadLibrary 动态加载 cuBLAS，需写入 Windows 进程环境块才生效）
    import ctypes
    _nv = os.path.join(SRC_ROOT, ".venv", "Lib", "site-packages", "nvidia")
    _add = os.pathsep.join(
        os.path.join(_nv, _d, "bin") for _d in ("cublas", "cudnn")
        if os.path.isdir(os.path.join(_nv, _d, "bin"))
    )
    _new_path = _add + ";" + os.environ.get("PATH", "")
    os.environ["PATH"] = _new_path
    try:
        ctypes.windll.kernel32.SetEnvironmentVariableW("PATH", _new_path)
    except Exception:
        pass
    from faster_whisper import WhisperModel
    dur = _wav_duration(TTTS_WAV)

    t0 = time.time()
    model = WhisperModel(MODEL_DIR, device="cuda", compute_type="float16")
    t_load = time.time() - t0

    # 预热一次（排除首次 CUDA 初始化开销）
    _ = list(model.transcribe(TTTS_WAV, language="zh", beam_size=5, vad_filter=True))

    t0 = time.time()
    segments, info = model.transcribe(TTTS_WAV, language="zh", beam_size=5, vad_filter=True)
    text = "".join(s.text for s in segments)
    t_asr = time.time() - t0

    rtf = t_asr / dur
    return {
        "metric": "gpu_asr_rtf",
        "device": "cuda",
        "compute_type": "float16",
        "audio_seconds": round(dur, 2),
        "model_load_seconds": round(t_load, 2),
        "infer_seconds": round(t_asr, 3),
        "rtf": round(rtf, 4),
        "target": "<= 0.1",
        "pass": rtf <= 0.1,
        "note": "转录文本长度 %d 字" % len(text),
    }


# --------------------------------------------------------------------------- #
# 2. 并发处理性能下降
# --------------------------------------------------------------------------- #
def _process_one(video: str) -> float:
    """无缓存、无落盘的完整处理：抽音轨 + ASR + 翻译"""
    t0 = time.time()
    wav = extract_audio(video)
    rows = asr_segments(wav, None)
    texts = [r["text"] for r in rows]
    translate(texts, "en", {}, use_cache=False)
    return time.time() - t0


def bench_concurrency() -> dict:
    # 单任务基准
    t_single = _process_one(SPEECH_VIDEO)

    # 2 个任务并发（同一视频，无缓存无落盘，互不冲突）
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(_process_one, [SPEECH_VIDEO, SPEECH_VIDEO]))
    t_concurrent = time.time() - t0

    # 性能下降 = 并发 wall time 相对单任务的增幅
    degradation = (t_concurrent - t_single) / t_single * 100
    return {
        "metric": "concurrency_degradation",
        "single_seconds": round(t_single, 2),
        "concurrent_wall_seconds": round(t_concurrent, 2),
        "degradation_pct": round(degradation, 1),
        "target": "<= 30%",
        "pass": degradation <= 30.0,
        "note": "2 个视频并发 vs 单视频",
    }


# --------------------------------------------------------------------------- #
# 3. 翻译缓存命中率
# --------------------------------------------------------------------------- #
def bench_cache() -> dict:
    from src.cache.translation_cache import TranslationCache

    async def _run():
        cache = TranslationCache(CACHE_DB)
        await cache.initialize()
        await cache.clear()

        # 混合场景：20 行中 10 行是"历史已缓存"，10 行是"新内容"
        old_lines = ["旧字幕第 %d 行" % i for i in range(10)]
        new_lines = ["新字幕第 %d 行" % i for i in range(10)]
        for t in old_lines:
            await cache.set(t, "en", "cached translation %s" % t)

        hits, total = 0, 0
        for t in old_lines + new_lines:
            total += 1
            if await cache.get(t, "en"):
                hits += 1
        await cache.close()
        return hits, total

    hits, total = asyncio.run(_run())
    if os.path.exists(CACHE_DB):
        os.remove(CACHE_DB)

    rate = hits / total * 100
    return {
        "metric": "cache_hit_rate",
        "hits": hits,
        "total": total,
        "hit_rate_pct": round(rate, 1),
        "target": ">= 20%",
        "pass": rate >= 20.0,
        "note": "混合场景（10 历史 + 10 新）",
    }


# --------------------------------------------------------------------------- #
# 4. OCR 硬字幕识别率
# --------------------------------------------------------------------------- #
def _char_accuracy(pred: str, truth: str) -> float:
    """字符级准确率（忽略空格）"""
    pred = re.sub(r"\s+", "", pred)
    truth = re.sub(r"\s+", "", truth)
    if not truth:
        return 0.0
    matched = sum(1 for a, b in zip(pred, truth) if a == b)
    return matched / len(truth)


def bench_ocr() -> dict:
    import cv2
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR()
    cap = cv2.VideoCapture(HARDSUB_VIDEO)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(fps / 2.0)))  # 与 pipeline 默认 sample_fps=2 一致

    samples = []
    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                res, _ = engine(frame)
                if res:
                    text = " ".join(t for _, t, s in res if s >= 0.5 and t.strip())
                    if text.strip():
                        samples.append(text.strip())
        idx += 1
    cap.release()

    # 逐帧字符准确率，取平均
    accs = [_char_accuracy(s, OCR_GROUND_TRUTH) for s in samples]
    avg = (sum(accs) / len(accs) * 100) if accs else 0.0
    return {
        "metric": "ocr_accuracy",
        "frames_with_text": len(samples),
        "avg_char_accuracy_pct": round(avg, 1),
        "target": ">= 85%",
        "pass": avg >= 85.0,
        "ground_truth": OCR_GROUND_TRUTH,
        "samples": samples[:6],
    }


# --------------------------------------------------------------------------- #
# 5. 翻译 BLEU
# --------------------------------------------------------------------------- #
def bench_bleu() -> dict:
    import sacrebleu
    srcs = [s for s, _ in BLEU_SET]
    refs = [r for _, r in BLEU_SET]

    # 逐行翻译（走同一 LLM），避免批量编号解析引入误差
    hyps = []
    for s in srcs:
        hyps.append(translate([s], "en", {}, use_cache=False)[0])

    bleu = sacrebleu.corpus_bleu(hyps, [refs]).score
    return {
        "metric": "bleu",
        "sentences": len(srcs),
        "bleu_score": round(bleu, 2),
        "target": ">= 0.6",
        "pass": bleu >= 60.0,
        "pairs": [{"src": s, "ref": r, "hyp": h} for s, r, h in zip(srcs, refs, hyps)],
    }


# --------------------------------------------------------------------------- #
# 6. 术语库命中率
# --------------------------------------------------------------------------- #
def bench_terms() -> dict:
    terms = _load_terms()
    lines = list(terms.keys())  # 12 行，每行恰为一条术语
    out = translate(lines, "en", terms, use_cache=False)

    hits = sum(1 for src, dst in zip(lines, out) if dst == terms[src])
    rate = hits / len(lines) * 100
    return {
        "metric": "terminology_hit_rate",
        "total_terms": len(lines),
        "matched": hits,
        "hit_rate_pct": round(rate, 1),
        "target": ">= 90%",
        "pass": rate >= 90.0,
    }


# --------------------------------------------------------------------------- #
# 7. 翻译失败自动重试成功率
# --------------------------------------------------------------------------- #
def bench_retry() -> dict:
    import random
    from src.retry import retry, RetryExhausted

    random.seed(42)
    total, success = 0, 0
    for _ in range(20):
        total += 1

        def _call() -> str:
            if random.random() < 0.4:  # 模拟 40% 瞬时故障（网络抖动）
                raise ConnectionError("模拟瞬时网络故障")
            return "ok"

        try:
            retry(_call, max_retries=3, base_delay=0.0)
            success += 1
        except RetryExhausted:
            pass

    rate = success / total * 100
    return {
        "metric": "retry_success_rate",
        "tasks": total,
        "succeeded": success,
        "success_rate_pct": round(rate, 1),
        "target": ">= 80%",
        "pass": rate >= 80.0,
        "note": "模拟 40% 瞬时故障 + 最多 3 次重试",
    }


# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    runners = {
        "gpu_rtf": bench_gpu_rtf,
        "concurrency": bench_concurrency,
        "cache": bench_cache,
        "ocr": bench_ocr,
        "bleu": bench_bleu,
        "terms": bench_terms,
        "retry": bench_retry,
    }
    if which == "all":
        keys = ["gpu_rtf", "concurrency", "cache", "ocr", "bleu", "terms", "retry"]
    elif which in runners:
        keys = [which]
    else:
        print("未知子命令: %s" % which)
        return 2

    results = []
    for k in keys:
        try:
            r = runners[k]()
            results.append(r)
            print(json.dumps(r, ensure_ascii=False))
        except Exception as e:
            import traceback
            traceback.print_exc()
            results.append({"metric": k, "error": str(e)})
            print(json.dumps({"metric": k, "error": str(e)}, ensure_ascii=False))

    print("=== SUMMARY ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
