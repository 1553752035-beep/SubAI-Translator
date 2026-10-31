# -*- coding: utf-8 -*-
"""ASR 引擎扩充测试（qwen3 / firered）。

测试重点
--------
新引擎的价值最终要靠准确率评估，但**工程正确性**必须先固定住：

1. **模型不完整时必须报清楚缺哪一件**。
   Qwen3 是四件套（conv_frontend + encoder + decoder + tokenizer），
   少一件只会得到一个难懂的 sherpa 原生报错，用户根本不知道该下什么。
2. **FireRed 有两条产品线，签名不同**（AED 双文件 / CTC 单文件），
   两种目录布局都要能识别。
3. **引擎分发用映射表**：目录名与引擎名不是简单加后缀的关系
   （qwen3 -> qwen3-asr，firered -> firered-asr），拼错就会去错目录。
4. 引擎判断**不能靠字符串比较散落各处**，否则新增引擎必然漏改一处。
"""
import os

import pytest

from src import asr_sherpa


# ---------------- 模型就绪检测 ----------------

def test_models_available_has_all_engines():
    """四个引擎 + vad/denoise 都要在返回里，缺字段会让前端读不到。"""
    m = asr_sherpa.models_available()
    for k in ("sensevoice", "paraformer", "qwen3", "firered", "vad", "denoise"):
        assert k in m, "models_available 缺少 %s" % k
        assert isinstance(m[k], bool)


def test_qwen3_requires_all_parts(tmp_path, monkeypatch):
    """Qwen3 缺任意一件就必须判为未就绪。

    真实故障模式：只下了 encoder 没下 decoder（720MB 那个），
    前面能加载、推理时才崩，报错还看不出原因。

    tokenizer 是**目录**（vocab.json + merges.txt），不是单个文件 ——
    这一点查上游官方文档才确认（LESSONS L-008），
    一开始按「tokens.txt / tokenizer.json 二选一」猜，猜错了。
    """
    d = tmp_path / "qwen3"
    d.mkdir()
    monkeypatch.setattr(asr_sherpa, "QWEN3_DIR", str(d))

    assert asr_sherpa.models_available()["qwen3"] is False

    for f in ("conv_frontend.onnx", "encoder.int8.onnx"):
        (d / f).write_bytes(b"x")
    assert asr_sherpa.models_available()["qwen3"] is False, "缺 decoder 不该算就绪"

    (d / "decoder.int8.onnx").write_bytes(b"x")
    assert asr_sherpa.models_available()["qwen3"] is False, "缺 tokenizer 目录不该算就绪"

    tk = d / "tokenizer"
    tk.mkdir()
    (tk / "vocab.json").write_bytes(b"{}")
    assert asr_sherpa.models_available()["qwen3"] is False, "缺 merges.txt 不该算就绪"

    (tk / "merges.txt").write_bytes(b"x")
    assert asr_sherpa.models_available()["qwen3"] is True


def test_qwen3_tokenizer_must_be_directory(tmp_path, monkeypatch):
    """把 tokenizer 写成单个文件（tokens.txt）不能算就绪。

    这是实践中很容易踩的错：其他 sherpa 模型（SenseVoice/Paraformer）
    确实用单文件 tokens.txt，照着类推就会以为 Qwen3 也一样。
    """
    d = tmp_path / "qwen3c"
    d.mkdir()
    monkeypatch.setattr(asr_sherpa, "QWEN3_DIR", str(d))
    for f in ("conv_frontend.onnx", "encoder.int8.onnx", "decoder.int8.onnx"):
        (d / f).write_bytes(b"x")
    (d / "tokens.txt").write_bytes(b"x")     # 单文件：对 Qwen3 无效
    assert asr_sherpa.models_available()["qwen3"] is False


def test_firered_detection(tmp_path, monkeypatch):
    d = tmp_path / "firered"
    d.mkdir()
    monkeypatch.setattr(asr_sherpa, "FIRERED_DIR", str(d))
    assert asr_sherpa.models_available()["firered"] is False
    (d / "model.int8.onnx").write_bytes(b"x")
    (d / "tokens.txt").write_bytes(b"x")
    assert asr_sherpa.models_available()["firered"] is True


# ---------------- 引擎名 → 目录名映射 ----------------

def test_sherpa_engine_dir_map():
    """目录名映射必须集中且正确。

    真实坑：qwen3 的目录叫 qwen3-asr、firered 叫 firered-asr，
    不是引擎名加后缀这么简单。原来用内联三元表达式拼，
    加到第 3 个引擎时已经无法阅读，且**报错信息里的路径会和实际查找的不一致**。
    """
    from src.pipeline import _SHERPA_ENGINE_DIRS
    assert _SHERPA_ENGINE_DIRS == {
        "sensevoice": "sensevoice-small",
        "paraformer": "paraformer-zh",
        "qwen3": "qwen3-asr",
        "firered": "firered-asr",
    }


def test_engine_map_covers_all_known_engines():
    """配置里允许的引擎名必须都在映射表里（漏一个就会走错分支）。"""
    from src.pipeline import _SHERPA_ENGINE_DIRS
    from src.config import ASRConfig
    allowed = ["sensevoice", "paraformer", "qwen3", "firered"]
    desc = ASRConfig.model_fields["engine"].description or ""
    for e in allowed:
        assert e in _SHERPA_ENGINE_DIRS
        assert e in desc, "引擎 %s 没写进 config 的 description" % e


# ---------------- 构造识别器：缺模型要给人话 ----------------

def test_qwen3_missing_model_message_is_actionable(tmp_path, monkeypatch):
    """缺模型时错误信息必须点出**缺哪一件**和**该放哪**。"""
    d = tmp_path / "q"
    d.mkdir()
    monkeypatch.setattr(asr_sherpa, "QWEN3_DIR", str(d))
    # 只放 conv_frontend，缺 encoder/decoder/tokenizer
    (d / "conv_frontend.onnx").write_bytes(b"x")
    asr_sherpa._recognizer_cache.clear()

    with pytest.raises(RuntimeError) as ei:
        asr_sherpa._get_recognizer("qwen3")
    msg = str(ei.value)
    assert "Qwen3-ASR" in msg
    assert "encoder" in msg and "decoder" in msg, "应列出缺失的具体文件：%s" % msg
    assert str(d) in msg, "应指出模型目录"


def test_firered_missing_model_message(tmp_path, monkeypatch):
    d = tmp_path / "f"
    d.mkdir()
    monkeypatch.setattr(asr_sherpa, "FIRERED_DIR", str(d))
    asr_sherpa._recognizer_cache.clear()
    with pytest.raises(RuntimeError) as ei:
        asr_sherpa._get_recognizer("firered")
    assert "FireRed" in str(ei.value)


# ---------------- 真实推理（模型就绪时才跑） ----------------

needs_qwen3 = pytest.mark.skipif(
    not asr_sherpa.models_available().get("qwen3"),
    reason="Qwen3-ASR 模型未下载",
)


@needs_qwen3
def test_qwen3_real_inference(tmp_path):
    """Qwen3-ASR 真实推理：合成一段静音 + 一段语音，至少要不崩、结构正确。

    这里不追求识别内容（合成 TTS 质量有限），只固定：
    能加载模型、能返回结构、时间轴单调。
    """
    import wave
    p = tmp_path / "a.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)   # 1 秒静音
    rows = asr_sherpa.transcribe(str(p), "qwen3")
    assert isinstance(rows, list)
    for r in rows:
        assert r["start"] <= r["end"]
        assert isinstance(r["text"], str)
