# -*- coding: utf-8 -*-
"""
SubAI Translator —— 一期链路冒烟脚本（同时充当集成参考实现）
============================================================

把「视频 → 字幕 → 翻译 → SRT」整条链路真实跑通一遍，用来证明环境不只是
“包能 import”，而是端到端可用；代码结构也是后续正式 pipeline 的雏形。

两种字幕来源：
  --mode asr       （默认）从音轨做语音识别（faster-whisper / CTranslate2）
  --mode hardsub   从画面做硬字幕 OCR（RapidOCR / PP-OCR on ONNX Runtime）

用法：
  .venv\\Scripts\\python.exe src\\pipeline_smoke.py data\\test_speech.mp4
  .venv\\Scripts\\python.exe src\\pipeline_smoke.py data\\test_hardsub.mp4 --mode hardsub
  .venv\\Scripts\\python.exe src\\pipeline_smoke.py <video> --target ja --mode hardsub

设计约定：
  * 翻译走本机 koboldcpp 的 OpenAI 兼容接口（默认 127.0.0.1:5001），
    不依赖任何云 API，也不依赖 GPU torch。
  * 全部耗时都会打印，便于日后判断哪一环是瓶颈。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FFMPEG = os.path.join(ROOT, "bin", "ffmpeg.exe")
MODEL_DIR = os.path.join(ROOT, "models", "faster-whisper-small")
OUT_DIR = os.path.join(ROOT, "output")
TMP_DIR = os.path.join(ROOT, "output", "_tmp")

KOBOLD_URL = os.environ.get("KOBOLD_URL", "http://127.0.0.1:5001/v1/chat/completions")
KOBOLD_MODEL = os.environ.get("KOBOLD_MODEL", "koboldcpp")

# 字幕切分阈值：一行最多 20 个字符 / 最长 6 秒，避免整段堆在一行
MAX_CHARS = 20
MAX_DUR = 6.0
# 中文断句标点，遇到就断行
BREAK_PUNCT = "。！？!?…；;，,、"

# 术语表：命中的字幕行不走 LLM，直接用用户指定的译法（对应设计文档里的
# “优化一：用户自定义术语库”）。可被 --terms 指向的 JSON 文件覆盖。
DEFAULT_TERMS: dict[str, str] = {}


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def log(msg: str) -> None:
    print(msg, flush=True)


def fmt_ts(seconds: float) -> str:
    """秒 -> SRT 时间戳 00:00:00,000"""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def run_ffmpeg(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error"] + args,
                          capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# 第 1 步：抽音轨
# --------------------------------------------------------------------------- #
def extract_audio(video: str) -> str:
    """视频 -> 16kHz 单声道 PCM wav（Whisper 的原生输入格式）"""
    os.makedirs(TMP_DIR, exist_ok=True)
    wav = os.path.join(TMP_DIR, "audio16k.wav")
    r = run_ffmpeg(["-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", wav])
    if not os.path.exists(wav) or os.path.getsize(wav) < 1000:
        raise RuntimeError("抽音轨失败：%s" % (r.stderr or "").strip()[:300])
    return wav


# --------------------------------------------------------------------------- #
# 第 2 步（A）：语音识别
# --------------------------------------------------------------------------- #
def _regroup(segments, max_chars: int = MAX_CHARS, max_dur: float = MAX_DUR) -> list[dict]:
    """把 Whisper 的长段落按标点 / 字数 / 时长切成一屏一行的字幕。"""
    out: list[dict] = []
    for seg in segments:
        words = list(getattr(seg, "words", None) or [])
        if not words:
            text = (seg.text or "").strip()
            if text:
                out.append({"start": seg.start, "end": seg.end, "text": text})
            continue
        cur = []
        for w in words:
            if not cur and not w.word.strip():
                continue
            cur.append(w)
            text = "".join(x.word for x in cur).strip()
            dur = cur[-1].end - cur[0].start
            tail = w.word.strip()[-1:] if w.word.strip() else ""
            if len(text) >= max_chars or dur >= max_dur or tail in BREAK_PUNCT:
                if text:
                    out.append({"start": cur[0].start, "end": cur[-1].end, "text": text})
                cur = []
        if cur:
            text = "".join(x.word for x in cur).strip()
            if text:
                out.append({"start": cur[0].start, "end": cur[-1].end, "text": text})
    # 过短的碎片（<2 字）并入上一行，避免出现只有标点/语气词的一屏
    merged: list[dict] = []
    for seg in out:
        if merged and len(seg["text"]) < 2:
            merged[-1]["text"] = (merged[-1]["text"] + seg["text"]).strip()
            merged[-1]["end"] = seg["end"]
        else:
            merged.append(seg)
    return merged


def asr_segments(wav: str, language: str | None) -> list[dict]:
    from faster_whisper import WhisperModel

    t0 = time.time()
    if not os.path.isdir(MODEL_DIR):
        raise RuntimeError("未找到本地模型目录 %s（请先跑 tools/fetch_ct2_model.ps1）" % MODEL_DIR)
    # 一期固定 CPU + int8：koboldcpp 已占满显存，且 8 秒音频仅需 1.6s 推理，
    # 完全没有抢 GPU 的必要。详见决策文档「算力分配」一节。
    model = WhisperModel(MODEL_DIR, device="cpu", compute_type="int8", cpu_threads=8)
    t_load = time.time() - t0

    t0 = time.time()
    segments, info = model.transcribe(wav, language=language, beam_size=5,
                                      vad_filter=True, word_timestamps=True)
    segs = list(segments)          # 生成器，必须在这里消费掉
    t_asr = time.time() - t0

    rows = _regroup(segs)
    log("  [ASR] 模型加载 %.2fs / 推理 %.2fs / 语言=%s(%.2f) / 段落 %d -> 字幕行 %d"
        % (t_load, t_asr, info.language, info.language_probability, len(segs), len(rows)))
    return rows


# --------------------------------------------------------------------------- #
# 第 2 步（B）：硬字幕 OCR
# --------------------------------------------------------------------------- #
def hardsub_segments(video: str, sample_fps: float = 2.0,
                     min_score: float = 0.5, gap_tol: float = 0.8) -> list[dict]:
    """按固定帧率采样 -> OCR -> 合并连续相同文本，得到带时间戳的字幕。"""
    import cv2
    from rapidocr_onnxruntime import RapidOCR

    t0 = time.time()
    engine = RapidOCR()
    log("  [OCR] 引擎加载 %.2fs" % (time.time() - t0))

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise RuntimeError("无法打开视频：%s" % video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(fps / sample_fps)))

    t0 = time.time()
    frames = 0
    ocr_calls = 0
    raw: list[tuple[float, str]] = []          # (时间, 文本)
    idx = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                frames += 1
                res, _ = engine(frame)
                ocr_calls += 1
                if res:
                    parts = [t for _, t, s in res if s >= min_score and t.strip()]
                    text = " ".join(parts).strip()
                    if text:
                        raw.append((idx / fps, _norm(text)))
        idx += 1
    cap.release()
    t_ocr = time.time() - t0

    # 合并时间上相邻、文本相同的采样点
    rows: list[dict] = []
    for ts, text in raw:
        if rows and rows[-1]["text"] == text and ts - rows[-1]["end"] <= gap_tol:
            rows[-1]["end"] = ts
        else:
            rows.append({"start": ts, "end": ts, "text": text})
    for r in rows:
        r["end"] = max(r["end"], r["start"] + 0.5)

    log("  [OCR] 采样 %.0f 帧 / OCR %d 次 / 耗时 %.2fs(%.3fs 每帧) / 去重后字幕 %d 行"
        % (frames, ocr_calls, t_ocr, t_ocr / max(1, ocr_calls), len(rows)))
    return rows


def _norm(text: str) -> str:
    """去空格与常见标点，仅用于“同一句话”判定，不改变输出内容。"""
    return re.sub(r"[\s，。！？!?,.;:；：、\-—_]+", "", text)


# --------------------------------------------------------------------------- #
# 第 3 步：翻译
# --------------------------------------------------------------------------- #
def load_terms(path: str | None) -> dict[str, str]:
    if path and os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return {str(k): str(v) for k, v in json.load(f).items()}
    return dict(DEFAULT_TERMS)


def _call_llm(text: str, target: str, timeout: float = 180) -> str:
    import httpx

    payload = {
        "model": KOBOLD_MODEL,
        "messages": [
            {"role": "system", "content":
                "You are a professional subtitle translator. Translate the user's "
                "subtitle into %s. Output only the translation, no explanation, "
                "no quotes, keep it short." % target},
            {"role": "user", "content": text},
        ],
        "max_tokens": 256,
        "temperature": 0.2,
    }
    r = httpx.post(KOBOLD_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def translate(texts: list[str], target: str, terms: dict[str, str],
              batch_size: int = 10) -> list[str]:
    """逐批复用一次请求翻译多行（编号协议），解析失败自动退回逐行翻译。

    批量请求能把上下文一起给模型，译文更连贯，请求数也从 N 降到 N/10。
    """
    t0 = time.time()
    out: list[str] = [""] * len(texts)
    todo: list[int] = []

    # 术语库优先：命中即锁定，不送 LLM（“优先级：高”覆盖 AI 翻译）
    for i, t in enumerate(texts):
        if t in terms:
            out[i] = terms[t]
        else:
            todo.append(i)

    n_batch = 0
    for s in range(0, len(todo), batch_size):
        idxs = todo[s:s + batch_size]
        block = "\n".join("%d. %s" % (n + 1, texts[i]) for n, i in enumerate(idxs))
        prompt = ("Translate each numbered Chinese subtitle line into %s. "
                  "Keep the same numbering, one line per input line, "
                  "output nothing else.\n\n%s" % (target, block))
        try:
            raw = _call_llm(prompt, target)
            n_batch += 1
            got = {}
            for line in raw.splitlines():
                m = re.match(r"^\s*(\d+)\s*[.、)]\s*(.+?)\s*$", line)
                if m:
                    got[int(m.group(1))] = m.group(2).strip()
            if len(got) >= len(idxs):
                for n, i in enumerate(idxs):
                    out[i] = got.get(n + 1, "")
            else:
                for i in idxs:                      # 解析不全 -> 逐行重来
                    out[i] = _call_llm(texts[i], target)
                    n_batch += 1
        except Exception as e:                       # 接口异常 -> 逐行重来
            log("  [翻译] 批量请求失败(%r)，退回逐行" % e)
            for i in idxs:
                out[i] = _call_llm(texts[i], target)
                n_batch += 1

    dt = time.time() - t0
    log("  [翻译] %d 行 -> %s | 请求 %d 次 / 耗时 %.2fs（术语命中 %d 行）"
        % (len(texts), target, n_batch, dt, len(texts) - len(todo)))
    return out


# --------------------------------------------------------------------------- #
# 第 4 步：落盘
# --------------------------------------------------------------------------- #
def write_srt(rows: list[dict], path: str, texts: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for i, (row, text) in enumerate(zip(rows, texts), 1):
            f.write("%d\n%s --> %s\n%s\n\n"
                    % (i, fmt_ts(row["start"]), fmt_ts(row["end"]), text))
    log("  [输出] %s" % path)


# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser(description="SubAI Translator 一期链路冒烟")
    ap.add_argument("video", help="输入视频文件")
    ap.add_argument("--mode", choices=["asr", "hardsub"], default="asr")
    ap.add_argument("--source", default=None, help="源语言，如 zh；默认自动检测(asr)/zh(hardsub)")
    ap.add_argument("--target", default="en", help="目标语言，默认 en")
    ap.add_argument("--terms", default=None, help="术语库 JSON 文件")
    ap.add_argument("--sample-fps", type=float, default=2.0, help="hardsub 模式采样帧率")
    args = ap.parse_args()

    if not os.path.isfile(args.video):
        log("输入文件不存在：%s" % args.video)
        return 2
    t_all = time.time()
    stem = os.path.splitext(os.path.basename(args.video))[0]

    log("=" * 72)
    log("SubAI Translator 冒烟：%s  mode=%s  target=%s" % (args.video, args.mode, args.target))
    log("=" * 72)

    log("[2/4] 字幕提取 ...")
    if args.mode == "asr":
        wav = extract_audio(args.video)
        rows = asr_segments(wav, args.source)
    else:
        rows = hardsub_segments(args.video, sample_fps=args.sample_fps)
    if not rows:
        log("未提取到任何字幕，结束。")
        return 1

    log("[3/4] 翻译 ...")
    terms = load_terms(args.terms)
    texts = [r["text"] for r in rows]
    translated = translate(texts, args.target, terms)

    log("[4/4] 写出字幕 ...")
    write_srt(rows, os.path.join(OUT_DIR, "%s.%s.srt" % (stem, args.target)), translated)
    write_srt(rows, os.path.join(OUT_DIR, "%s.bilingual.srt" % stem),
              ["%s\n%s" % (a, b) for a, b in zip(texts, translated)])

    log("-" * 72)
    for i, (row, src, dst) in enumerate(zip(rows, texts, translated), 1):
        log("%2d  %s --> %s\n    %s\n    %s"
            % (i, fmt_ts(row["start"]), fmt_ts(row["end"]), src, dst))
    log("-" * 72)
    log("完成：%d 行字幕，总耗时 %.1fs" % (len(rows), time.time() - t_all))
    return 0


if __name__ == "__main__":
    sys.exit(main())
