# -*- coding: utf-8 -*-
"""逐任务选 ASR 引擎测试。

为什么需要这个能力
------------------
实测同一段 146 秒中文游戏解说：
  SenseVoice 4.1s / Paraformer 3.9s / Qwen3 23.0s
而粤语、中英混说、英语说唱则是 Qwen3 明显更准。
如果只能全局改配置，用户换一种素材就要回设置页改一次，
批量处理混合素材时不可能做到。

本文件验证「逐任务覆盖」这条链路没有断点：
请求字段 → 校验 → 队列参数 → 子进程 payload → run_pipeline → asr_segments。
"""
import inspect

import pytest
from fastapi import HTTPException

from src.api.server import VALID_ASR_ENGINES, normalize_asr_engine
from src import pipeline


# ---------------- 引擎名校验 ----------------

@pytest.mark.parametrize("value,expect", [
    (None, None),
    ("", None),
    ("   ", None),
    ("whisper", "whisper"),
    ("sensevoice", "sensevoice"),
    ("SENSEVOICE", "sensevoice"),
    ("  qwen3  ", "qwen3"),
    ("Paraformer", "paraformer"),
    ("firered", "firered"),
])
def test_normalize_valid(value, expect):
    assert normalize_asr_engine(value) == expect


@pytest.mark.parametrize("bad", ["xxx", "gpt", "sense voice", "sensevoice2", "1"])
def test_normalize_rejects_unknown(bad):
    """未知引擎必须 400，且报错里列出可选值。

    否则会一路传到子进程深处才失败，用户看到「任务失败」
    却完全看不出是自己填错了引擎名。
    """
    with pytest.raises(HTTPException) as ei:
        normalize_asr_engine(bad)
    assert ei.value.status_code == 400
    assert "未知的 ASR 引擎" in ei.value.detail
    for name in VALID_ASR_ENGINES:
        assert name in ei.value.detail


def test_valid_engines_list():
    assert set(VALID_ASR_ENGINES) == {
        "whisper", "sensevoice", "paraformer", "qwen3", "firered"}


# ---------------- 链路参数存在性 ----------------

def test_run_pipeline_accepts_asr_engine():
    params = inspect.signature(pipeline.run_pipeline).parameters
    assert "asr_engine" in params
    assert params["asr_engine"].default is None      # 缺省不改行为


def test_asr_segments_accepts_engine():
    params = inspect.signature(pipeline.asr_segments).parameters
    assert "engine" in params
    assert params["engine"].default is None


def test_worker_forwards_asr_engine():
    """worker 子进程必须把 payload 里的 asr_engine 传下去。

    这条容易被漏：worker 是独立进程入口，参数是一个个显式列出来的，
    新增字段不写进去的话，主进程传了也不会生效（静默失效）。
    """
    src = open(pipeline.__file__.replace("pipeline.py", "worker.py"),
               encoding="utf-8").read()
    assert "asr_engine=payload.get(\"asr_engine\")" in src


def test_transcode_request_has_field():
    from src.api.server import TranscodeRequest, BatchTranscodeItem
    assert "asr_engine" in TranscodeRequest.model_fields
    assert "asr_engine" in BatchTranscodeItem.model_fields
    # 默认 None = 用全局配置
    assert TranscodeRequest(video_path="a.mp4").asr_engine is None


def test_submit_passes_engine_to_callback():
    """_submit_one_transcode 必须把校验后的引擎名放进队列参数。"""
    import src.api.server as S
    src = inspect.getsource(S._submit_one_transcode)
    assert "normalize_asr_engine" in src
    assert "asr_engine=_engine" in src


def test_process_task_accepts_asr_engine():
    import src.api.server as S
    params = inspect.signature(S.process_transcode_task).parameters
    assert "asr_engine" in params


def test_payload_includes_asr_engine():
    """process_transcode_task 构造的 worker payload 必须带 asr_engine。"""
    import src.api.server as S
    src = inspect.getsource(S.process_transcode_task)
    assert '"asr_engine": asr_engine' in src


# ---------------- 引擎参数真正生效 ----------------

def test_asr_segments_uses_engine_override(monkeypatch):
    """传 engine 时必须覆盖全局配置，而不是忽略它。

    做法：把全局配置设成 whisper，传 engine=sensevoice，
    看它走的是不是 sherpa 分支（sherpa 分支会因为缺模型抛特定错误，
    而 whisper 分支不会 —— 用这个差异证明真的切换了）。
    """
    from src import config as config_module
    monkeypatch.setattr(config_module.config.asr, "engine", "whisper", raising=False)

    # 让 sherpa 模型探测返回缺失，触发明确的 sherpa 错误
    import src.asr_sherpa as sherpa_mod
    monkeypatch.setattr(sherpa_mod, "models_available",
                        lambda: {"sensevoice": False, "vad": True})

    with pytest.raises(RuntimeError) as ei:
        pipeline.asr_segments("dummy.wav", None, engine="sensevoice")
    assert "sensevoice" in str(ei.value)
    assert "模型未安装" in str(ei.value)


def test_asr_segments_default_uses_global(monkeypatch):
    """不传 engine 时读全局配置（零行为变化）。"""
    from src import config as config_module
    monkeypatch.setattr(config_module.config.asr, "engine", "sensevoice", raising=False)

    import src.asr_sherpa as sherpa_mod
    monkeypatch.setattr(sherpa_mod, "models_available",
                        lambda: {"sensevoice": False, "vad": True})

    with pytest.raises(RuntimeError) as ei:
        pipeline.asr_segments("dummy.wav", None)      # 不传 engine
    assert "sensevoice" in str(ei.value)