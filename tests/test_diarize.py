# -*- coding: utf-8 -*-
"""说话人分离测试（src/diarize.py）。

分两层：
- **纯逻辑层**（不需要模型文件）：说话人贴附、编号重排、前缀生成。
  这层是真正容易出错的地方，必须全覆盖。
- **真实推理层**：模型就绪时才跑，缺模型时 skip（CI 环境常见）。

贴附逻辑的重点
-------------
ASR 的行切分和分离的时间片**不可能对齐**：一个按语义标点切，一个按声学停顿切。
所以必须用「重叠时长最大」判定归属，不能用「包含关系」。
这个用例要能抓住「改成包含判定」的回归。
"""
import os
import wave

import pytest

from src import diarize


# ---------------- 纯逻辑：speaker 贴附 ----------------

def test_assign_picks_max_overlap_not_containment():
    """一行字幕跨两个说话人时，归重叠更长的那个。

    rows[0] = 0~3.0s，与 SPEAKER_0(0~2.5) 重叠 2.5s，与 SPEAKER_1(2.5~3.0) 重叠 0.5s
    -> 应归 SPEAKER_0。若实现改成「谁包含起点就归谁」会误判。
    """
    rows = [{"start": 0.0, "end": 3.0, "text": "a"}]
    diar = [
        {"start": 0.0, "end": 2.5, "speaker": 0},
        {"start": 2.5, "end": 3.0, "speaker": 1},
    ]
    st = diarize.assign_speakers(rows, diar)
    assert rows[0]["speaker"] == 0
    # speaker_count 是「分离出几个人」（看 diar），不是「字幕行里出现几个」
    assert st["speaker_count"] == 2
    assert st["speakers_in_rows"] == 1
    assert st["labeled"] == 1


def test_assign_handles_no_overlap_as_minus_one():
    """完全没有重叠的行（静音、纯音乐）标 -1，不强行归给某人。"""
    rows = [{"start": 10.0, "end": 12.0, "text": "静音段"}]
    diar = [{"start": 0.0, "end": 5.0, "speaker": 0}]
    st = diarize.assign_speakers(rows, diar)
    assert rows[0]["speaker"] == -1
    assert st["unlabeled"] == 1
    assert st["speaker_count"] == 1


def test_assign_empty_diarization():
    rows = [{"start": 0.0, "end": 1.0, "text": "x"}]
    st = diarize.assign_speakers(rows, [])
    assert rows[0]["speaker"] == -1
    assert st["segments"] == 0
    assert st["labeled"] == 0


def test_assign_bad_row_tolerated():
    """坏行标 -1 而不是整批失败。"""
    rows = [{"start": "坏", "end": 1.0, "text": "x"},
            {"start": 0.0, "end": 1.0, "text": "好的"}]
    diar = [{"start": 0.0, "end": 1.0, "speaker": 0}]
    diarize.assign_speakers(rows, diar)
    assert rows[0]["speaker"] == -1
    assert rows[1]["speaker"] == 0


def test_assign_counts():
    rows = [
        {"start": 0.0, "end": 1.0, "text": "a"},
        {"start": 1.0, "end": 2.0, "text": "b"},
        {"start": 50.0, "end": 51.0, "text": "c"},
    ]
    diar = [{"start": 0.0, "end": 1.5, "speaker": 0},
            {"start": 1.5, "end": 2.0, "speaker": 1}]
    st = diarize.assign_speakers(rows, diar)
    assert st["speaker_count"] == 2
    assert st["labeled"] == 2
    assert st["unlabeled"] == 1
    # 1~2s 行与两条分离片段各重叠 0.5s（并列），约定归靠前的一条
    assert rows[1]["speaker"] == 0


# ---------------- 纯逻辑：编号重排 ----------------

def test_renumber_by_first_appearance():
    """聚类编号按首次出现顺序重排。

    动机：聚类算法给的编号无语义，同一素材两次运行可能把同一个人编成 0 或 3。
    按出现顺序重编后，「SPEAKER_00 永远是最先开口的人」，重跑结果一致。
    """
    segs = [
        {"start": 0.0, "end": 1.0, "speaker": 7},
        {"start": 1.0, "end": 2.0, "speaker": 3},
        {"start": 2.0, "end": 3.0, "speaker": 7},
        {"start": 3.0, "end": 4.0, "speaker": 9},
    ]
    diarize._renumber_by_first_appearance(segs)
    assert [s["speaker"] for s in segs] == [0, 1, 0, 2]


def test_renumber_is_idempotent():
    segs = [{"start": 0, "end": 1, "speaker": 0}, {"start": 1, "end": 2, "speaker": 1}]
    diarize._renumber_by_first_appearance(segs)
    assert [s["speaker"] for s in segs] == [0, 1]


# ---------------- 纯逻辑：前缀 ----------------

def test_speaker_prefix():
    assert diarize.speaker_prefix(0) == "SPEAKER_00"
    assert diarize.speaker_prefix(12) == "SPEAKER_12"
    assert diarize.speaker_prefix(-1) == ""
    assert diarize.speaker_prefix(None) == ""


def test_speaker_prefix_custom_format():
    assert diarize.speaker_prefix(3, "说话人%d") == "说话人3"


# ---------------- 模型就绪检查 ----------------

def test_models_available_returns_dict():
    m = diarize.models_available()
    assert set(m) == {"segmentation", "embedding", "dir"}
    assert isinstance(m["segmentation"], bool)
    assert isinstance(m["embedding"], bool)


def test_available_is_bool():
    assert isinstance(diarize.available(), bool)


# ---------------- 真实推理（模型缺失时 skip） ----------------

needs_models = pytest.mark.skipif(
    not diarize.available(), reason="说话人分离模型未下载"
)


@needs_models
def test_real_diarize_on_silence(tmp_path):
    """纯静音应当分离出 0 段（或极少段），不能凭空造出说话人。

    合成 2 秒 16kHz 静音 wav。这条同时验证：读 wav 的路径通、
    模型能加载、返回结构正确。
    """
    p = tmp_path / "silence.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 32000)
    segs = diarize.diarize(str(p))
    assert isinstance(segs, list)
    assert len(segs) <= 2, "静音不该分离出多个说话人：%r" % segs


@needs_models
def test_real_diarize_missing_file():
    with pytest.raises(FileNotFoundError):
        diarize.diarize(str("C:/definitely_not_here.wav"))


def test_missing_models_raises_actionable_error(monkeypatch, tmp_path):
    """模型缺失时必须给出可执行的报错，而不是 None 或静默返回空列表。"""
    monkeypatch.setattr(diarize, "SEG_MODEL", str(tmp_path / "nope.onnx"))
    monkeypatch.setattr(diarize, "EMB_MODEL", str(tmp_path / "nope2.onnx"))
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    with pytest.raises(RuntimeError) as ei:
        diarize.diarize(str(wav))
    msg = str(ei.value)
    assert "模型未就绪" in msg
    assert "segmentation=False" in msg

def test_num_clusters_forced_two_speakers():
    """强制 2 人时必须真的分出 2 人（用两个不同音源验证）。

    **素材设计是这条测试的全部价值**：必须用两个**不同的人**（真人 + TTS），
    不能用同一段音频的两段拼接 —— 同一人声纹相似，分成 1 人是正确行为。
    这个坑我踩过两次（LESSONS L-001 / L-007），所以把素材构造也写进测试。
    """
    import subprocess
    import wave
    import numpy as np

    src = r"C:/tmp/ab_test/v2.wav"
    if not os.path.isfile(src):
        pytest.skip("缺少测试音频 C:/tmp/ab_test/v2.wav")

    ff = r"D:/SubAI-Translator/bin/ffmpeg.exe"
    if not os.path.isfile(ff):
        pytest.skip("缺少 ffmpeg")

    # 用 TTS 生成第二个人声（与源音频的主人明显不同）
    ps = (
        'Add-Type -AssemblyName System.Speech; '
        '$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; '
        '$s.SetOutputToWaveFile("C:/tmp/ab_test/_tts_test.wav"); '
        '$s.Speak("Hello, this is a different voice speaking."); $s.Dispose()'
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=90)
    tts = r"C:/tmp/ab_test/_tts_test.wav"
    if not os.path.isfile(tts):
        pytest.skip("TTS 不可用")

    out = r"C:/tmp/ab_test/_mixed_test.wav"
    r = subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-i", tts,
         "-filter_complex",
         "[0:a]atrim=0:20,asetpts=N/SR/TB[a];"
         "[1:a]aformat=sample_rates=16000:channel_layouts=mono[b];"
         "[a][b]concat=n=2:v=0:a=1[o]",
         "-map", "[o]", "-ar", "16000", "-ac", "1", out],
        capture_output=True)
    if r.returncode != 0:
        pytest.skip("音频拼接失败")

    segs = diarize.diarize(out, num_speakers=2)
    n = len(set(s["speaker"] for s in segs))
    assert n == 2, "强制 2 人应分出 2 人，实际 %d 人：%r" % (n, segs)

