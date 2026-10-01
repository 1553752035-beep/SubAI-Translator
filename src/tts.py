# -*- coding: utf-8 -*-
"""
SubAI Translator —— 语音合成 TTS（四期 4.1）
=============================================

目标：把字幕翻译成配音音轨，并与字幕时间轴对齐。

可插拔后端：
- WindowsSapiEngine：调用系统 SAPI（离线、零额外依赖，Windows 内置中英文音色）
- EdgeTTSEngine：可选，需 pip install edge-tts 且联网（音色多、多语言）

核心流程（synthesize_segments）：
  1. 逐条字幕合成 wav
  2. fit_slot=True 时用 FFmpeg atempo 把超长音频压缩到字幕时间槽内（语速自适应）
  3. 按字幕起始时间把各段铺到时间轴上（段间补静音），产出合并配音轨
  4. 返回合并音轨、分段文件与最大同步误差

设计约定：
- 纯标准库 + FFmpeg（通过 config.ffmpeg），与 pipeline / compose 一致
- 时间轴合并用标准库 wave 直接拼 PCM，固定 24kHz/16bit/mono，避免额外依赖
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import wave
from typing import Optional

from src.config import config

_SAPI_SCRIPT = """param([string]$TextFile, [string]$OutFile, [string]$Voice, [int]$Rate = 0)
Add-Type -AssemblyName System.Speech
$text = Get-Content -LiteralPath $TextFile -Raw -Encoding UTF8
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
if ($Voice) { $s.SelectVoice($Voice) }
$s.Rate = $Rate
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(24000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($OutFile, $fmt)
$s.Speak($text)
$s.SetOutputToNull()
$s.Dispose()
Write-Output 'SYNTH_OK'
"""

_LIST_VOICES_SCRIPT = """Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Culture }
$s.Dispose()
"""

SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2  # 16bit


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #

def _run_ffmpeg(args: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(
        [config.ffmpeg, "-hide_banner", "-loglevel", "error", "-y"] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


def wav_duration(path: str) -> float:
    """返回 wav 时长（秒）。"""
    with wave.open(path, "rb") as w:
        return w.getnframes() / float(w.getframerate() or SAMPLE_RATE)


def _atempo_chain(ratio: float) -> list[float]:
    """把总变速比拆成 FFmpeg atempo 允许的 [0.5, 2.0] 链。

    ratio > 1 表示需要加速（原音频过长）；< 1 表示放慢。
    """
    if ratio <= 0:
        raise ValueError("ratio 必须为正数")
    factors: list[float] = []
    r = ratio
    while r > 2.0:
        factors.append(2.0)
        r /= 2.0
    while r < 0.5:
        factors.append(0.5)
        r /= 0.5
    factors.append(r)
    return factors


def _time_fit(src: str, dst: str, ratio: float) -> str:
    """用 atempo 把 src 变速，输出 dst。"""
    chain = ",".join("atempo=%.4f" % f for f in _atempo_chain(ratio))
    r = _run_ffmpeg(["-i", src, "-filter:a", chain, dst])
    if r.returncode != 0 or not os.path.exists(dst):
        raise RuntimeError("音频变速失败: %s" % (r.stderr or "").strip()[:300])
    return dst


def build_dub_track(clips: list[tuple[float, str]], total_duration: float,
                    out_wav: str) -> tuple[str, float]:
    """按 (起始秒, wav路径) 把各段铺到时间轴，段间补静音。

    Returns:
        (out_wav, 最大同步误差秒)
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
    max_drift = 0.0
    with wave.open(out_wav, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(SAMPLE_WIDTH)
        out.setframerate(SAMPLE_RATE)
        cursor = 0  # 已写入的采样点数
        for start, path in sorted(clips, key=lambda c: c[0]):
            with wave.open(path, "rb") as r:
                if (r.getframerate(), r.getnchannels(), r.getsampwidth()) != \
                        (SAMPLE_RATE, 1, SAMPLE_WIDTH):
                    raise ValueError("音频格式不一致（需 24kHz/16bit/mono）: %s" % path)
                frames = r.readframes(r.getnframes())

            target = int(round(start * SAMPLE_RATE))
            actual = max(target, cursor)
            max_drift = max(max_drift, abs(actual - target) / float(SAMPLE_RATE))
            if actual > cursor:
                out.writeframes(bytes((actual - cursor) * SAMPLE_WIDTH))
            out.writeframes(frames)
            cursor = actual + len(frames) // SAMPLE_WIDTH

        end = int(round(max(total_duration, 0.0) * SAMPLE_RATE))
        if end > cursor:
            out.writeframes(bytes((end - cursor) * SAMPLE_WIDTH))

    return out_wav, max_drift


# --------------------------------------------------------------------------- #
# 后端：Windows SAPI
# --------------------------------------------------------------------------- #

class WindowsSapiEngine:
    """Windows 系统语音合成（离线，零额外依赖）。"""

    name = "sapi"

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("WindowsSapiEngine 仅在 Windows 上可用")
        self._script = self._ensure_script()

    @staticmethod
    def _ensure_script() -> str:
        path = os.path.join(tempfile.gettempdir(), "subai_sapi_synth.ps1")
        with open(path, "w", encoding="ascii") as f:
            f.write(_SAPI_SCRIPT)
        return path

    @staticmethod
    def _powershell() -> str:
        return shutil.which("powershell.exe") or shutil.which("powershell") or "powershell.exe"

    def list_voices(self) -> list[dict]:
        r = subprocess.run(
            [self._powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
             _LIST_VOICES_SCRIPT],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
        voices = []
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if "|" in line:
                name, _, culture = line.partition("|")
                voices.append({"name": name.strip(), "culture": culture.strip(), "engine": self.name})
        return voices

    def synthesize(self, text: str, out_wav: str, voice: Optional[str] = None,
                   rate: int = 0) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
        txt = out_wav + ".txt"
        with open(txt, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            cmd = [self._powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", self._script, "-TextFile", txt, "-OutFile", out_wav,
                   "-Rate", str(int(rate))]
            if voice:
                cmd += ["-Voice", voice]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=300)
        finally:
            if os.path.exists(txt):
                os.remove(txt)

        if r.returncode != 0 or not os.path.exists(out_wav) or os.path.getsize(out_wav) == 0:
            raise RuntimeError("SAPI 合成失败: %s" % (r.stderr or r.stdout or "").strip()[:300])
        return out_wav


# --------------------------------------------------------------------------- #
# 后端：edge-tts（可选）
# --------------------------------------------------------------------------- #

class EdgeTTSEngine:
    """微软 edge-tts（音色多、多语言），需 pip install edge-tts 且可联网。"""

    name = "edge"

    def __init__(self) -> None:
        try:
            import edge_tts  # type: ignore
        except ImportError as e:  # pragma: no cover - 依赖缺失路径
            raise RuntimeError(
                "edge-tts 未安装：pip install edge-tts（国内可用阿里云镜像）"
            ) from e
        self._edge = edge_tts

    def list_voices(self) -> list[dict]:  # pragma: no cover - 需联网
        async def _list():
            return await self._edge.list_voices()
        try:
            raw = asyncio.run(_list())
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("获取 edge-tts 音色失败（需联网）: %s" % e) from e
        return [{"name": v.get("ShortName", ""), "culture": v.get("Locale", ""),
                 "engine": self.name} for v in raw]

    def synthesize(self, text: str, out_wav: str, voice: Optional[str] = None,
                   rate: int = 0) -> str:  # pragma: no cover - 需联网
        os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
        mp3 = out_wav + ".mp3"
        pct = "%+d%%" % (int(rate) * 10)

        async def _synth():
            comm = self._edge.Communicate(text, voice or "zh-CN-XiaoxiaoNeural", rate=pct)
            await comm.save(mp3)

        r = None
        try:
            asyncio.run(_synth())
            r = _run_ffmpeg(["-i", mp3, "-ar", str(SAMPLE_RATE), "-ac", "1",
                             "-c:a", "pcm_s16le", out_wav])
        finally:
            if os.path.exists(mp3):
                os.remove(mp3)

        if r is None or r.returncode != 0 or not os.path.exists(out_wav):
            stderr = (r.stderr if r is not None else "")
            raise RuntimeError("edge-tts 音频转换失败: %s" % stderr.strip()[:300])
        return out_wav


def get_engine(name: str = "auto"):
    """获取 TTS 后端。auto：Windows 用 SAPI，其他平台尝试 edge-tts。"""
    if name in ("auto", "sapi"):
        if os.name == "nt":
            return WindowsSapiEngine()
        if name == "sapi":
            raise RuntimeError("sapi 后端仅支持 Windows")
    if name in ("auto", "edge"):
        return EdgeTTSEngine()
    raise ValueError("未知 TTS 后端: %s" % name)


def voice_for_language(language: str, voices: list[dict]) -> Optional[str]:
    """按语言前缀（zh/en/ja/...）挑选音色名，找不到返回 None。"""
    if not language:
        return None
    lang = language.lower().replace("_", "-")
    for v in voices:
        if (v.get("culture") or "").lower().startswith(lang):
            return v.get("name")
    base = lang.split("-")[0]
    for v in voices:
        if (v.get("culture") or "").lower().startswith(base):
            return v.get("name")
    return None


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def synthesize_segments(
    segments: list[dict],
    out_dir: str,
    *,
    engine=None,
    voice: Optional[str] = None,
    rate: int = 0,
    fit_slot: bool = True,
    merged_name: str = "dub_merged.wav",
) -> dict:
    """把字幕段落合成为与时间轴对齐的配音音轨。

    Args:
        segments: [{"start": float, "end": float, "text": str}, ...]
        out_dir: 分段 wav 与合并音轨的输出目录
        engine: TTS 后端；None 时自动选择
        voice: 音色名；None 时用后端默认
        rate: 语速（SAPI -10..10；edge 以百分比换算）
        fit_slot: 超长音频是否变速压缩到字幕时间槽（保证同步误差）
        merged_name: 合并音轨文件名

    Returns:
        {"merged": str, "clips": [str], "max_drift_seconds": float, "total_seconds": float,
         "silent_clips": int, "silent_indices": [int]}
        silent_clips > 0 表示有段落"合成成功但没有声音"（常见原因：音色不支持该语言）。
    """
    engine = engine or get_engine()
    os.makedirs(out_dir, exist_ok=True)

    clips: list[tuple[float, str]] = []
    silent: list[int] = []
    for i, seg in enumerate(segments):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        raw = os.path.join(out_dir, "dub_%04d.wav" % i)
        engine.synthesize(text, raw, voice=voice, rate=rate)

        # 关键：合成"成功"不等于合成出声音。
        # SAPI 在音色不支持文本语言时会写出只有文件头、0 采样的 wav
        # （实测：英文音色读中文 -> 46 字节 / 0.000s），而 os.path.getsize 依然 > 0。
        # 这类静音若不被识别，会被 build_dub_track 补静音到时间轴，
        # 表面上"时长/同步偏差"都正常，用户却拿到一条全静音配音。
        dur = wav_duration(raw)
        if dur <= 0.01:
            silent.append(i)

        path = raw
        if fit_slot:
            slot = max(0.1, float(seg["end"]) - float(seg["start"]))
            if dur > slot * 1.05:
                path = _time_fit(raw, os.path.join(out_dir, "dub_%04d_fit.wav" % i), dur / slot)
        clips.append((float(seg["start"]), path))

    total = max((float(s["end"]) for s in segments), default=0.0)
    merged = os.path.join(out_dir, merged_name)
    merged, drift = build_dub_track(clips, total, merged)

    return {
        "merged": merged,
        "clips": [c[1] for c in clips],
        "max_drift_seconds": round(drift, 4),
        "total_seconds": round(total, 3),
        "silent_clips": len(silent),
        "silent_indices": silent,
    }
