# -*- coding: utf-8 -*-
"""五期：可选增强识别模型（faster-whisper large-v3-turbo）下载管理。

设计要点（对应验收裁决）：
1. 下载目录用**用户可写目录**（{root}/tools/models-turbo；安装包默认装在
   %LOCALAPPDATA%，per-user 可写），不写 Program Files。
2. 不依赖 PowerShell 脚本（PyInstaller 不带 tools/），用 httpx 流式下载，支持断点续传。
3. 校验：model.bin 大小达到参考值 95% 才算成功，不完整绝不写配置。
4. 生效方式：写完 .env 持久化，同时**动态更新 pipeline.MODEL_DIR** —— 不需重启后端。
5. 失败可重试（断点续传）；取消时删除半截文件。
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

import httpx

from src.config import config

REPO = "dropbox-dash/faster-whisper-large-v3-turbo"
BASE = "https://hf-mirror.com/%s/resolve/main/%%s" % REPO
FILES = ["model.bin", "config.json", "tokenizer.json", "vocabulary.json", "preprocessor_config.json"]
MODEL_REF_BYTES = 1_617_884_929      # model.bin 参考大小（Q? 官方）


def turbo_dir() -> str:
    return config.paths.resolve("{root}/tools/models-turbo")


def installed() -> bool:
    p = os.path.join(turbo_dir(), "model.bin")
    try:
        return os.path.exists(p) and os.path.getsize(p) >= MODEL_REF_BYTES * 0.95
    except OSError:
        return False


def current_bytes() -> int:
    p = os.path.join(turbo_dir(), "model.bin")
    try:
        return os.path.getsize(p) if os.path.exists(p) else 0
    except OSError:
        return 0


class DownloadState:
    def __init__(self) -> None:
        self.state = "idle"          # idle | running | done | failed | cancelled
        self.error = ""
        self.task: Optional[asyncio.Task] = None
        self.cancel = False

    def status(self) -> dict:
        from src import pipeline as pl
        return {
            "state": self.state,
            "error": self.error,
            "downloaded": current_bytes(),
            "total": MODEL_REF_BYTES,
            "progress": min(1.0, current_bytes() / MODEL_REF_BYTES) if MODEL_REF_BYTES else 0.0,
            "installed": installed(),
            "model_dir": turbo_dir(),
            "active_model_dir": getattr(pl, "MODEL_DIR", ""),
        }


DL = DownloadState()


async def _fetch_one(client: httpx.AsyncClient, name: str, dst: str) -> None:
    """单文件下载，支持断点续传（Range 头）。"""
    url = BASE % name
    have = os.path.getsize(dst) if os.path.exists(dst) else 0
    headers = {"Range": "bytes=%d-" % have} if have else {}
    async with client.stream("GET", url, headers=headers, timeout=None) as r:
        if have and r.status_code == 416:
            return  # 已经下完
        r.raise_for_status()
        mode = "ab" if (have and r.status_code == 206) else "wb"
        with open(dst, mode) as f:
            async for chunk in r.aiter_bytes(65536):
                if DL.cancel:
                    raise asyncio.CancelledError()
                f.write(chunk)


async def _run() -> None:
    d = turbo_dir()
    os.makedirs(d, exist_ok=True)
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for name in FILES:
                await _fetch_one(client, name, os.path.join(d, name))
        if not installed():
            raise RuntimeError("下载不完整（model.bin 大小不足），未写入配置")
        _activate(d)
        DL.state = "done"
    except asyncio.CancelledError:
        DL.state = "cancelled"
        _cleanup(d)
    except Exception as e:  # noqa: BLE001
        DL.state = "failed"
        DL.error = str(e)[:300]


def _cleanup(d: str) -> None:
    """取消时删掉半截文件，避免占空间。"""
    for name in FILES:
        p = os.path.join(d, name)
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def _activate(d: str) -> None:
    """持久化到 .env，并**动态更新 pipeline.MODEL_DIR**（不需重启后端）。"""
    env_path = config.paths.resolve("{root}/.env")
    try:
        lines = []
        if os.path.exists(env_path):
            with open(env_path, encoding="utf-8") as f:
                lines = [x for x in f.read().splitlines() if not x.strip().startswith("SUBAI_ASR_MODEL_DIR=")]
        lines.append("SUBAI_ASR_MODEL_DIR=%s" % d)
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass  # .env 不可写也不影响本次生效
    from src import pipeline as pl
    pl.MODEL_DIR = d


def start() -> dict:
    if DL.state == "running":
        return DL.status()
    DL.state = "running"
    DL.error = ""
    DL.cancel = False
    DL.task = asyncio.get_event_loop().create_task(_run())
    return DL.status()


def cancel() -> dict:
    DL.cancel = True
    if DL.task and not DL.task.done():
        DL.task.cancel()
    DL.state = "cancelled"
    return DL.status()
