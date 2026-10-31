# -*- coding: utf-8 -*-
"""五期：turbo 模型下载管理的状态与校验逻辑"""
import os
import src.asr_model as am


def test_installed_false_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(am, "turbo_dir", lambda: str(tmp_path))
    assert am.installed() is False
    assert am.current_bytes() == 0


def test_installed_true_when_size_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(am, "turbo_dir", lambda: str(tmp_path))
    monkeypatch.setattr(am, "MODEL_REF_BYTES", 1000)
    with open(os.path.join(tmp_path, "model.bin"), "wb") as f:
        f.write(b"x" * 1000)
    assert am.installed() is True
    assert am.current_bytes() == 1000


def test_installed_false_when_too_small(tmp_path, monkeypatch):
    """不完整（<95%）绝不能算已安装 —— 否则会写进配置、启动后加载失败。"""
    monkeypatch.setattr(am, "turbo_dir", lambda: str(tmp_path))
    monkeypatch.setattr(am, "MODEL_REF_BYTES", 1000)
    with open(os.path.join(tmp_path, "model.bin"), "wb") as f:
        f.write(b"x" * 900)
    assert am.installed() is False


def test_status_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(am, "turbo_dir", lambda: str(tmp_path))
    monkeypatch.setattr(am, "MODEL_REF_BYTES", 1000)
    st = am.DL.status()
    for k in ("state", "downloaded", "total", "progress", "installed", "model_dir", "active_model_dir"):
        assert k in st, "缺少字段 " + k


def test_cleanup_removes_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(am, "turbo_dir", lambda: str(tmp_path))
    p = os.path.join(tmp_path, "model.bin")
    with open(p, "wb") as f:
        f.write(b"x" * 10)
    am._cleanup(str(tmp_path))
    assert not os.path.exists(p)
