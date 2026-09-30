# -*- coding: utf-8 -*-
"""
SubAI Translator —— 环境自检（源码入口）
=========================================

真正的实现已统一到 src/selfcheck.py，源码与绿色版共用同一套检查逻辑：
    subai-backend.exe --check [--full]

用法:
    python tools/selfcheck.py [--full] [--json]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from src.selfcheck import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
