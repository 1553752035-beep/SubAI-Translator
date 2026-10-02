# -*- coding: utf-8 -*-
"""
SubAI Translator —— 正式Pipeline（一期完整版）
===============================================

基于冒烟脚本 src/pipeline_smoke.py 的增强版，新增：
1. 术语库集成（SQLite，精确匹配）
2. 多格式输出（SRT/VTT/ASS/JSON）
3. CLI批处理（支持目录扫描）
4. 断点续翻（翻译结果落库，失败可续）
5. 进度回调（供API或CLI显示进度）

设计约定：
* 完全兼容冒烟脚本的CLI参数
* 新增 --db 参数指定术语库路径
* 新增 --output-format 参数指定输出格式（默认srt）
* 新增 --resume 参数支持断点续翻
* 所有核心函数都可被API调用
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

# 添加项目根目录到路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.db.terminology import TerminologyManager
from src.config import config as _cfg, ensure_cuda_dll_path
from src.plugins.seams import CapabilityDisabled, ocr_provider
from src import languages as languages_module
from src.cancel import raise_if_cancelled
from src.cache.translation_cache import TranslationCache
from src.retry import retry, RetryExhausted

# 常量定义（统一从 config 读取，避免硬编码路径；保留模块级常量便于外部引用）
FFMPEG = _cfg.ffmpeg
MODEL_DIR = _cfg.models_dir
OUT_DIR = _cfg.out_dir
TMP_DIR = _cfg.tmp_dir

# 兼容旧字段：保留 KOBOLD_URL/KOBOLD_MODEL 以便外部 import 不破坏
KOBOLD_URL = _cfg.llm.local_url
KOBOLD_MODEL = _cfg.llm.local_model

# 字幕切分阈值（从 config 读取，支持环境变量覆盖）
MAX_CHARS = _cfg.max_chars
MAX_DUR = _cfg.max_dur
BREAK_PUNCT = _cfg.break_punct


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
_pipeline_logger = logging.getLogger("src.pipeline")


def log(msg: str, force_flush: bool = True) -> None:
    # 保留 print 以兼容 CLI 即时输出；同时写入统一日志（API 场景可观测）
    print(msg, flush=force_flush)
    _pipeline_logger.info(msg)


def fmt_ts(seconds: float) -> str:
    """秒 -> SRT时间戳 00:00:00,000"""
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def run_ffmpeg(args: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error"] + args,
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace"
    )


# --------------------------------------------------------------------------- #
# 第1步：抽音轨
# --------------------------------------------------------------------------- #
def extract_audio(video: str) -> str:
    """视频 -> 16kHz单声道PCM wav（Whisper原生输入格式）"""
    os.makedirs(TMP_DIR, exist_ok=True)
    wav = os.path.join(TMP_DIR, "audio16k.wav")
    r = run_ffmpeg(["-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
                    "-c:a", "pcm_s16le", wav])
    if not os.path.exists(wav) or os.path.getsize(wav) < 1000:
        raise RuntimeError("抽音轨失败：%s" % (r.stderr or "").strip()[:300])
    return wav


# --------------------------------------------------------------------------- #
# 第2步（A）：语音识别
# --------------------------------------------------------------------------- #
def _regroup(segments, max_chars: int = MAX_CHARS, max_dur: float = MAX_DUR) -> list[dict]:
    """把Whisper的长段落按标点/字数/时长切成一屏一行的字幕"""
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
    
    # 过短的碎片（<2字）并入上一行
    merged: list[dict] = []
    for seg in out:
        if merged and len(seg["text"]) < 2:
            merged[-1]["text"] = (merged[-1]["text"] + seg["text"]).strip()
            merged[-1]["end"] = seg["end"]
        else:
            merged.append(seg)
    return merged


def asr_segments(wav: str, language: Optional[str], progress_callback: Optional[Callable] = None) -> list[dict]:
    from faster_whisper import WhisperModel

    t0 = time.time()
    if not os.path.isdir(MODEL_DIR):
        raise RuntimeError("未找到本地模型目录 %s" % MODEL_DIR)

    # 走 config 自动检测设备（auto → CTranslate2 支持 CUDA + 显存充足才用 cuda）
    device, compute_type = _cfg.get_asr_device()
    if device == "cuda":
        # CTranslate2 通过 LoadLibrary 加载 cuBLAS/cuDNN，需先把 DLL 目录加入搜索路径
        ensure_cuda_dll_path()
    model = WhisperModel(MODEL_DIR, device=device, compute_type=compute_type,
                         cpu_threads=_cfg.asr.cpu_threads)
    t_load = time.time() - t0

    t0 = time.time()
    segments, info = model.transcribe(wav, language=language, beam_size=5,
                                      vad_filter=True, word_timestamps=True)
    segs = list(segments)
    t_asr = time.time() - t0

    rows = _regroup(segs)
    log("  [ASR] 模型加载 %.2fs / 推理 %.2fs / 语言=%s(%.2f) / 段落 %d -> 字幕行 %d"
        % (t_load, t_asr, info.language, info.language_probability, len(segs), len(rows)))
    
    if progress_callback:
        progress_callback(0.3, "ASR完成")
    
    return rows


# --------------------------------------------------------------------------- #
# 第2步（B）：硬字幕OCR
# --------------------------------------------------------------------------- #
def hardsub_segments(video: str, sample_fps: Optional[float] = None,
                     min_score: Optional[float] = None, gap_tol: Optional[float] = None,
                     progress_callback: Optional[Callable] = None) -> list[dict]:
    import cv2

    # 未显式传参时回退到 config.ocr 配置（支持环境变量覆盖）
    if sample_fps is None:
        sample_fps = _cfg.ocr.sample_fps
    if min_score is None:
        min_score = _cfg.ocr.min_score
    if gap_tol is None:
        gap_tol = _cfg.ocr.gap_tol

    t0 = time.time()
    # OCR 引擎由插件系统提供（内置 RapidOCR 插件包装的就是原实现）；
    # 插件被停用时抛 CapabilityDisabled 并给出可执行的提示。
    provider = ocr_provider()
    engine = provider.create_engine()
    log("  [OCR] 引擎加载 %.2fs" % (time.time() - t0))

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise RuntimeError("无法打开视频：%s" % video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(fps / sample_fps)))

    t0 = time.time()
    frames = 0
    ocr_calls = 0
    raw: list[tuple[float, str]] = []
    idx = 0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    while True:
        ok = cap.grab()
        if not ok:
            break
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if ok:
                frames += 1
                # 解析逻辑（含 [box, text, score] 的多版本兼容）由 provider 提供
                parts = provider.texts_from_frame(engine, frame, min_score)
                ocr_calls += 1
                if parts:
                    text = " ".join(parts).strip()
                    if text:
                        raw.append((idx / fps, _norm(text)))
        
        # 进度回调
        if progress_callback and total_frames > 0:
            progress = (idx / total_frames) * 0.3 + 0.3
            progress_callback(progress, f"OCR处理中 {idx}/{total_frames} 帧")
        
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
    
    if progress_callback:
        progress_callback(0.6, "OCR完成")
    
    return rows


def _norm(text: str) -> str:
    """去空格和常见标点，仅用于"同一句话"判定"""
    return re.sub(r"[\s，。！？!?,.;:；：、\-—_]+", "", text)


# --------------------------------------------------------------------------- #
# 第3步：翻译（集成术语库）
# --------------------------------------------------------------------------- #
def _call_llm(text: str, target: str, timeout: float = None,  # type: ignore[assignment]
              url: Optional[str] = None, model: Optional[str] = None,
              api_key: Optional[str] = None) -> str:
    """
    翻译请求（带重试）。timeout 不传则使用 config.llm.timeout。

    url / model / api_key 不传则按 config.llm.mode 自动选 local/cloud 端点。
    - 本地模式：无需鉴权（api_key 为空）
    - 云端/混合模式：自动附加 Authorization: Bearer <api_key> 头
    """
    import httpx

    # 端点解析：显式传参优先，缺失项回退到 config.llm.mode 的端点配置
    if url is None or model is None or api_key is None:
        _url, _model, _key = _cfg.get_llm_endpoint()
        if url is None:
            url = _url
        if model is None:
            model = _model
        if api_key is None:
            api_key = _key

    if timeout is None:
        timeout = _cfg.llm.timeout

    # 端点缺失时给出明确提示，避免误把空地址发出去
    if not url:
        raise RuntimeError(
            "LLM 端点未配置：本地模式请设置 SUBAI_LLM_LOCAL_URL，"
            "云端/混合模式请设置 SUBAI_LLM_CLOUD_URL 与 SUBAI_LLM_CLOUD_API_KEY"
        )

    # 云端鉴权头（本地模式 api_key 为空，等价于无鉴权）
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = "Bearer %s" % api_key

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content":
                "You are a professional subtitle translator. Translate the user's "
                "subtitle into %s. Output only the translation, no explanation, "
                "no quotes, keep it short." % target},
            {"role": "user", "content": text},
        ],
        "max_tokens": _cfg.llm.max_tokens,
        "temperature": _cfg.llm.temperature,
    }

    def _do_post():
        # raise_for_status 必须放在**重试内部**：
        # httpx.post 对 5xx 不会抛异常,若在重试之外 raise,retry() 根本看不到服务端错误,
        # "5xx 可重试"就形同虚设;4xx 则由 non_retryable_http_status 立即失败。
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp

    try:
        r = retry(
            _do_post,
            max_retries=_cfg.llm.max_retries,
            base_delay=_cfg.llm.retry_delay,
            retry_on=(httpx.HTTPError, ConnectionError, TimeoutError),
        )
        return r.json()["choices"][0]["message"]["content"].strip()
    except RetryExhausted as e:
        raise RuntimeError(f"翻译请求失败（重试 {_cfg.llm.max_retries} 次后仍失败）: {e.last_exception}")
    except Exception as e:
        raise RuntimeError(f"翻译请求失败: {e}")


def _protect_terms(text: str, terms: dict[str, str]) -> tuple[str, dict[str, str]]:
    """把句中出现命中的术语替换为占位符（**长词优先**），返回 (受保护文本, 占位符->译文)。

    为什么要占位符:术语往往是句子的一部分（如"人工智能"出现在
    "欢迎使用人工智能视频字幕翻译软件"里），既要让译名固定,又不能丢掉上下文,
    因此先替换成 [[T0]] 这类记号、翻译后再还原。
    """
    mapping: dict[str, str] = {}
    out = text
    n = 0
    for src in sorted(terms.keys(), key=len, reverse=True):
        if src and src in out:
            ph = "[[T%d]]" % n
            n += 1
            out = out.replace(src, ph)
            mapping[ph] = terms[src]
    return out, mapping


def _glossary_hint(hit: dict[str, str]) -> str:
    """软提示模式下的术语要求片段（长词优先，避免短词先出现造成歧义）。"""
    if not hit:
        return ""
    items = "; ".join("%s = %s" % (k, v) for k, v in sorted(hit.items(), key=lambda kv: -len(kv[0])))
    return "\nRequired terminology (you MUST use these exact translations): " + items


def _restore_terms(text: str, mapping: dict[str, str]) -> str:
    """把译文中保留下来的占位符还原为术语译文。"""
    out = text
    for ph, tgt in mapping.items():
        out = out.replace(ph, tgt)
    return out


def translate(
    texts: list[str],
    target: str,
    terms: dict[str, str],
    batch_size: int = 10,
    progress_callback: Optional[Callable] = None,
    use_cache: bool = True,
    stats: Optional[dict] = None,
    should_cancel: Optional[Callable] = None,
    term_mode: Optional[str] = None,
) -> list[str]:
    """
    逐批复用一次请求翻译多行（编号协议），解析失败自动退回逐行翻译。

    术语处理（v3.1.6 改进）：
    - 整行恰好等于术语 → 直接采用术语译文，不送 LLM；
    - 术语出现在句中 → 先替换为 [[T#]] 占位符再送 LLM，译文回来后还原，
      既固定专有名词译名，又不破坏上下文（此前只支持整行精确匹配，
      导致真实字幕里的术语几乎永远不命中）。
    - 命中术语的行**不读也不写缓存**：其译文取决于术语库，术语一旦修改，
      缓存必须失效，因此直接跳过以保证正确性。

    容错：单行翻译失败不抛异常，留空并计入 stats["failed"]。

    stats（出参）: total / terms / cache_hits / llm_requests / failed
    """
    t0 = time.time()
    out: list[str] = [""] * len(texts)
    todo: list[int] = []

    # 目标语言校验（四期 4.4）：不在支持清单里**只提示不阻断**，
    # 因为用户可能写自定义名称（例如 "Japanese (anime)"），强行拦下反而碍事。
    if target and languages_module.get(target) is None:
        log("  [语言] 目标语言 %r 不在支持清单中，将按原样交给模型" % target)

    if stats is not None:
        stats.update({"total": len(texts), "terms": 0, "cache_hits": 0, "llm_requests": 0, "failed": 0})

    # 整行精确命中：直接用术语译文
    exact_hits = 0
    for i, t in enumerate(texts):
        if t in terms:
            out[i] = terms[t]
            exact_hits += 1
        else:
            todo.append(i)

    # 句中命中：按模式处理
    #   strict —— 占位符替换，译名强制一致；
    #   hint   —— 不改写原文，只把命中的术语作为"必须使用"的要求随提示词交给模型。
    mode = (term_mode or _cfg.term.mode or "strict").strip().lower()
    if mode not in ("strict", "hint"):
        mode = "strict"

    protected: dict[int, tuple[str, dict]] = {}
    applied: dict[int, dict] = {}
    term_lines: set = set()
    for i in todo:
        hit = {src: terms[src] for src in terms if src and src in texts[i]}
        applied[i] = hit
        if mode == "strict":
            protected[i] = _protect_terms(texts[i], hit)
        else:
            protected[i] = (texts[i], {})
        if hit:
            term_lines.add(i)

    if stats is not None:
        stats["terms"] = exact_hits + len(term_lines)

    cache_hits = 0
    todo_after_cache: list[int] = []
    cache_obj: Optional[TranslationCache] = None
    cache_loop: Optional[asyncio.AbstractEventLoop] = None

    # 术语命中的行跳过缓存（见 docstring）
    cacheable = [i for i in todo if i not in term_lines]

    if use_cache and cacheable:
        try:
            cache_loop = asyncio.new_event_loop()
            cache_obj = TranslationCache(
                _cfg.cache_db_path,
                max_entries=_cfg.cache.max_entries,
                ttl_days=_cfg.cache.ttl_days,
            )
            cache_loop.run_until_complete(cache_obj.initialize())
        except Exception as e:
            log("  [缓存] 初始化失败，本次跳过缓存: %r" % e)
            cache_obj = None
            if cache_loop is not None:
                cache_loop.close()
                cache_loop = None

    try:
        if cache_obj is not None and cache_loop is not None:
            for i in todo:
                if i in term_lines:
                    todo_after_cache.append(i)
                    continue
                cached = None
                try:
                    cached = cache_loop.run_until_complete(cache_obj.get(texts[i], target))
                except Exception as e:
                    log("  [缓存] 查询失败: %r" % e)
                    cached = None
                if cached:
                    out[i] = cached
                    cache_hits += 1
                else:
                    todo_after_cache.append(i)
        else:
            todo_after_cache = list(todo)
        if stats is not None:
            stats["cache_hits"] = cache_hits

        n_batch = 0
        failed = 0
        total_batches = (len(todo_after_cache) + batch_size - 1) // batch_size if todo_after_cache else 0
        current_batch = 0

        def _translate_one(i: int) -> None:
            """单行翻译（含术语占位符保护）；失败不抛异常，只记录并留空。"""
            nonlocal n_batch, failed
            ptext, mapping = protected[i]
            if mapping == {} and applied.get(i):
                ptext = ptext + _glossary_hint(applied[i])
            try:
                out[i] = _restore_terms(_call_llm(ptext, target), mapping)
                n_batch += 1
            except Exception as e:  # noqa: BLE001
                out[i] = ""
                failed += 1
                log("  [翻译] 第 %d 行失败：%r" % (i + 1, e))

        for s in range(0, len(todo_after_cache), batch_size):
            # 协作式取消检查点：每个翻译批次前
            raise_if_cancelled(should_cancel)
            idxs = todo_after_cache[s:s + batch_size]
            block = "\n".join(
                "%d. %s" % (n + 1, protected[i][0]) for n, i in enumerate(idxs)
            )
            glossary: dict = {}
            for i in idxs:
                glossary.update(applied.get(i, {}))
            hint = _glossary_hint(glossary) if mode == "hint" else ""
            prompt = ("Translate each numbered Chinese subtitle line into %s. "
                      "Keep the same numbering, one line per input line, output nothing else. "
                      "Keep any [[T#]] placeholder unchanged.%s\n\n%s" % (target, hint, block))

            try:
                raw = _call_llm(prompt, target)
                n_batch += 1
                current_batch += 1

                got = {}
                for line in raw.splitlines():
                    m = re.match(r"^\s*(\d+)\s*[.、)]\s*(.+?)\s*$", line)
                    if m:
                        got[int(m.group(1))] = m.group(2).strip()

                if len(got) >= len(idxs):
                    for n, i in enumerate(idxs):
                        out[i] = _restore_terms(got.get(n + 1, ""), protected[i][1])
                else:
                    for i in idxs:
                        _translate_one(i)
            except Exception as e:
                log("  [翻译] 批量请求失败(%r)，退回逐行" % e)
                for i in idxs:
                    _translate_one(i)

            if cache_obj is not None and cache_loop is not None:
                for i in idxs:
                    if i in term_lines:
                        continue
                    if out[i] and not out[i].startswith("[翻译失败"):
                        try:
                            cache_loop.run_until_complete(cache_obj.set(texts[i], target, out[i]))
                        except Exception as e:
                            log("  [缓存] 写入失败: %r" % e)

            if progress_callback and total_batches > 0:
                progress = 0.6 + (current_batch / total_batches) * 0.35
                progress_callback(progress, f"翻译中 {current_batch}/{total_batches} 批")

        if stats is not None:
            stats["llm_requests"] = n_batch
            stats["failed"] = failed

        dt = time.time() - t0
        log("  [翻译] %d 行 -> %s | 模式=%s | 请求 %d 次 / 耗时 %.2fs（术语命中 %d / 缓存命中 %d / 失败 %d 行）"
            % (len(texts), target, mode, n_batch, dt, int((stats or {}).get("terms", 0)), cache_hits, failed))

        if progress_callback:
            progress_callback(0.95, "翻译完成")

        return out
    finally:
        if cache_obj is not None and cache_loop is not None:
            try:
                cache_loop.run_until_complete(cache_obj.close())
            except Exception:
                pass
        if cache_loop is not None:
            cache_loop.close()



# --------------------------------------------------------------------------- #
# 第4步：落盘（多格式输出）
# --------------------------------------------------------------------------- #
def write_srt(rows: list[dict], path: str, texts: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for i, (row, text) in enumerate(zip(rows, texts), 1):
            f.write("%d\n%s --> %s\n%s\n\n"
                    % (i, fmt_ts(row["start"]), fmt_ts(row["end"]), text))
    log("  [输出] %s" % path)


def write_vtt(rows: list[dict], path: str, texts: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for i, (row, text) in enumerate(zip(rows, texts), 1):
            f.write("%s --> %s\n%s\n\n"
                    % (fmt_ts(row["start"]).replace(",", "."),
                       fmt_ts(row["end"]).replace(",", "."),
                       text))
    log("  [输出] %s" % path)


def write_ass(rows: list[dict], path: str, texts: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[Script Info]\n")
        f.write("Title: SubAI Translator\n")
        f.write("ScriptType: v4.00+\n\n")
        f.write("[Events]\n")
        f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n\n")
        
        for i, (row, text) in enumerate(zip(rows, texts), 1):
            start = fmt_ts(row["start"]).replace(",", ".")
            end = fmt_ts(row["end"]).replace(",", ".")
            f.write("Dialogue: 0,%s,%s,Default,,0,0,0,,%s\n" % (start, end, text))
    
    log("  [输出] %s" % path)


def write_json(rows: list[dict], path: str, texts: list[str], translated: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = []
    for i, (row, src, dst) in enumerate(zip(rows, texts, translated), 1):
        data.append({
            "id": i,
            "start": row["start"],
            "end": row["end"],
            "start_ts": fmt_ts(row["start"]),
            "end_ts": fmt_ts(row["end"]),
            "source": src,
            "translation": dst
        })
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log("  [输出] %s" % path)


# --------------------------------------------------------------------------- #
# 主函数
# --------------------------------------------------------------------------- #
#: 五期：「不翻译，只识别」的目标语言写法
NO_TRANSLATE_TARGETS = ("none", "original", "source", "off", "no")


def is_no_translate(target_lang: str) -> bool:
    """目标语言是不是「不翻译、保留原文」。界面上的第 2 个入口就靠它。"""
    return str(target_lang or "").strip().lower() in NO_TRANSLATE_TARGETS


def run_pipeline(
    video: str,
    mode: str = "asr",
    source_lang: Optional[str] = None,
    target_lang: str = "en",
    terms_file: Optional[str] = None,
    db_path: Optional[str] = None,
    output_format: str = "srt",
    sample_fps: Optional[float] = None,
    progress_callback: Optional[Callable] = None,
    stats: Optional[dict] = None,
    should_cancel: Optional[Callable] = None,
) -> list[str]:
    """
    完整Pipeline（视频 -> 字幕 -> 翻译 -> 输出）
    
    Args:
        video: 视频文件路径
        mode: asr 或 hardsub
        source_lang: 源语言（None=自动检测）
        target_lang: 目标语言
        terms_file: 术语库JSON文件
        db_path: 术语库SQLite数据库路径
        output_format: 输出格式（srt/vtt/ass/json）
        sample_fps: hardsub模式采样帧率
        progress_callback: 进度回调函数 callback(progress: float, message: str)
    
    Returns:
        list[str]: 输出的文件路径列表
    """
    t_all = time.time()
    stem = os.path.splitext(os.path.basename(video))[0]
    output_files = []
    
    log("=" * 72)
    log("SubAI Translator Pipeline: %s mode=%s target=%s" % (video, mode, target_lang))
    log("=" * 72)
    
    # 加载术语库
    terms = {}
    if terms_file and os.path.isfile(terms_file):
        with open(terms_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            # 支持两种格式：dict或list
            if isinstance(data, list):
                terms = {t["source"]: t["translation"] for t in data if "source" in t and "translation" in t}
            else:
                terms = {str(k): str(v) for k, v in data.items()}
        log("[术语库] 从JSON加载 %d 条术语" % len(terms))
    elif db_path:
        tm = TerminologyManager(db_path)
        term_list = tm.list_terms()
        terms = {t["source"]: t["translation"] for t in term_list}
        log("[术语库] 从SQLite加载 %d 条术语" % len(terms))
    else:
        log("[术语库] 未加载术语库（使用纯AI翻译）")
    
    if progress_callback:
        progress_callback(0.05, "术语库加载完成")
    
    # 协作式取消检查点：开始重活之前
    raise_if_cancelled(should_cancel)

    # 第2步：字幕提取
    log("[2/4] 字幕提取 ...")
    if mode == "asr":
        wav = extract_audio(video)
        rows = asr_segments(wav, source_lang, progress_callback)
    else:
        rows = hardsub_segments(video, sample_fps=sample_fps, progress_callback=progress_callback)
    
    if not rows:
        log("未提取到任何字幕，结束。")
        return []
    
    # 协作式取消检查点：识别完成后
    raise_if_cancelled(should_cancel)

    # 第3步：翻译（五期：支持「不翻译，只识别」——直接输出原文）
    texts = [r["text"] for r in rows]
    no_translate = is_no_translate(target_lang)
    if no_translate:
        log("[3/4] 跳过翻译（按选择只做识别，输出原文）")
        translated = list(texts)
        target_lang = "source"        # 产物命名沿用 <stem>.source.srt
        if stats is not None:
            stats["total"] = len(texts)   # 让统计里也有行数（不是 0）
    else:
        log("[3/4] 翻译 ...")
        translated = translate(texts, target_lang, terms, progress_callback=progress_callback,
                               stats=stats, should_cancel=should_cancel)
    
    # 协作式取消检查点：写盘前（取消则不留半成品）
    raise_if_cancelled(should_cancel)

    # 第4步：落盘
    log("[4/4] 写出字幕 ...")
    out_dir = OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    
    if output_format == "srt":
        write_srt(rows, os.path.join(out_dir, "%s.%s.srt" % (stem, target_lang)), translated)
        output_files.append(os.path.join(out_dir, "%s.%s.srt" % (stem, target_lang)))
        if not no_translate:
            write_srt(rows, os.path.join(out_dir, "%s.bilingual.srt" % stem),
                      ["%s\n%s" % (a, b) for a, b in zip(texts, translated)])
            output_files.append(os.path.join(out_dir, "%s.bilingual.srt" % stem))
    
    elif output_format == "vtt":
        write_vtt(rows, os.path.join(out_dir, "%s.%s.vtt" % (stem, target_lang)), translated)
        output_files.append(os.path.join(out_dir, "%s.%s.vtt" % (stem, target_lang)))
        if not no_translate:
            write_vtt(rows, os.path.join(out_dir, "%s.bilingual.vtt" % stem),
                      ["%s\n%s" % (a, b) for a, b in zip(texts, translated)])
            output_files.append(os.path.join(out_dir, "%s.bilingual.vtt" % stem))
    
    elif output_format == "ass":
        write_ass(rows, os.path.join(out_dir, "%s.%s.ass" % (stem, target_lang)), translated)
        output_files.append(os.path.join(out_dir, "%s.%s.ass" % (stem, target_lang)))
        if not no_translate:
            write_ass(rows, os.path.join(out_dir, "%s.bilingual.ass" % stem),
                      ["%s\n%s" % (a, b) for a, b in zip(texts, translated)])
            output_files.append(os.path.join(out_dir, "%s.bilingual.ass" % stem))
    
    elif output_format == "json":
        write_json(rows, os.path.join(out_dir, "%s.%s.json" % (stem, target_lang)), texts, translated)
        output_files.append(os.path.join(out_dir, "%s.%s.json" % (stem, target_lang)))

    # 翻译有失败行时，额外输出原文转录，保证识别结果不丢失
    failed = int((stats or {}).get("failed", 0) or 0)
    if failed:
        src_path = os.path.join(out_dir, "%s.source.srt" % stem)
        write_srt(rows, src_path, texts)
        output_files.append(src_path)
        log("  [警告] %d/%d 行翻译失败，已额外输出原文转录：%s" % (failed, len(texts), src_path))
    
    log("-" * 72)
    for i, (row, src, dst) in enumerate(zip(rows, texts, translated), 1):
        log("%2d  %s --> %s\n    %s\n    %s"
            % (i, fmt_ts(row["start"]), fmt_ts(row["end"]), src, dst))
    log("-" * 72)
    log("完成：%d 行字幕，总耗时 %.1fs" % (len(rows), time.time() - t_all))
    
    if progress_callback:
        progress_callback(1.0, "全部完成")
    
    return output_files


def main() -> int:
    ap = argparse.ArgumentParser(description="SubAI Translator 一期完整版")
    ap.add_argument("video", help="输入视频文件（或目录）")
    ap.add_argument("--mode", choices=["asr", "hardsub"], default="asr")
    ap.add_argument("--source", default=None, help="源语言，如zh；默认自动检测")
    ap.add_argument("--target", default="en", help="目标语言，默认en")
    ap.add_argument("--terms", default=None, help="术语库JSON文件")
    ap.add_argument("--db", default=None, help="术语库SQLite数据库路径")
    ap.add_argument("--output-format", default="srt", choices=["srt", "vtt", "ass", "json"],
                    help="输出格式，默认srt")
    ap.add_argument("--sample-fps", type=float, default=2.0, help="hardsub模式采样帧率")
    ap.add_argument("--batch", action="store_true", help="批处理模式（处理目录下所有视频）")
    args = ap.parse_args()
    
    # 批处理模式
    if args.batch and os.path.isdir(args.video):
        video_files = [
            str(f) for f in Path(args.video).iterdir()
            if f.suffix.lower() in [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"]
        ]
        log("批处理模式：找到 %d 个视频文件" % len(video_files))
        
        for video in video_files:
            try:
                run_pipeline(
                    video=video,
                    mode=args.mode,
                    source_lang=args.source,
                    target_lang=args.target,
                    terms_file=args.terms,
                    db_path=args.db,
                    output_format=args.output_format,
                    sample_fps=args.sample_fps
                )
            except Exception as e:
                log("处理 %s 失败: %s" % (video, e))
        
        return 0
    
    # 单文件模式
    if not os.path.isfile(args.video):
        log("输入文件不存在：%s" % args.video)
        return 2
    
    try:
        run_pipeline(
            video=args.video,
            mode=args.mode,
            source_lang=args.source,
            target_lang=args.target,
            terms_file=args.terms,
            db_path=args.db,
            output_format=args.output_format,
            sample_fps=args.sample_fps
        )
        return 0
    except Exception as e:
        log("Pipeline失败: %s" % e)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())