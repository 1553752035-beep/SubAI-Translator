# -*- coding: utf-8 -*-
"""
SubAI Translator —— GPU 可用性检查（不下载任何内容）
=====================================================

报告 ASR 设备判定依据，并可用 --load 真实地在目标设备上加载一次 Whisper 模型。

用法：
    .venv\\Scripts\\python.exe tools\\check_gpu.py
    .venv\\Scripts\\python.exe tools\\check_gpu.py --load
    .venv\\Scripts\\python.exe tools\\check_gpu.py --load --wav data\\extracted_audio.wav
"""
from __future__ import annotations

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.config import config, cuda_dll_dirs, ct2_cuda_supported, ensure_cuda_dll_path, free_vram_gb  # noqa: E402


def report() -> None:
    info = config.describe_asr_device()
    print("=" * 68)
    print("ASR 设备判定")
    print("=" * 68)
    print("  配置项 SUBAI_ASR_DEVICE : %s" % info["configured"])
    print("  实际生效设备            : %s / %s" % (info["effective_device"], info["compute_type"]))
    print("  CTranslate2 支持 CUDA   : %s" % info["ct2_cuda_supported"])
    print("  空闲显存 (nvidia-smi)   : %s GB" % info["free_vram_gb"])
    print("  找到的 CUDA DLL 目录    : %d 个" % len(info["cuda_dll_dirs"]))
    for d in info["cuda_dll_dirs"]:
        print("      - %s" % d)
    try:
        import torch  # type: ignore
        print("  torch                   : %s (cuda_available=%s)  ← 仅作兜底,不用于最终判定"
              % (torch.__version__, torch.cuda.is_available()))
    except Exception:  # noqa: BLE001
        print("  torch                   : 未安装（不影响 ASR,本项目 GPU 能力来自 CTranslate2）")
    print()
    print("判定规则: CTranslate2 支持 CUDA  且  能找到 CUDA DLL  且  空闲显存 >= 4GB  →  cuda")
    print("          否则安全回落 cpu/int8（不会因缺库而失败）")


def try_load() -> int:
    from faster_whisper import WhisperModel

    device, compute = config.get_asr_device()
    if device == "cuda":
        ensure_cuda_dll_path()
    if not os.path.isdir(config.models_dir):
        print("[SKIP] 未找到模型目录: %s" % config.models_dir)
        return 2
    print()
    print("正在以 device=%s compute=%s 加载模型 ..." % (device, compute))
    try:
        t0 = time.time()
        WhisperModel(config.models_dir, device=device, compute_type=compute)
        print("[PASS] 模型加载成功（%.2fs）—— %s 可用" % (time.time() - t0, device))
        return 0
    except Exception as e:  # noqa: BLE001
        print("[FAIL] 以 %s 加载失败: %s" % (device, e))
        if device == "cuda":
            print("       提示: 需要 cublas/cudnn 的 DLL。可执行 tools\\build_gpu_pack.ps1 生成")
            print("       可选 GPU 包,并把其中的 cuda_dlls 放到 exe 同级目录。")
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="SubAI Translator GPU 可用性检查")
    ap.add_argument("--load", action="store_true", help="真实加载一次模型验证")
    args = ap.parse_args()

    report()
    if args.load:
        return try_load()
    return 0


if __name__ == "__main__":
    sys.exit(main())
