# -*- coding: utf-8 -*-
"""非 ASCII 路径安全测试（src/native_safe.py）。

这条功能的价值在于「防静默降级」：
sherpa-onnx 的 C++ 层用窄字符 API 打开模型，Windows 代码页不是 UTF-8 时，
中文路径会被错误解码成不存在的名字。**它不报错**：
- silero VAD 构造失败后每次调用都打印 `vad is nullptr`，永远切出 0 个语音段
- 识别/降噪构造时抛 `Please check your config!`

所以测试要固定住：
1. 只有「Windows + 非 ASCII」才介入（ASCII 用户行为完全不变）
2. 暂存副本内容与原文件**逐字节一致**（模型被改一个字节就是灾难）
3. 任何失败都退回原路径，绝不让识别流程失败
"""
import hashlib
import os

import pytest

from src import native_safe as ns


# ---------------- 非 ASCII 判定 ----------------

@pytest.mark.parametrize("path,expect", [
    ("D:/SubAI-Translator/models", False),
    ("C:/Users/Administrator/AppData", False),
    ("/usr/share/fonts", False),
    ("", False),
    ("D:/中文/models", True),
    ("C:/用户/文档", True),
    ("D:/café/models", True),
    ("D:/models/模型.onnx", True),
])
def test_has_non_ascii(path, expect):
    assert ns.has_non_ascii(path) is expect


@pytest.mark.parametrize("plat,expect", [
    ("win32", True),
    ("windows", True),
    ("linux", False),
    ("darwin", False),
])
def test_needs_native_safe_only_on_windows(plat, expect):
    """非 Windows 的文件系统用 UTF-8 字节，原生库能正确打开，不需要处理。"""
    assert ns.needs_native_safe("C:/中文/model.onnx", plat) is expect


def test_needs_native_safe_ascii_never():
    """纯 ASCII 路径永远不需要处理（零行为变化）。"""
    assert ns.needs_native_safe("C:/plain/model.onnx", "win32") is False


# ---------------- 暂存目录候选 ----------------

def test_staging_dirs_non_windows_empty():
    assert ns.staging_base_dirs({}, "linux") == []


def test_staging_dirs_filters_non_ascii():
    """自身含非 ASCII 的候选必须剔除 —— 暂存到中文目录等于没暂存。"""
    env = {
        "ProgramData": "C:/ProgramData",
        "PUBLIC": "C:/中文/Public",      # 含中文，应被剔除
        "SystemDrive": "C:",
    }
    dirs = ns.staging_base_dirs(env, "win32")
    assert all(d.isascii() for d in dirs), dirs
    assert not any("中文" in d for d in dirs)


def test_staging_dirs_dedup():
    env = {"ProgramData": "C:/ProgramData", "PUBLIC": "C:/ProgramData"}
    dirs = ns.staging_base_dirs(env, "win32")
    assert len(dirs) == len(set(os.path.normcase(os.path.abspath(d)) for d in dirs))


# ---------------- ASCII 文件名 ----------------

@pytest.mark.parametrize("name,expect", [
    ("silero_vad.onnx", "silero_vad.onnx"),
    ("model.int8.onnx", "model.int8.onnx"),
    ("中文模型.onnx", "model.onnx"),
    ("模型", "model"),
    ("模型.abc", "model.abc"),
])
def test_ascii_filename(name, expect):
    assert ns._ascii_filename(name) == expect


# ---------------- 暂存：内容必须逐字节一致 ----------------

def test_stage_model_copies_bytes(tmp_path):
    """副本内容必须与原文件完全一致。模型改一个字节就是灾难。"""
    ns.reset_cache_for_test()
    src = tmp_path / "src" / "model.onnx"
    src.parent.mkdir(parents=True)
    payload = bytes((i * 7) % 256 for i in range(5000))
    src.write_bytes(payload)

    base = tmp_path / "stage"
    base.mkdir()
    out = ns.stage_model(str(src), base_dirs=[str(base)])

    assert out != str(src)
    assert os.path.isfile(out)
    assert open(out, "rb").read() == payload


def test_stage_model_content_addressed(tmp_path):
    """目录名用内容哈希，同一份文件重复暂存会复用同一路径。"""
    ns.reset_cache_for_test()
    src = tmp_path / "m.onnx"
    src.write_bytes(b"abc" * 100)
    base = tmp_path / "stage"
    base.mkdir()

    a = ns.stage_model(str(src), base_dirs=[str(base)])
    ns.reset_cache_for_test()          # 模拟新进程，绕过内存缓存
    b = ns.stage_model(str(src), base_dirs=[str(base)])
    assert a == b
    digest = hashlib.sha1(b"abc" * 100).hexdigest()[:16]
    assert digest in a


def test_stage_model_reuses_intact_copy(tmp_path):
    """已存在且完整时不再复制（避免每次启动都重写几十 MB）。"""
    ns.reset_cache_for_test()
    src = tmp_path / "m.onnx"
    src.write_bytes(b"x" * 100)
    base = tmp_path / "stage"
    base.mkdir()
    out = ns.stage_model(str(src), base_dirs=[str(base)])
    mtime1 = os.path.getmtime(out)

    ns.reset_cache_for_test()
    out2 = ns.stage_model(str(src), base_dirs=[str(base)])
    assert out2 == out
    assert os.path.getmtime(out2) == mtime1      # 没有被重写


def test_stage_model_repairs_truncated_copy(tmp_path):
    """副本被截断时必须重建，而不是照用。

    这是「加载成功但推理结果全错」的典型来源，比直接失败更难查。
    """
    ns.reset_cache_for_test()
    src = tmp_path / "m.onnx"
    payload = b"y" * 2000
    src.write_bytes(payload)
    base = tmp_path / "stage"
    base.mkdir()
    out = ns.stage_model(str(src), base_dirs=[str(base)])

    # 人为截断
    open(out, "wb").write(payload[:100])
    ns.reset_cache_for_test()
    out2 = ns.stage_model(str(src), base_dirs=[str(base)])
    assert open(out2, "rb").read() == payload


# ---------------- 失败必须退回原路径 ----------------

def test_stage_model_too_large_returns_original(tmp_path):
    """超过上限不搬（GB 级模型搬运代价太大），返回原路径。"""
    ns.reset_cache_for_test()
    src = tmp_path / "big.onnx"
    src.write_bytes(b"z" * 1000)
    base = tmp_path / "stage"
    base.mkdir()
    out = ns.stage_model(str(src), base_dirs=[str(base)], max_bytes=100)
    assert out == str(src)


def test_stage_model_missing_source_returns_original(tmp_path):
    ns.reset_cache_for_test()
    out = ns.stage_model(str(tmp_path / "nope.onnx"), base_dirs=[str(tmp_path)])
    assert out == str(tmp_path / "nope.onnx")


def test_stage_model_no_writable_base_returns_original(tmp_path):
    """所有候选目录都写不了时退回原路径，不抛异常。"""
    ns.reset_cache_for_test()
    src = tmp_path / "m.onnx"
    src.write_bytes(b"a" * 50)
    bad = tmp_path / "no_such_parent" / "deep" / "x"
    # 用一个不存在且无法创建的父路径模拟失败（Windows 上盘符不存在）
    out = ns.stage_model(str(src), base_dirs=["Z:/definitely/not/exist"])
    assert out == str(src)


# ---------------- ensure_native_safe 短路逻辑 ----------------

def test_ensure_ascii_path_unchanged(tmp_path):
    """ASCII 路径原样返回，不做任何 I/O。"""
    p = tmp_path / "m.onnx"
    p.write_bytes(b"1")
    assert ns.ensure_native_safe(str(p), platform="win32") == str(p)


def test_ensure_empty_returns_empty():
    assert ns.ensure_native_safe("", platform="win32") == ""


def test_ensure_missing_file_unchanged(tmp_path):
    """文件不存在时原样返回（让调用方自己报「模型缺失」）。"""
    p = str(tmp_path / "中文" / "nope.onnx")
    assert ns.ensure_native_safe(p, platform="win32") == p


def test_ensure_non_windows_unchanged(tmp_path):
    p = tmp_path / "中文.onnx"
    p.write_bytes(b"1")
    assert ns.ensure_native_safe(str(p), platform="linux") == str(p)


# ---------------- 目录暂存 ----------------

def test_ensure_dir_copies_tree(tmp_path):
    """目录暂存要把整个目录（含子目录）搬过去。"""
    ns.reset_cache_for_test()
    d = tmp_path / "模型目录"
    (d / "sub").mkdir(parents=True)
    (d / "a.onnx").write_bytes(b"aaa")
    (d / "sub" / "b.txt").write_bytes(b"bbb")

    out = ns.ensure_dir_native_safe(str(d), platform="win32")
    assert out != str(d)
    assert os.path.isfile(os.path.join(out, "a.onnx"))
    assert os.path.isfile(os.path.join(out, "sub", "b.txt"))


def test_ensure_dir_ascii_unchanged(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    assert ns.ensure_dir_native_safe(str(d), platform="win32") == str(d)


# ---------------- 与 asr_sherpa 的集成 ----------------

def test_asr_sherpa_exposes_safe_helpers():
    """asr_sherpa 必须提供 _safe / _safe_dir，且它们不抛异常。"""
    from src import asr_sherpa
    assert asr_sherpa._safe("") == ""
    assert asr_sherpa._safe("C:/nope/x.onnx") == "C:/nope/x.onnx"
    assert asr_sherpa._safe_dir("") == ""


def test_asr_sherpa_model_paths_go_through_safe():
    """VAD / 降噪模型喂给原生库前必须过 _safe。

    漏掉的话打包到中文路径下会静默降级（永远 0 个语音段），
    而开发环境用相对路径测不出来。
    """
    import inspect
    from src import asr_sherpa
    src = inspect.getsource(asr_sherpa)
    assert "_safe(VAD_MODEL)" in src
    assert "_safe(DENOISE_MODEL)" in src
    assert "_safe_dir(SENSEVOICE_DIR)" in src
    assert "_safe_dir(PARAFORMER_DIR)" in src