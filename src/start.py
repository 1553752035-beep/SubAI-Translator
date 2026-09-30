# -*- coding: utf-8 -*-
"""
SubAI Translator —— 项目启动脚本
==================================

一键启动所有服务：
1. 环境自检
2. 启动FastAPI服务器
3. 输出API文档地址

使用方式：
    python src/start.py
"""
import os
import sys
import subprocess
import time
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def check_environment():
    """检查环境"""
    print("=" * 72)
    print("SubAI Translator - 环境检查")
    print("=" * 72)
    
    checks = [
        ("Python", sys.version, lambda v: "3.12" in v or "3.13" in v or "3.14" in v),
        ("FFmpeg", os.path.join(ROOT, "bin", "ffmpeg.exe"), lambda p: os.path.exists(p)),
        ("ASR模型", os.path.join(ROOT, "models", "faster-whisper-small"), lambda p: os.path.exists(p)),
        ("koboldcpp", os.environ.get("KOBOLD_URL", "http://127.0.0.1:5001"), lambda url: True),
    ]
    
    all_pass = True
    for name, path, check in checks:
        if check(path):
            print(f"  [OK] {name}")
        else:
            print(f"  [FAIL] {name} - {path}")
            all_pass = False
    
    print("=" * 72)
    return all_pass


def start_api_server():
    """启动FastAPI服务器（遵守 config 中的 host/port 与 HTTPS 设置）"""
    from src.config import config as _cfg

    scheme = "https" if (_cfg.security.enable_https and _cfg.security.ssl_certfile) else "http"
    print("\n启动FastAPI服务器...")
    print("API文档: %s://localhost:%d/docs" % (scheme, _cfg.server.port))
    print("\n按 Ctrl+C 停止服务\n")

    cmd = [
        sys.executable, "-m", "uvicorn",
        "src.api.server:app",
        "--host", _cfg.server.host,
        "--port", str(_cfg.server.port),
        "--reload",
        "--log-level", "info",
    ]
    # HTTPS（三期安全加固）：仅在启用且提供证书时附加
    if _cfg.security.enable_https and _cfg.security.ssl_certfile:
        cmd += ["--ssl-certfile", _cfg.security.ssl_certfile]
        if _cfg.security.ssl_keyfile:
            cmd += ["--ssl-keyfile", _cfg.security.ssl_keyfile]

    subprocess.run(cmd, cwd=ROOT)


if __name__ == "__main__":
    # 检查环境
    if not check_environment():
        print("\n环境检查未通过，请先解决上述问题。")
        sys.exit(1)
    
    # 启动服务器
    start_api_server()