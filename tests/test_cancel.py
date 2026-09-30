# -*- coding: utf-8 -*-
"""
SubAI Translator —— 协作式取消测试
====================================

验证：
1. 取消令牌注册表的语义（注册 / 置位 / 查询 / 注销）
2. 流水线在检查点抛 TaskCancelled（翻译批次之间、开始重活之前）
3. 取消后不产生半成品输出文件
"""
from __future__ import annotations

import os

import pytest

from src import cancel as cancel_mod
from src import pipeline
from src.cancel import TaskCancelled, cancel, is_cancelled, raise_if_cancelled, register, unregister


class TestRegistry:
    def test_register_cancel_query_unregister(self):
        register("t1")
        assert is_cancelled("t1") is False
        assert cancel("t1") is True
        assert is_cancelled("t1") is True
        unregister("t1")
        assert is_cancelled("t1") is False
        assert cancel("t1") is False          # 已注销 -> 没命中

    def test_cancel_unknown_task(self):
        assert cancel("nonexistent-task") is False

    def test_raise_if_cancelled(self):
        raise_if_cancelled(None)              # 不抛
        raise_if_cancelled(lambda: False)     # 不抛
        with pytest.raises(TaskCancelled):
            raise_if_cancelled(lambda: True)


class TestPipelineCheckpoints:
    def test_translate_aborts_before_any_llm_call(self, monkeypatch):
        calls = {"n": 0}

        def fake(text, target, **k):
            calls["n"] += 1
            return "1. X"

        monkeypatch.setattr(pipeline, "_call_llm", fake)
        with pytest.raises(TaskCancelled):
            pipeline.translate(["甲", "乙"], "en", {}, batch_size=1,
                               use_cache=False, should_cancel=lambda: True)
        assert calls["n"] == 0, "已取消时不应发起任何 LLM 请求"

    def test_translate_stops_between_batches(self, monkeypatch):
        state = {"checks": 0}
        calls = {"n": 0}

        def should_cancel() -> bool:
            state["checks"] += 1
            return state["checks"] > 1        # 第一次检查放行，第二次起取消

        def fake(text, target, **k):
            calls["n"] += 1
            return "1. X"

        monkeypatch.setattr(pipeline, "_call_llm", fake)
        with pytest.raises(TaskCancelled):
            pipeline.translate(["甲", "乙"], "en", {}, batch_size=1,
                               use_cache=False, should_cancel=should_cancel)
        assert calls["n"] == 1, "应完成第一个批次后立刻停止（实际调用 %d 次）" % calls["n"]

    def test_run_pipeline_cancels_before_heavy_work(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        monkeypatch.setattr(pipeline, "OUT_DIR", str(out))
        monkeypatch.setattr(pipeline, "TMP_DIR", str(tmp_path / "tmp"))

        with pytest.raises(TaskCancelled):
            pipeline.run_pipeline(video=str(tmp_path / "nope.mp4"), mode="asr",
                                  should_cancel=lambda: True)

        assert not out.exists(), "取消后不应创建输出目录/半成品"

    def test_token_e2e_shape(self):
        """register 返回的事件可直接作为 should_cancel 的来源。"""
        ev = register("t2")
        try:
            assert ev.is_set() is False
            cancel_mod.cancel("t2")
            assert ev.is_set() is True
            with pytest.raises(TaskCancelled):
                raise_if_cancelled(ev.is_set)
        finally:
            unregister("t2")
