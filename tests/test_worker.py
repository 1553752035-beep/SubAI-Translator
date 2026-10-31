# -*- coding: utf-8 -*-
"""进程隔离与「假字幕」回归测试。

这里盯住两个真实出过的问题：

1. **假字幕（严重）**：抽音轨失败时，旧实现检查的是固定的
   \`tmp/audio16k.wav\` 是否存在 —— 那个文件是**上一次任务留下的**，
   于是检查通过，把上一个视频的语音当成本次输入，产出完全错误的字幕。
   症状极具欺骗性：**传一个不存在的视频路径，居然"成功"输出字幕。**

2. **原生崩溃拖垮整个服务**：CTranslate2 / sherpa-onnx / onnxruntime
   都是 C++ 库，崩溃不走 Python 异常，try/except 拦不住。
   必须靠进程隔离，让单个任务崩掉而不是整个后端消失。
"""
import os
import subprocess
import sys

import pytest

from src import worker


# ---------------- 假字幕回归（最重要） ----------------

def test_extract_audio_rejects_missing_video(tmp_path):
    """不存在的视频必须立刻报错，绝不能产出字幕。

    旧实现的 bug 路径就在这里：它不校验输入，只看输出文件存不存在，
    而输出文件名是固定的，于是读到上一次的残留音频。
    """
    from src.pipeline import extract_audio
    missing = str(tmp_path / "definitely_not_here.mp4")
    with pytest.raises(FileNotFoundError) as ei:
        extract_audio(missing)
    assert "不存在" in str(ei.value)


def test_extract_audio_uses_unique_filename(tmp_path, monkeypatch):
    """每次抽音轨必须用独立文件名 —— 固定名会并发覆盖 + 读到残留。"""
    from src import pipeline

    monkeypatch.setattr(pipeline, "TMP_DIR", str(tmp_path))
    # 造两个极短的合法音频当「视频」
    srcs = []
    import wave
    for i in range(2):
        p = tmp_path / ("in%d.wav" % i)
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x00\x01" * 16000)
        srcs.append(str(p))

    a = pipeline.extract_audio(srcs[0])
    b = pipeline.extract_audio(srcs[1])
    assert a != b, "两次抽音轨不能写同一个文件"
    assert os.path.isfile(a) and os.path.isfile(b)
    for p in (a, b):
        os.remove(p)


def test_extract_audio_cleans_up_on_failure(tmp_path, monkeypatch):
    """失败时不能留下半成品文件（否则下次可能被误读）。"""
    from src import pipeline
    monkeypatch.setattr(pipeline, "TMP_DIR", str(tmp_path))
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video at all")
    with pytest.raises(RuntimeError):
        pipeline.extract_audio(str(bad))
    leftovers = [p for p in os.listdir(tmp_path) if p.startswith("audio16k_")]
    assert leftovers == [], "失败应清理输出，实际残留：%r" % leftovers


# ---------------- 退出码识别 ----------------

@pytest.mark.parametrize("code,crash", [
    (-11, True),        # SIGSEGV
    (-6, True),         # SIGABRT
    (-4, True),         # SIGILL
    (-1073741819, True),  # Windows STATUS_ACCESS_VIOLATION（有符号）
    (3221225477, True),   # 同一个值以无符号出现（0xC0000005）
    (0, False),
    (1, False),         # Python 异常退出的普通失败
    (2, False),
])
def test_is_crash(code, crash):
    assert worker.is_crash(code) is crash


def test_describe_exit_is_human_readable():
    """报错信息要能让人知道「是原生库崩了」，而不是只给个数字。"""
    assert "段错误" in worker.describe_exit(-11)
    assert "访问冲突" in worker.describe_exit(-1073741819)
    assert worker.describe_exit(1) == "退出码 1"


def test_describe_exit_none():
    assert "未知" in worker.describe_exit(None)


# ---------------- 隔离行为 ----------------

def test_cancel_stops_promptly():
    """should_cancel 立刻为真时必须马上停下（不再跑到超时）。"""
    import time
    t0 = time.time()
    with pytest.raises(RuntimeError) as ei:
        worker.run_isolated({"video": "C:/nope.mp4"}, should_cancel=lambda: True, timeout=120)
    assert "取消" in str(ei.value)
    assert time.time() - t0 < 30, "取消耗时过长"


def test_error_from_subprocess_propagates():
    """子进程里的 Python 异常要能带回可读信息，而不是只剩退出码。"""
    with pytest.raises(RuntimeError) as ei:
        worker.run_isolated({"video": "C:/definitely_no_such_file_xyz.mp4"}, timeout=180)
    msg = str(ei.value)
    assert msg.strip(), "错误信息不能为空"
    assert ("不存在" in msg) or ("FileNotFoundError" in msg) or ("失败" in msg)


# ---------------- 真实崩溃隔离（核心价值） ----------------

def test_native_crash_does_not_kill_parent():
    """子进程触发原生崩溃，父进程必须活着，且能认出这是「原生崩溃」。

    这是整个隔离机制存在的理由：旧实现里这个崩溃会带走整个后端进程。

    **踩过的坑**：Windows + Python 3.14 上，空指针写（`ctypes.memset(0,0,1)`）
    的退出码只是 **1**，跟普通 Python 异常完全一样；
    唯一可靠的信号是 stderr 里的 `Windows fatal exception: access violation`。
    一开始只用退出码表判断，这条测试就假阴性了（报成「普通失败」）。
    """
    script = (
        "import ctypes, faulthandler\n"
        "faulthandler.enable()\n"
        "ctypes.memset(0, 0, 1)\n"     # 空指针写 -> 访问冲突
    )
    r = subprocess.run([sys.executable, "-c", script], capture_output=True)
    err = (r.stderr or b"").decode("utf-8", "replace")
    assert r.returncode != 0, "空指针写应当让子进程异常退出"

    # 关键断言：父进程（本测试）还活着，并且能识别出这是原生崩溃
    assert worker.is_crash(r.returncode, err) is True, (
        "应识别为原生崩溃；rc=%r stderr=%r" % (r.returncode, err[:200])
    )
    # 反例：普通 Python 异常不能被误判成崩溃
    r2 = subprocess.run([sys.executable, "-c", "raise ValueError('普通错误')"],
                        capture_output=True)
    err2 = (r2.stderr or b"").decode("utf-8", "replace")
    assert worker.is_crash(r2.returncode, err2) is False, (
        "普通 Python 异常不该被判成原生崩溃；stderr=%r" % err2[:200]
    )
