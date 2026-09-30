# -*- coding: utf-8 -*-
"""
SubAI Translator —— ASR 设备选择测试（v3.1.2）
================================================

锁定"不再依赖 torch 判断 GPU"的行为：
CTranslate2 支持 + CUDA DLL 可用 + 显存充足 才走 cuda，否则安全回落 cpu。
"""
from __future__ import annotations

import os

from src import config as config_mod
from src.config import config


class TestExplicitDevice:
    def test_explicit_cuda(self, monkeypatch):
        monkeypatch.setattr(config.asr, "device", "cuda")
        assert config.get_asr_device() == ("cuda", "float16")

    def test_explicit_cpu(self, monkeypatch):
        monkeypatch.setattr(config.asr, "device", "cpu")
        assert config.get_asr_device() == ("cpu", "int8")

    def test_explicit_cuda_keeps_configured_compute_type(self, monkeypatch):
        monkeypatch.setattr(config.asr, "device", "cuda")
        monkeypatch.setattr(config.asr, "compute_type", "int8_float16")
        assert config.get_asr_device() == ("cuda", "int8_float16")


class TestAutoDevice:
    def _set(self, monkeypatch, ct2, dlls, vram):
        monkeypatch.setattr(config.asr, "device", "auto")
        monkeypatch.setattr(config.asr, "compute_type", "auto")
        monkeypatch.setattr(config_mod, "ct2_cuda_supported", lambda: ct2)
        monkeypatch.setattr(config_mod, "cuda_dll_dirs", lambda: dlls)
        monkeypatch.setattr(config_mod, "free_vram_gb", lambda: vram)

    def test_no_ct2_cuda(self, monkeypatch):
        self._set(monkeypatch, False, ["x"], 8.0)
        assert config.get_asr_device() == ("cpu", "int8")

    def test_no_cuda_dlls(self, monkeypatch):
        self._set(monkeypatch, True, [], 8.0)
        assert config.get_asr_device() == ("cpu", "int8")

    def test_insufficient_vram(self, monkeypatch):
        self._set(monkeypatch, True, ["x"], 1.0)
        assert config.get_asr_device() == ("cpu", "int8")

    def test_all_conditions_met(self, monkeypatch):
        self._set(monkeypatch, True, ["x"], 8.0)
        assert config.get_asr_device() == ("cuda", "float16")

    def test_vram_unknown_falls_back_to_cpu_without_cuda_torch(self, monkeypatch):
        self._set(monkeypatch, True, ["x"], None)
        assert config.get_asr_device() == ("cpu", "int8")


class TestDescribe:
    def test_describe_shape(self):
        info = config.describe_asr_device()
        assert set(info) >= {
            "configured", "effective_device", "compute_type",
            "ct2_cuda_supported", "cuda_dll_dirs", "free_vram_gb",
        }
        assert info["effective_device"] in ("cuda", "cpu")

    def test_cuda_dll_dirs_is_list(self):
        assert isinstance(config_mod.cuda_dll_dirs(), list)

    def test_optional_gpu_pack_under_install_dir_is_detected(self, tmp_path, monkeypatch):
        bin_dir = tmp_path / "cuda_dlls" / "cublas" / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "cublas64_12.dll").write_bytes(b"x")
        monkeypatch.setattr(config_mod, "_project_root", lambda: str(tmp_path))
        found = config_mod.cuda_dll_dirs()
        assert any(d.endswith(os.path.join("cublas", "bin")) for d in found)
