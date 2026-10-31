# -*- coding: utf-8 -*-
"""sherpa-onnx 引擎接入的单元测试。

只测**不需要真实模型**的部分（配置默认值、分流语义、错误提示），
真实推理由 integration 用例按模型是否存在自动跳过。

设计意图：默认 CI 环境没有 446MB 模型，不能让测试因此失败；
但**分流逻辑本身**必须有测试，否则线上切引擎会静默走错分支。
"""
import os

import pytest

from src.config import config


# ---------- 配置默认值：这些默认值决定「不装模型的老用户行为不变」 ----------

def test_default_engine_is_whisper():
    """默认必须是 whisper —— 未安装 sherpa 模型的用户行为不能变。"""
    assert config.asr.engine == "whisper"


def test_denoise_default_off():
    """GTCRN 降噪默认关：实测会把「有敌人」改成「就敌人」，属引入新错误。"""
    assert config.asr.denoise is False


def test_sensevoice_itn_default_on():
    """SenseVoice 逆文本规整默认开：字幕里「4246」比「四千二百四十六」可读。"""
    assert config.asr.sensevoice_itn is True


def test_vad_defaults_match_reference():
    """VAD 默认值对齐 Silero 官方推荐（与 SmartSub 一致）。"""
    assert config.asr.vad_threshold == 0.5
    assert config.asr.vad_min_silence_ms == 100
    assert config.asr.vad_min_speech_ms == 250
    assert config.asr.vad_max_speech_sec == 0.0


# ---------- 分流语义：引擎名的解析规则 ----------

SHERPA_ENGINES = ("sensevoice", "paraformer")


def _resolve(engine):
    """复刻 pipeline.asr_segments 开头的判定逻辑，用于单测其语义。

    直接测完整 asr_segments 需要 mock faster-whisper 的 Transcriber 全部字段，
    mock 不全反而测不到分流本身，故这里把判定规则抽出来单独验证。
    规则变更时必须同步改这里与 pipeline 的实现 —— 两边都是三行，成本可接受。
    """
    e = (engine or "whisper").strip().lower()
    return "sherpa" if e in SHERPA_ENGINES else "whisper"


@pytest.mark.parametrize("engine", ["sensevoice", "paraformer", "SenseVoice", "  PARA former  ".replace(" ", ""), "Paraformer"])
def test_sherpa_engine_names_resolve_to_sherpa(engine):
    """引擎名大小写与空白不该影响分流结果。"""
    assert _resolve(engine) == "sherpa"


@pytest.mark.parametrize("engine", ["whisper", "", None, "unknown", "faster-whisper"])
def test_other_engine_names_fall_back_to_whisper(engine):
    """未知 / 空引擎名必须回落到 whisper，不能静默选 sherpa。"""
    assert _resolve(engine) == "whisper"


# ---------- 模型探测：缺失时必须如实报告 ----------

def test_models_available_reports_all_keys():
    """模型不全时必须如实报告 False，供上层给出可操作的错误信息。

    [2026-10-25] 断言从「精确等于」改成「必须包含」：
    新增引擎（qwen3 / firered）会让 key 集合增长，
    精确相等会在每次扩充引擎时无意义地失败，
    而这条测试真正要保证的是「每个已知引擎都有对应字段且是 bool」。
    """
    from src.asr_sherpa import models_available

    info = models_available()
    assert {"sensevoice", "paraformer", "qwen3", "firered", "vad", "denoise"} <= set(info)
    assert all(isinstance(v, bool) for v in info.values())


def test_sherpa_module_imports_without_model():
    """模块本身必须能在没有模型、甚至没装 sherpa-onnx 的环境里 import。

    否则 pipeline.py 顶层的分流判断会在 import 期就炸掉，
    连 whisper 路径都不可用 —— 那是最坏的情况。
    """
    import importlib
    import src.asr_sherpa as m
    importlib.reload(m)
    assert callable(m.transcribe)


def test_missing_model_raises_actionable_error(monkeypatch, tmp_path):
    """模型缺失时的报错必须指出「缺什么、该放哪」，而不是一句 KeyError。"""
    from src import asr_sherpa

    monkeypatch.setattr(asr_sherpa, "SENSEVOICE_DIR", str(tmp_path / "nope"))
    with pytest.raises(RuntimeError) as ei:
        asr_sherpa._get_recognizer("sensevoice")
    msg = str(ei.value)
    assert "模型未安装" in msg
    assert str(tmp_path / "nope") in msg


# ---------- 真实推理（可选） ----------

@pytest.mark.skipif(
    not os.getenv("SUBAI_TEST_WAV"),
    reason="需要 SUBAI_TEST_WAV 指向一段 16k 单声道 wav",
)
@pytest.mark.parametrize("engine", ["sensevoice", "paraformer"])
def test_real_transcribe(engine):
    """真实推理：确认能产出段落、时间轴单调递增、文本非空。"""
    from src.asr_sherpa import models_available, transcribe

    if not models_available().get(engine):
        pytest.skip("%s 模型未安装" % engine)

    wav = os.environ["SUBAI_TEST_WAV"]
    if not os.path.isfile(wav):
        pytest.skip("SUBAI_TEST_WAV 指向的文件不存在")

    rows = transcribe(wav, engine)
    assert isinstance(rows, list)
    for r in rows:
        assert set(r) >= {"start", "end", "text"}
        assert 0 <= r["start"] <= r["end"]
        assert r["text"].strip()
    for a, b in zip(rows, rows[1:]):
        assert b["start"] >= a["start"]
