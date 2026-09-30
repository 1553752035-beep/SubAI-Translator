# -*- coding: utf-8 -*-
"""
SubAI Translator —— 环境自检（源码与绿色版通用）
=================================================

换一台机器后,先用它确认"能不能跑",而不是等到上传视频才报错。

只用 **当前安装位置** 推导全部路径（源码运行时为仓库根,绿色版为 exe 同级目录）,
不再硬编码任何绝对路径,也不假设本机装了什么。

用法:
    源码:    python tools/selfcheck.py [--full] [--json]
    绿色版:  subai-backend.exe --check [--full]

    --full  额外做真实推理抽样（加载 ASR 模型 / OCR 一帧 / 真翻译一句）,较慢
    --json  以 JSON 输出,便于脚本或 CI 消费

退出码: 0 = 无 FAIL（WARN 可接受）;1 = 存在 FAIL。
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

_PASS, _WARN, _FAIL = "pass", "warn", "fail"


def _add(out: list, section: str, name: str, status: str, detail: str, fix: str = "") -> None:
    out.append({"section": section, "name": name, "status": status, "detail": detail, "fix": fix})


# --------------------------------------------------------------------------- #
# 1. 运行环境
# --------------------------------------------------------------------------- #
CORE_MODULES = ["fastapi", "uvicorn", "pydantic", "httpx", "aiosqlite", "pydantic_settings"]
HEAVY_MODULES = ["faster_whisper", "rapidocr_onnxruntime", "cv2", "PIL", "numpy"]


def check_runtime(out: list) -> None:
    frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        _add(out, "运行环境", "Python 运行时", _PASS, "打包运行（无需外部 Python）")
    else:
        v = sys.version_info
        status = _PASS if v >= (3, 10) else _FAIL
        _add(out, "运行环境", "Python 版本", status, "%d.%d.%d" % (v[0], v[1], v[2]),
             "需要 Python 3.10 及以上" if status == _FAIL else "")

    for mod in CORE_MODULES + HEAVY_MODULES:
        try:
            m = importlib.import_module(mod)
            ver = getattr(m, "__version__", "")
            _add(out, "运行环境", mod, _PASS, str(ver) if ver else "已安装")
        except Exception as e:  # noqa: BLE001
            _add(out, "运行环境", mod, _FAIL, "导入失败: %r" % e,
                 "执行 pip install -r requirements.txt")


# --------------------------------------------------------------------------- #
# 2. FFmpeg
# --------------------------------------------------------------------------- #
def find_ffmpeg() -> str:
    from src.config import config
    for cand in (config.ffmpeg, shutil.which("ffmpeg") or ""):
        if cand and os.path.isfile(cand):
            return cand
    return ""


def check_ffmpeg(out: list) -> None:
    exe = find_ffmpeg()
    if not exe:
        _add(out, "FFmpeg", "可执行文件", _FAIL, "未找到 ffmpeg",
             "把 ffmpeg.exe 放到 <安装目录>/bin/ 下,或加入 PATH")
        return
    _add(out, "FFmpeg", "可执行文件", _PASS, exe)
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, text=True,
                           timeout=30, encoding="utf-8", errors="replace")
        first = (r.stdout or "").splitlines()[0] if r.stdout else "(无输出)"
        _add(out, "FFmpeg", "版本", _PASS, first[:110])
    except Exception as e:  # noqa: BLE001
        _add(out, "FFmpeg", "版本", _FAIL, "执行失败: %r" % e, "重新下载完整版 ffmpeg")
        return
    try:
        r = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True,
                           timeout=30, encoding="utf-8", errors="replace")
        has_x264 = "libx264" in (r.stdout or "")
        _add(out, "FFmpeg", "libx264 编码器", _PASS if has_x264 else _WARN,
             "可用（视频压制可用）" if has_x264 else "缺失（仅影响 hardsub 压制功能）",
             "" if has_x264 else "换用带 --enable-libx264 的 ffmpeg 构建")
    except Exception as e:  # noqa: BLE001
        _add(out, "FFmpeg", "libx264 编码器", _WARN, "检测失败: %r" % e)


# --------------------------------------------------------------------------- #
# 3. 模型
# --------------------------------------------------------------------------- #
MODEL_FILES = ["model.bin", "config.json", "tokenizer.json"]


def check_models(out: list) -> None:
    from src.config import config
    d = config.models_dir
    if not os.path.isdir(d):
        # 依次在 <root>/models、以及安装根的上层 models 里找现成的模型目录：
        # 源码方式运行时，安装根常常是仓库目录，而模型放在仓库的上一级。
        candidates = []
        for base in (os.path.dirname(d),
                     os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(d))), "models")):
            if os.path.isdir(base):
                candidates += [os.path.join(base, n) for n in os.listdir(base)]
        found = [c for c in candidates if os.path.isdir(c)]
        hint = ("已发现可用的模型目录: %s" % ", ".join(found[:3])) if found else ""
        _add(out, "模型", "ASR 模型目录", _FAIL, "不存在: %s" % d,
             "把 faster-whisper-small 放到该路径;" + (hint or "模型不随仓库分发,需另行下载"))
        return
    _add(out, "模型", "ASR 模型目录", _PASS, d)
    missing = [f for f in MODEL_FILES if not os.path.isfile(os.path.join(d, f))]
    _add(out, "模型", "模型文件完整性", _PASS if not missing else _FAIL,
         "关键文件齐全" if not missing else "缺少: %s" % ", ".join(missing),
         "" if not missing else "模型目录不完整,建议重新下载")


# --------------------------------------------------------------------------- #
# 4. 目录可写
# --------------------------------------------------------------------------- #
def check_dirs(out: list) -> None:
    from src.config import config
    targets = [("输出目录", config.out_dir), ("临时目录", config.tmp_dir),
               ("数据目录", os.path.dirname(config.users_db))]
    for label, path in targets:
        try:
            os.makedirs(path, exist_ok=True)
            fd, probe = tempfile.mkstemp(dir=path, prefix="_selfcheck_")
            os.close(fd)
            os.remove(probe)
            _add(out, "目录权限", label, _PASS, path)
        except Exception as e:  # noqa: BLE001
            _add(out, "目录权限", label, _FAIL, "%s 不可写: %r" % (path, e),
                 "检查磁盘空间与目录权限（避免放在 Program Files 等受保护目录）")


# --------------------------------------------------------------------------- #
# 5. 翻译后端
# --------------------------------------------------------------------------- #
def check_translation(out: list, full: bool) -> None:
    from src.config import config
    try:
        from src import llm as llm_mod
        st = llm_mod.test_endpoint(config.llm.mode, timeout=10)
        if st.get("reachable"):
            _add(out, "翻译后端", "端点连通性", _PASS,
                 "mode=%s url=%s (%s/%sms)" % (config.llm.mode, st.get("url"),
                                               st.get("method"), st.get("elapsed_ms")))
        else:
            _add(out, "翻译后端", "端点连通性", _FAIL,
                 "mode=%s 不可达: %s" % (config.llm.mode, st.get("detail")),
                 "启动本地翻译服务(如 koboldcpp)并在设置页「测试连接」;或改为云端模式")
    except Exception as e:  # noqa: BLE001
        _add(out, "翻译后端", "端点连通性", _FAIL, "检测失败: %r" % e)
        return

    if not full:
        return
    try:
        from src import pipeline
        t0 = time.time()
        text = pipeline._call_llm("你好，世界", "en", timeout=90)
        _add(out, "翻译后端", "真实翻译", _PASS if text else _FAIL,
             "%.2fs -> %s" % (time.time() - t0, text),
             "" if text else "服务返回空内容")
    except Exception as e:  # noqa: BLE001
        _add(out, "翻译后端", "真实翻译", _FAIL, "调用失败: %r" % e)


# --------------------------------------------------------------------------- #
# 6. ASR 设备
# --------------------------------------------------------------------------- #
def check_asr(out: list, full: bool) -> None:
    from src.config import config
    try:
        info = config.describe_asr_device()
    except Exception as e:  # noqa: BLE001
        _add(out, "语音识别", "设备判定", _FAIL, "判定失败: %r" % e)
        return
    dev = info.get("effective_device")
    if dev == "cuda":
        _add(out, "语音识别", "设备判定", _PASS,
             "GPU / %s（CUDA 支持=%s，DLL 目录 %d 个，空闲显存 %s GB）" % (
                 info.get("compute_type"), info.get("ct2_cuda_supported"),
                 len(info.get("cuda_dll_dirs") or []), info.get("free_vram_gb")))
    else:
        _add(out, "语音识别", "设备判定", _WARN,
             "CPU / %s（CTranslate2 CUDA=%s，CUDA DLL 目录 %d 个，空闲显存 %s GB）" % (
                 info.get("compute_type"), info.get("ct2_cuda_supported"),
                 len(info.get("cuda_dll_dirs") or []), info.get("free_vram_gb")),
             "CPU 可用但较慢;要启用 GPU 见 README「GPU 加速（可选）」")

    if not full:
        return
    audio = ""
    from src.config import config as _c
    ddir = os.path.dirname(_c.users_db)
    for cand in ("extracted_audio.wav", "tts_test.wav"):
        p = os.path.join(ddir, cand)
        if os.path.isfile(p):
            audio = p
            break
    if not audio and os.path.isdir(ddir):
        # 绿色版不一定带自检音频：数据目录下任意 .wav 都可以拿来验证识别链路
        wavs = sorted(n for n in os.listdir(ddir) if n.lower().endswith(".wav"))
        if wavs:
            audio = os.path.join(ddir, wavs[0])
    if not audio:
        _add(out, "语音识别", "真实识别", _WARN,
             "未找到可用于自检的音频（在 %s 下放任意 .wav 即可验证识别链路）" % ddir)
        return
    try:
        from faster_whisper import WhisperModel
        import src.pipeline as pl
        dev_eff, ct = _c.get_asr_device()
        if dev_eff == "cuda":
            from src.config import ensure_cuda_dll_path
            ensure_cuda_dll_path()
        model_dir = os.path.realpath(pl.MODEL_DIR)
        t0 = time.time()
        model = WhisperModel(model_dir, device=dev_eff, compute_type=ct)
        t_load = time.time() - t0
        t0 = time.time()
        segs, info = model.transcribe(audio, language="zh", beam_size=5)
        text = "".join(s.text for s in segs).strip()
        _add(out, "语音识别", "真实识别", _PASS if text else _FAIL,
             "device=%s load=%.1fs infer=%.1fs -> %s" % (dev_eff, t_load, time.time() - t0, text[:80]),
             "" if text else "识别结果为空")
    except Exception as e:  # noqa: BLE001
        _add(out, "语音识别", "真实识别", _FAIL, "推理失败: %r" % e)


# --------------------------------------------------------------------------- #
# 7. 硬字幕 OCR（仅 --full）
# --------------------------------------------------------------------------- #
def check_ocr(out: list, full: bool) -> None:
    if not full:
        return
    from src.config import config
    frame = os.path.join(os.path.dirname(config.users_db), "hardsub_frame.png")
    if not os.path.isfile(frame):
        _add(out, "硬字幕OCR", "真实识别", _WARN, "未找到自检图片 hardsub_frame.png")
        return
    try:
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        t0 = time.time()
        res, _ = engine(frame)
        text = " | ".join(x[1] for x in res) if res else ""
        _add(out, "硬字幕OCR", "真实识别", _PASS if text else _FAIL,
             "%.2fs -> %s" % (time.time() - t0, text[:90]),
             "" if text else "未识别到文本")
    except Exception as e:  # noqa: BLE001
        _add(out, "硬字幕OCR", "真实识别", _FAIL, "OCR 失败: %r" % e)


# --------------------------------------------------------------------------- #
# 8. 服务端口
# --------------------------------------------------------------------------- #
def check_port(out: list) -> None:
    from src.config import config
    host, port = config.server.host, config.server.port
    bind_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    try:
        with socket.create_connection((bind_host, port), timeout=2):
            _add(out, "服务端口", "%s:%d" % (host, port), _PASS, "已有服务在监听（后端可能已在运行）")
            return
    except OSError:
        pass
    try:
        s = socket.socket()
        s.bind((host, port))
        s.close()
        _add(out, "服务端口", "%s:%d" % (host, port), _PASS, "可绑定")
    except OSError as e:
        _add(out, "服务端口", "%s:%d" % (host, port), _FAIL, "被占用: %r" % e,
             "设置环境变量 SUBAI_SERVER_PORT 换端口后重启")


def run_checks(full: bool = False) -> list:
    out: list = []
    for fn in (check_runtime,):
        fn(out)
    check_ffmpeg(out)
    check_models(out)
    check_dirs(out)
    check_translation(out, full)
    check_asr(out, full)
    check_ocr(out, full)
    check_port(out)
    return out


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
_TAG = {_PASS: "[PASS]", _WARN: "[WARN]", _FAIL: "[FAIL]"}


def report(results: list) -> int:
    print("=" * 72)
    print("SubAI Translator 环境自检")
    print("=" * 72)
    section = None
    for r in results:
        if r["section"] != section:
            section = r["section"]
            print()
            print("-- %s " % section + "-" * (68 - len(section)))
        print("  %-6s %-22s %s" % (_TAG[r["status"]], r["name"], r["detail"]))
        if r["fix"]:
            print("         %-22s -> %s" % ("", r["fix"]))

    fails = [r for r in results if r["status"] == _FAIL]
    warns = [r for r in results if r["status"] == _WARN]
    print()
    print("=" * 72)
    print("汇总: %d 项检查 | 通过 %d | 警告 %d | 失败 %d" % (
        len(results), len(results) - len(fails) - len(warns), len(warns), len(fails)))
    if fails:
        print("判定: 存在失败项，请按上面的 -> 提示处理后重试")
    else:
        print("判定: 关键项全部通过" + ("（有警告项，见上）" if warns else "") + " — 可以开始使用")
    print("=" * 72)
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="SubAI Translator 环境自检")
    ap.add_argument("--full", action="store_true", help="额外做真实推理抽样（较慢）")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args(argv)

    results = run_checks(full=args.full)
    if args.json:
        # ensure_ascii=True：输出纯 ASCII，避免不同控制台/管道编码导致乱码
        print(json.dumps(results, ensure_ascii=True, indent=2))
        return 1 if any(r["status"] == _FAIL for r in results) else 0
    return report(results)


if __name__ == "__main__":
    sys.exit(main())
