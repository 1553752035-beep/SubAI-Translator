# -*- coding: utf-8 -*-
"""sherpa-onnx ASR 引擎：SenseVoice / Paraformer-zh。

为什么不用 `funasr` 库
----------------------
阿里官方 `funasr` 是训练/研究框架，作为部署推理运行时有多处反直觉行为（实测）：

1. **VAD 不显式传 `vad_model` 时会静默只处理开头几秒**，整段 100 秒音频只出 23 个字；
2. 即使传了 `vad_model`，`merge_vad=True` 会把全部语音合并成 **一条** 段落，
   拿不到分句时间轴；
3. 参数（`batch_size_s` / `merge_length_s`）对结果影响不成规律，难以验收。

同一个 SenseVoice 模型换成 `sherpa-onnx` 运行时后，分段正常（19/30/24 段）、
耗时从 4.2~8.1s 降到 1.6~2.5s。故本项目直接对接 sherpa-onnx，
`funasr` 只作为模型来源（实际模型取自 `csukuangfj/sherpa-onnx-*` 的 onnx 版本）。

与项目现有接口的关系
--------------------
对外只暴露 `transcribe(wav) -> list[dict]`，返回结构与 `pipeline.asr_segments`
一致（`{"start": float, "end": float, "text": str}`），
因此调用方只需按 `config.asr.engine` 分流，下游（词表纠错、regroup、写 SRT）完全复用。

时间轴说明
----------
SenseVoice / Paraformer 都是**段级**模型，没有词级时间戳。
每段的时间来自 **Silero VAD 的语音段边界**：先把语音切成段，再逐段识别，
段落起止即 VAD 段起止。这是段级引擎能做到的最准时间轴，
精度取决于 VAD 切分质量而非文本长度比例（后者是 SmartSub 对无 VAD 场景的兜底做法）。
"""
from __future__ import annotations

import os
import time
from typing import Callable, Optional

from src.config import config

# log 定义在 pipeline.py（项目既有约定），此处延迟导入避免循环依赖：
# pipeline → asr_sherpa → pipeline 会在模块加载期成环。
def log(msg: str, force_flush: bool = True) -> None:  # noqa: D103
    from src.pipeline import log as _plog
    _plog(msg, force_flush)

# ---- 默认模型目录布局（与 SmartSub 的 <根>/<模型id>/{model.int8.onnx,tokens.txt} 同构） ----
ENGINE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "sherpa")
SENSEVOICE_DIR = os.path.join(ENGINE_DIR, "sensevoice-small")
PARAFORMER_DIR = os.path.join(ENGINE_DIR, "paraformer-zh")
# [2026-10-25] 新增两个引擎（都是 sherpa-onnx 2.x 原生支持的类型）。
# Qwen3-ASR 是 decoder-only LLM 结构（decoder 独占 720MB），
# 多语言覆盖（日/粤/中英混说）比 SenseVoice 广；代价是体积与速度。
QWEN3_DIR = os.path.join(ENGINE_DIR, "qwen3-asr")
FIRERED_DIR = os.path.join(ENGINE_DIR, "firered-asr")
VAD_MODEL = os.path.join(ENGINE_DIR, "silero_vad.onnx")
DENOISE_MODEL = os.path.join(ENGINE_DIR, "gtcrn_simple.onnx")

SAMPLE_RATE = 16000
VAD_WINDOW = 512          # Silero VAD 推荐窗口（样本数）
DENOISE_SAMPLE_RATE = 16000


def _safe(path: str) -> str:
    """把模型路径转成原生库能打开的形式。

    [2026-10-25] 为什么必须有这一层：
    sherpa-onnx 的 C++ 层用**窄字符 API**（fopen / std::ifstream）打开模型，
    而 Python 传的是 UTF-8 字节。Windows 系统代码页不是 UTF-8 时
    （中文版 936/GBK），这些字节被当成本地代码页解码，路径变成不存在的名字。

    症状是**静默降级**而不是报错，所以特别难查：
    - silero VAD 构造失败后每次调用都打印 `vad is nullptr`，永远切出 0 段
    - 识别/降噪/TTS 构造时抛 `Please check your config!`

    本项目 models/sherpa 位于含中文的路径下（开发时用相对路径能跑通），
    **打包后必然踩到**，所以提前处理。

    只有 Windows + 非 ASCII 时才介入；其余情形原样返回。
    """
    try:
        from src.native_safe import ensure_native_safe
        return ensure_native_safe(path)
    except Exception:  # noqa: BLE001
        # 暂存是尽力而为，失败不该让识别失败
        return path


def _safe_dir(path: str) -> str:
    """目录版（模型目录下有多个文件，整体搬比逐文件更简单）。"""
    try:
        from src.native_safe import ensure_dir_native_safe
        return ensure_dir_native_safe(path)
    except Exception:  # noqa: BLE001
        return path

_recognizer_cache: dict = {}
_denoiser_cache: dict = {}


def _require(mod_name: str):
    try:
        import importlib
        return importlib.import_module(mod_name)
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError(
            "未安装 %s，无法使用 sherpa 引擎。请执行: pip install sherpa-onnx"
            % mod_name
        ) from e


def models_available() -> dict:
    """返回各模型是否就绪（供 /api/system/asr-device 之类的只读接口展示）。"""
    def _ready(d: str) -> bool:
        return os.path.isfile(os.path.join(d, "model.int8.onnx")) and \
               os.path.isfile(os.path.join(d, "tokens.txt"))

    def _qwen3_ready() -> bool:
        """Qwen3-ASR 是三个模型文件 + 一个 tokenizer 目录，缺一件都跑不起来。

        tokenizer 是**目录**（BPE 的 vocab.json + merges.txt +
        tokenizer_config.json），不是单个 tokens.txt。
        sherpa 的 tokenizer 参数直接接目录路径。
        """
        need = ("conv_frontend.onnx", "encoder.int8.onnx", "decoder.int8.onnx")
        if not all(os.path.isfile(os.path.join(QWEN3_DIR, f)) for f in need):
            return False
        tk = os.path.join(QWEN3_DIR, "tokenizer")
        return (os.path.isfile(os.path.join(tk, "vocab.json"))
                and os.path.isfile(os.path.join(tk, "merges.txt")))

    def _firered_ready() -> bool:
        return (os.path.isfile(os.path.join(FIRERED_DIR, "model.int8.onnx"))
                and os.path.isfile(os.path.join(FIRERED_DIR, "tokens.txt")))

    return {
        "sensevoice": _ready(SENSEVOICE_DIR),
        "paraformer": _ready(PARAFORMER_DIR),
        "qwen3": _qwen3_ready(),
        "firered": _firered_ready(),
        "vad": os.path.isfile(VAD_MODEL),
        "denoise": os.path.isfile(DENOISE_MODEL),
    }


def _get_recognizer(which: str):
    """按 (引擎, 线程数) 缓存识别器 —— 模型加载 2~3 秒，不能每个任务重来。"""
    key = (which, config.asr.cpu_threads)
    if key in _recognizer_cache:
        return _recognizer_cache[key]

    so = _require("sherpa_onnx")
    _nt = config.asr.cpu_threads

    if which == "qwen3":
        # Qwen3-ASR：decoder-only LLM 结构，四件套必须齐全。
        # 采样参数（temperature/top_p）用 sherpa 默认值，不暴露给用户 ——
        # 字幕场景要的是确定性输出，随机采样会让同一素材两次跑出不同字幕。
        need = {
            "conv_frontend": os.path.join(QWEN3_DIR, "conv_frontend.onnx"),
            "encoder": os.path.join(QWEN3_DIR, "encoder.int8.onnx"),
            "decoder": os.path.join(QWEN3_DIR, "decoder.int8.onnx"),
        }
        missing = [k for k, v in need.items() if not os.path.isfile(v)]
        # tokenizer 是目录：vocab.json + merges.txt (+ tokenizer_config.json)
        _tok_dir = os.path.join(QWEN3_DIR, "tokenizer")
        for f in ("vocab.json", "merges.txt"):
            if not os.path.isfile(os.path.join(_tok_dir, f)):
                missing.append("tokenizer/" + f)
        if missing:
            raise RuntimeError("Qwen3-ASR 模型不完整（缺 %s）：%s"
                               % (", ".join(missing), QWEN3_DIR))
        rec = so.OfflineRecognizer.from_qwen3_asr(
            conv_frontend=need["conv_frontend"],
            encoder=need["encoder"],
            decoder=need["decoder"],
            tokenizer=_tok_dir,
            num_threads=_nt,
            # 默认 max_new_tokens=128 太短：Qwen3 是 LLM 结构，一段稍长的语音
            # 就会在 128 个 token 处被截断（表现为字幕尾部丢失）。官方示例用 1024。
            max_new_tokens=1024,
            max_total_len=1024,
            debug=False,
        )
    elif which == "firered":
        # FireRed 有两条产品线，签名不同，必须都支持：
        # - firered-asr-large（2025-02）：encoder + decoder 两个文件（AED 结构）
        # - firered-asr2-ctc（2026-02）：单个 model.int8.onnx（CTC 结构）
        d = _safe_dir(FIRERED_DIR)
        t = os.path.join(d, "tokens.txt")
        enc = os.path.join(d, "encoder.int8.onnx")
        dec = os.path.join(d, "decoder.int8.onnx")
        m = os.path.join(d, "model.int8.onnx")
        if os.path.isfile(enc) and os.path.isfile(dec) and os.path.isfile(t):
            rec = so.OfflineRecognizer.from_fire_red_asr(
                encoder=enc, decoder=dec, tokens=t, num_threads=_nt, debug=False,
            )
        elif os.path.isfile(m) and os.path.isfile(t):
            # CTC 版：单文件，用通用构造走 offline recognizer
            cfg = so.OfflineRecognizerConfig(
                model_config=so.OfflineModelConfig(
                    fire_red_asr=so.OfflineFireRedAsrModelConfig(encoder=m, decoder=""),
                    tokens=t, num_threads=_nt,
                )
            )
            rec = so.OfflineRecognizer(cfg)
        else:
            raise RuntimeError(
                "FireRed-ASR 模型未安装：%s（需要 encoder+decoder+tokens "
                "或 model.int8.onnx+tokens）" % d)
    elif which == "paraformer":
        d = _safe_dir(PARAFORMER_DIR)
        m = os.path.join(d, "model.int8.onnx")
        t = os.path.join(d, "tokens.txt")
        if not (os.path.isfile(m) and os.path.isfile(t)):
            raise RuntimeError("Paraformer 模型未安装：%s" % d)
        rec = so.OfflineRecognizer.from_paraformer(
            paraformer=m, tokens=t, num_threads=_nt, debug=False,
        )
    else:
        d = _safe_dir(SENSEVOICE_DIR)
        m = os.path.join(d, "model.int8.onnx")
        t = os.path.join(d, "tokens.txt")
        if not (os.path.isfile(m) and os.path.isfile(t)):
            raise RuntimeError("SenseVoice 模型未安装：%s" % d)
        _lang = (config.asr.sensevoice_language or "auto").strip().lower()
        rec = so.OfflineRecognizer.from_sense_voice(
            model=m, tokens=t,
            num_threads=config.asr.cpu_threads,
            use_itn=bool(config.asr.sensevoice_itn),
            language="" if _lang in ("", "auto") else _lang,
            debug=False,
        )
    _recognizer_cache[key] = rec
    return rec


def _make_vad(so):
    cfg = so.VadModelConfig()
    cfg.silero_vad.model = _safe(VAD_MODEL)
    cfg.silero_vad.threshold = float(config.asr.vad_threshold)
    cfg.silero_vad.min_silence_duration = float(config.asr.vad_min_silence_ms) / 1000.0
    cfg.silero_vad.min_speech_duration = float(config.asr.vad_min_speech_ms) / 1000.0
    cfg.silero_vad.window_size = VAD_WINDOW
    # 0 = 不限制单段最大时长；sherpa 用一个足够大的秒数表达「不限」
    _max = float(config.asr.vad_max_speech_sec or 0)
    cfg.silero_vad.max_speech_duration = _max if _max > 0 else 100000.0
    cfg.sample_rate = SAMPLE_RATE
    cfg.num_threads = 1
    return cfg


def _denoise(samples, so):
    """GTCRN 降噪。默认关闭：实测会把「有敌人」变成「就敌人」，属引入新错误。

    仅在 config.asr.denoise=True 时启用（适合人声被噪声淹没的素材）。
    """
    key = "gtcrn"
    if key not in _denoiser_cache:
        cfg = so.OfflineSpeechDenoiserConfig()
        cfg.model.gtcrn.model = _safe(DENOISE_MODEL)
        _denoiser_cache[key] = so.OfflineSpeechDenoiser(cfg)
    out = _denoiser_cache[key].run(samples, DENOISE_SAMPLE_RATE)
    return out.samples


def _read_wav(path: str):
    """读 16k 单声道 wav 为 float32。

    [2026-10-25] 从「不对就报错」改成「不对就自动转」。
    原来 44.1kHz 的音频会直接抛「要求 16000 Hz，实际 44100 Hz」，
    但**这个错误对用户毫无可操作性** —— 他手上就是一段普通音频，
    期望的是能用，而不是先去学 ffmpeg 转码。
    实测官方测试音频 5 个里有 3 个是 44.1kHz，这条路很容易撞上。

    实现：检测到采样率/声道不符时，用 ffmpeg 转到临时 16k 单声道文件再读。
    """
    import wave
    import numpy as np
    try:
        with wave.open(path, "rb") as f:
            if f.getframerate() == SAMPLE_RATE and f.getnchannels() == 1:
                raw = f.readframes(f.getnframes())
                return np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0
    except (wave.Error, EOFError, OSError):
        # 不是标准 wav（或是 float wav），走下面的 ffmpeg 转码
        pass

    import os
    import subprocess
    import tempfile
    from src.config import config

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        r = subprocess.run(
            [config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
             "-i", path, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
             "-c:a", "pcm_s16le", tmp.name],
            capture_output=True, timeout=600,
        )
        if r.returncode != 0 or os.path.getsize(tmp.name) < 1000:
            raise RuntimeError(
                "音频转 16kHz 失败（%s）：%s"
                % (os.path.basename(path),
                   (r.stderr or b"").decode("utf-8", "replace")[:300])
            )
        with wave.open(tmp.name, "rb") as f:
            raw = f.readframes(f.getnframes())
        return np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass


def transcribe(wav: str, which: str = "sensevoice",
               progress_callback: Optional[Callable] = None) -> list:
    """sherpa-onnx 转写。返回 [{"start","end","text"}]，与 pipeline.asr_segments 同构。

    Parameters
    ----------
    wav : 16kHz 单声道 wav 路径
    which : "sensevoice" | "paraformer"
    progress_callback : 可选，接收 0~100 的整数进度
    """
    import numpy as np
    so = _require("sherpa_onnx")

    t0 = time.time()
    samples = _read_wav(wav)
    dur = len(samples) / float(SAMPLE_RATE)
    log("[ASR/sherpa] 引擎=%s 音频=%.1fs 线程=%d"
        % (which, dur, config.asr.cpu_threads))

    if getattr(config.asr, "denoise", False):
        if os.path.isfile(DENOISE_MODEL):
            t_dn = time.time()
            samples = np.asarray(_denoise(samples, so), dtype="float32")
            log("[ASR/sherpa] GTCRN 降噪完成 %.1fs（可能引入新错字，仅建议噪声素材开启）"
                % (time.time() - t_dn))
        else:
            log("[ASR/sherpa][注意] 已开启降噪但模型缺失：%s" % DENOISE_MODEL)

    rec = _get_recognizer(which)

    # ---- Silero VAD 切段 ----
    t1 = time.time()
    vad = so.VoiceActivityDetector(_make_vad(so), buffer_size_in_seconds=60)
    speech = []
    total = len(samples)
    step = 0
    for i in range(0, total, VAD_WINDOW):
        chunk = samples[i:i + VAD_WINDOW]
        if len(chunk) < VAD_WINDOW:
            chunk = np.pad(chunk, (0, VAD_WINDOW - len(chunk)))
        vad.accept_waveform(chunk)
        while not vad.empty():
            seg = vad.front
            start = seg.start / float(SAMPLE_RATE)
            end = (seg.start + len(seg.samples)) / float(SAMPLE_RATE)
            speech.append((start, end, np.array(seg.samples)))
            vad.pop()
        step += 1
        if progress_callback and step % 40 == 0:
            try:
                progress_callback(int(min(50, (i / max(total, 1)) * 50)))
            except Exception:  # noqa: BLE001
                pass
    vad.flush()
    while not vad.empty():
        seg = vad.front
        start = seg.start / float(SAMPLE_RATE)
        end = (seg.start + len(seg.samples)) / float(SAMPLE_RATE)
        speech.append((start, end, np.array(seg.samples)))
        vad.pop()
    t_vad = time.time() - t1
    log("[ASR/sherpa] VAD 切出 %d 段（%.1fs）" % (len(speech), t_vad))

    if not speech:
        log("[ASR/sherpa][注意] VAD 未检测到任何语音段：该音频可能几乎无人声")
        return []

    # ---- 逐段识别 ----
    t2 = time.time()
    rows = []
    for idx, (start, end, audio) in enumerate(speech):
        stream = rec.create_stream()
        stream.accept_waveform(SAMPLE_RATE, audio)
        rec.decode_stream(stream)
        text = (stream.result.text or "").strip()
        if text:
            rows.append({"start": round(start, 3), "end": round(end, 3), "text": text})
        if progress_callback and idx % 10 == 0:
            try:
                progress_callback(int(50 + (idx / max(len(speech), 1)) * 50))
            except Exception:  # noqa: BLE001
                pass
    t_asr = time.time() - t2
    if progress_callback:
        try:
            progress_callback(100)
        except Exception:  # noqa: BLE001
            pass

    chars = sum(1 for r in rows for c in r["text"] if "\u4e00" <= c <= "\u9fff")
    log("[ASR/sherpa] 识别完成 %d 段 / %d 汉字，VAD %.1fs + ASR %.1fs = %.1fs"
        % (len(rows), chars, t_vad, t_asr, time.time() - t0))
    return rows
