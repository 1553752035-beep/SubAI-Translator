# -*- coding: utf-8 -*-
"""
统一日志配置（二期新增）
========================

集中管理日志格式、级别与输出目标，保证后端服务与各模块
（retry / queue / cache / db / pipeline）日志格式一致、可观测。

使用方式：
    from src.logging_config import setup_logging
    setup_logging()  # 在应用启动时调用一次

日志级别通过环境变量 SUBAI_LOG_LEVEL 控制（DEBUG/INFO/WARNING/ERROR），
默认 INFO。重复调用幂等，不会叠加 handler。
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

# 默认日志格式：时间 [级别] 模块名: 消息
DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(level: Optional[str] = None) -> None:
    """
    初始化根日志器（幂等，重复调用不会叠加 handler）。

    Args:
        level: 日志级别（DEBUG/INFO/WARNING/ERROR），
               None 时读环境变量 SUBAI_LOG_LEVEL，默认 INFO。
    """
    global _configured
    if _configured:
        return

    if level is None:
        level = os.environ.get("SUBAI_LOG_LEVEL", "INFO").upper()

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))

    # 避免重复添加 handler
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(DEFAULT_FORMAT, DEFAULT_DATE_FORMAT))
        root.addHandler(handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取指定模块的 logger（确保已初始化统一格式）。"""
    setup_logging()
    return logging.getLogger(name)
