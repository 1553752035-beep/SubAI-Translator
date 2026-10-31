# -*- coding: utf-8 -*-
"""说话人分离（sherpa-onnx pyannote 分割 + 3dspeaker 嵌入）。

为什么需要
----------
现在所有字幕都是「一个说话人」。两三个人对谈的视频，字幕看不出谁在说话，
翻译出来人称代词全乱 —— 日语尤其明显（「私」和「僕」混成一句）。
分离之后每条字幕能带 `speaker` 字段，输出时可加前缀，翻译时也能作为上下文提示。

实现路线
--------
用 sherpa-onnx 自带的离线分离：**pyannote 分割模型** 找出「谁在说话」的
时间片，**3dspeaker 嵌入模型** 给每片算声纹向量，**FastClustering** 把
向量聚成 N 个说话人。这三件都是 sherpa 内部串好的，不用自己写聚类。

关键设计
--------
1. **分离与识别解耦**。分离只产出 `[(start, end, speaker_id)]` 时间片，
   不碰文本。之后用「时间重叠最大」把说话人贴到已有的 ASR 字幕行上。
   这样分离失败不影响出字幕，ASR 失败也能单独跑分离。
2. **按重叠时长而非包含关系判定**。ASR 的行切分和分离的时间片不会对齐
   （一个在语义边界切，一个在声学停顿切），必须用重叠面积算归属。
3. **说话人编号稳定**：按首次出现顺序重编为 SPEAKER_00/01/...，
   否则每次聚类编号可能不同，同一视频跑两遍字幕前缀就对不上了。
"""
from __future__ import annotations

import os
import time
from typing import Optional

# 模型目录与 asr_sherpa 用同一套推导方式（config 里没有 BASE_DIR）。
# 注意：本项目源码目录含中文（D:\SubAI-Translator\源码），sherpa 原生库在
# 非 ASCII 路径下可能静默失败；开发期用绝对路径正常，打包后需单独验证
# （已记入 KNOWN-LIMITS）。
ENGINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "sherpa", "diarization",
)
SEG_MODEL = os.path.join(ENGINE_DIR, "pyannote-segmentation.onnx")
EMB_MODEL = os.path.join(ENGINE_DIR, "3dspeaker-eres2net.onnx")


def models_available() -> dict:
    """返回各模型是否就绪。缺失不抛异常 —— 调用方按此决定是否拦路。"""
    return {
        "segmentation": os.path.isfile(SEG_MODEL) and os.path.getsize(SEG_MODEL) > 1024 * 1024,
        "embedding": os.path.isfile(EMB_MODEL) and os.path.getsize(EMB_MODEL) > 1024 * 1024,
        "dir": ENGINE_DIR,
    }


def available() -> bool:
    m = models_available()
    return bool(m["segmentation"] and m["embedding"])


# --------------------------------------------------------------------------- #
# 分离
# --------------------------------------------------------------------------- #
def diarize(wav: str, num_speakers: int = -1, threshold: float = 0.5,
            num_threads: int = 2, progress_callback=None) -> list:
    """对 wav 做说话人分离，返回 `[{"start","end","speaker"}]`（按时间排序）。

    参数
    ----
    num_speakers : -1 = 自动判断人数（推荐）；>0 = 强制指定
    threshold    : 自动判断时的聚类阈值，越小越容易拆成更多人

    异常
    ----
    模型缺失或推理失败时抛 RuntimeError，消息里带可执行的下一步。
    """
    m = models_available()
    if not (m["segmentation"] and m["embedding"]):
        raise RuntimeError(
            "说话人分离模型未就绪（segmentation=%s, embedding=%s），目录：%s"
            % (m["segmentation"], m["embedding"], ENGINE_DIR)
        )
    if not os.path.isfile(wav):
        raise FileNotFoundError("音频不存在: %s" % wav)

    import sherpa_onnx as so

    seg_cfg = so.OfflineSpeakerSegmentationModelConfig(
        pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=SEG_MODEL),
        num_threads=num_threads,
        provider="cpu",
    )
    emb_cfg = so.SpeakerEmbeddingExtractorConfig(
        model=EMB_MODEL, num_threads=num_threads, provider="cpu"
    )
    # num_clusters > 0 时强制人数，忽略 threshold；-1 时按 threshold 自动判断
    clu_cfg = so.FastClusteringConfig(num_clusters=num_speakers, threshold=threshold)
    cfg = so.OfflineSpeakerDiarizationConfig(
        segmentation=seg_cfg, embedding=emb_cfg, clustering=clu_cfg,
        min_duration_on=0.3, min_duration_off=0.5,
    )

    sd = so.OfflineSpeakerDiarization(cfg)
    if sd.sample_rate != 16000:
        raise RuntimeError("模型要求 16kHz 音频，实测 %d" % sd.sample_rate)

    t0 = time.time()
    if progress_callback:
        progress_callback("分离中", 0.0)
    audio = _read_wav_16k(wav)
    if progress_callback:
        progress_callback("分离中", 0.3)
    result = sd.process(audio).sort_by_start_time()
    if progress_callback:
        progress_callback("分离完成", 1.0)

    out = []
    for seg in result:
        out.append({
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "speaker": int(seg.speaker),
        })
    _renumber_by_first_appearance(out)
    return out


def _renumber_by_first_appearance(segs: list) -> None:
    """把聚类编号按「首次出现顺序」重编为 0,1,2...（原地修改）。

    聚类算法给的编号本身没有语义，同一素材两次运行可能把 A 编成 0 也可能编成 3。
    按首次出现顺序重编之后，只要音频一样，'SPEAKER_00 永远是最先开口的人'，
    用户重跑得到的字幕前缀才是一致的。
    """
    mapping = {}
    for s in segs:
        old = s.get("speaker")
        if old not in mapping:
            mapping[old] = len(mapping)
        s["speaker"] = mapping[old]


def _read_wav_16k(path: str):
    """读 16kHz 单声道 wav，返回 float32 numpy 数组。

    非 16k/多声道时用 ffmpeg 预处理 —— 分离模型固定 16k，喂错采样率
    会把所有人声都分错，且 sherpa 不会报错。
    """
    import wave
    import numpy as np

    try:
        with wave.open(path, "rb") as w:
            sr = w.getframerate()
            ch = w.getnchannels()
            if sr == 16000 and ch == 1:
                raw = w.readframes(w.getnframes())
                return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:  # noqa: BLE001
        pass
    # 需要转码：交给 ffmpeg
    import subprocess
    import tempfile
    from src.pipeline import ffmpeg_bin  # 延迟导入，避免循环依赖

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y",
           "-i", path, "-ar", "16000", "-ac", "1", "-f", "wav", tmp.name]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        with wave.open(tmp.name, "rb") as w:
            raw = w.readframes(w.getnframes())
        return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 贴到字幕行
# --------------------------------------------------------------------------- #
def assign_speakers(rows: list, diar: list) -> dict:
    """把分离结果贴到字幕行上，返回统计。

    归属规则：**与哪条分离片段的重叠时长最长，就归谁**。
    不用「包含关系」是因为两者切分边界不可能对齐 —— ASR 在语义标点处切，
    分离在声学停顿处切，一行字幕跨两三条分离片段是常态。

    原地给每行加 `speaker`（int）字段；无重叠的行标 -1（静音/纯音乐段）。
    """
    for r in rows:
        try:
            rs, re_ = float(r["start"]), float(r["end"])
        except (KeyError, TypeError, ValueError):
            r["speaker"] = -1
            continue
        best, best_ov = -1, 0.0
        for d in diar:
            ov = min(re_, d["end"]) - max(rs, d["start"])
            # 必须严格大于 0：重叠为 0（仅端点相接）或负（完全错开）都不算归属，
            # 否则静音行会被「归给」时间上最近但根本没重叠的说话人。
            if ov > best_ov:
                best_ov, best = ov, d["speaker"]
        r["speaker"] = best

    speakers = [r.get("speaker", -1) for r in rows]
    # speaker_count 描述的是「分离出几个说话人」（看 diar），不是「字幕行里出现几个」。
    # 两者会不一致：某个说话人的片段全被合并进相邻行时，后者会漏算，
    # 而用户想知道的显然是「这个视频里有几个人在说话」。
    diar_speakers = sorted(set(d["speaker"] for d in diar if d.get("speaker") is not None and d["speaker"] >= 0))
    row_speakers = sorted(set(s for s in speakers if s >= 0))
    return {
        "speaker_count": len(diar_speakers),
        "labeled": sum(1 for s in speakers if s >= 0),
        "unlabeled": sum(1 for s in speakers if s < 0),
        "segments": len(diar),
        "speakers_in_rows": len(row_speakers),
    }


def speaker_prefix(speaker: int, fmt: str = "SPEAKER_%02d") -> str:
    """生成说话人前缀。speaker<0 返回空串（静音行不加前缀）。"""
    if speaker is None or speaker < 0:
        return ""
    return fmt % speaker


def render_with_speakers(rows: list, texts: Optional[list] = None,
                         fmt: str = "SPEAKER_%02d",
                         separator: str = ": ") -> list:
    """给文本加说话人前缀，返回新的文本列表（不改 rows）。

    只在「开了分离且确实标出多人」时才有意义 —— 单人素材加前缀等于噪音，
    调用方应按 stats["diarization"]["speaker_count"] > 1 判断后再调。

    参数
    ----
    texts : 可选，覆盖文本（翻译流程用译文时传译文列表）
    """
    out = []
    for i, r in enumerate(rows or []):
        base = (texts[i] if texts is not None and i < len(texts) else r.get("text")) or ""
        pre = speaker_prefix(int(r.get("speaker", -1) or -1), fmt)
        out.append(("%s%s%s" % (pre, separator, base)) if pre else str(base))
    return out
