# -*- coding: utf-8 -*-
r"""非 ASCII 路径安全：让 sherpa-onnx 原生库能打开中文路径下的模型。

根因（实测与上游确认）
----------------------
sherpa-onnx 的 C++ 层用**窄字符 API**（fopen / std::ifstream）打开模型文件，
而 Python 传进去的是 UTF-8 字节。Windows 的系统代码页不是 UTF-8 时
（中文版是 936/GBK），这些字节被当成本地代码页解码，路径变成一个不存在的名字。

具体症状（不是报错，是**静默降级**，所以特别难查）：
- silero VAD：构造函数静默失败，之后每次调用都打印 `vad is nullptr`，永远切出 0 个语音段
- 降噪 / 识别 / TTS / 说话人分离：抛 `Please check your config!`
- readWave 抛 `Failed to read ...`，writeWave 返回 false

本项目 `models/sherpa` 位于 `D:\SubAI-Translator\源码\` 下，**路径含中文**。
开发时用相对路径能跑通，**打包后必然踩这个坑**（安装目录常被用户放在中文路径）。

处理策略（按文件性质分三类）
----------------------------
1. **随包小模型**（silero_vad 约 2 MB、gtcrn 约 0.5 MB）：复制到纯 ASCII 目录，
   内容寻址（sha1 前 16 位），原生库打开副本。本模块只管这一类。
2. **用户音频**：不复制，由 Python 侧读写 wav 后再交给原生库。
3. **GB 级用户模型**：不搬（复制 900 MB 太贵），失败时给出可操作提示。

只在 Windows 且路径含非 ASCII 时介入；其余情形原样返回，
ASCII 路径用户的行为完全不变。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from typing import Optional

# 随包小模型的暂存上限。超过就不搬（GB 级模型搬运代价太大）
DEFAULT_MAX_BYTES = 64 * 1024 * 1024

_STAGING_SUBDIR = "native-models"

# 每进程缓存：源路径 -> 已确认可用的暂存副本
_staged_cache: dict = {}


def has_non_ascii(value: str) -> bool:
    """路径里是否含非 ASCII 字符（中文、带音标的拉丁字母、emoji）。

    只检查能否用 ASCII 编码，不判别字符类别 —— 原生库只认字节，
    任何非 ASCII 字节都可能被错误解码。
    """
    if not value:
        return False
    try:
        value.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def needs_native_safe(path: str, platform: Optional[str] = None) -> bool:
    """原生库是否可能打不开该路径：仅 Windows 且含非 ASCII。

    非 Windows 的文件系统用 UTF-8 字节，原生库能正确打开，不需要处理。
    """
    plat = platform if platform is not None else sys.platform
    is_win = plat.startswith("win")
    return is_win and has_non_ascii(path or "")


def staging_base_dirs(env: Optional[dict] = None,
                      platform: Optional[str] = None) -> list:
    """可用的暂存目录候选，按优先级排列。

    自身含非 ASCII 的候选被剔除 —— 暂存到中文目录等于没暂存。
    """
    plat = platform if platform is not None else sys.platform
    if not plat.startswith("win"):
        return []
    e = env if env is not None else os.environ

    candidates = []
    # 1) 临时目录（通常 %LOCALAPPDATA%\Temp，用户名是英文时最干净）
    try:
        candidates.append(os.path.join(tempfile.gettempdir(), _STAGING_SUBDIR))
    except Exception:  # noqa: BLE001
        pass
    # 2) ProgramData：用户名含中文时的首选（所有用户可建目录）
    if e.get("ProgramData"):
        candidates.append(os.path.join(e["ProgramData"], "SubAI", _STAGING_SUBDIR))
    # 3) PUBLIC
    if e.get("PUBLIC"):
        candidates.append(os.path.join(e["PUBLIC"], "SubAI", _STAGING_SUBDIR))
    # 4) 系统盘根目录
    if e.get("SystemDrive"):
        candidates.append(os.path.join(e["SystemDrive"] + os.sep, "SubAI", _STAGING_SUBDIR))

    out = []
    seen = set()
    for d in candidates:
        if not d or has_non_ascii(d):
            continue
        key = os.path.normcase(os.path.abspath(d))
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
    return out


def _ascii_filename(name: str) -> str:
    """把文件名里的非 ASCII 换成下划线；主干全没了就退回 model + 原扩展名。"""
    cleaned = "".join(ch if 32 <= ord(ch) < 127 else "_" for ch in name)
    stem, ext = os.path.splitext(cleaned)
    if not any(ch.isalnum() for ch in stem):
        return "model" + ext
    return cleaned


def _is_intact_copy(target: str, digest: str, size: int) -> bool:
    """目标存在、大小对、内容哈希对。

    只比大小不够：模型文件被截断但大小相同的情况虽然罕见，
    一旦发生就是「加载成功但推理结果全错」，比直接失败更难查。
    """
    try:
        if os.path.getsize(target) != size:
            return False
        with open(target, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest() == digest
    except OSError:
        return False


def _write_copy(target: str, source: str) -> None:
    """先写临时文件再改名：避免另一个进程读到写了一半的模型。"""
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = "%s.%d.tmp" % (target, os.getpid())
    try:
        shutil.copyfile(source, tmp)
        os.replace(tmp, target)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def stage_model(source_path: str,
                base_dirs: Optional[list] = None,
                max_bytes: int = DEFAULT_MAX_BYTES,
                log=None) -> str:
    """把模型复制到纯 ASCII 目录，返回副本路径。

    任何失败都返回**原路径**并记日志 —— 行为不比不处理更差。
    这是刻意的：暂存是「尽力而为」，不该因此让整个流程失败。
    """
    emit = log or (lambda msg, level="info": None)

    cached = _staged_cache.get(source_path)
    if cached:
        try:
            if os.path.getsize(cached) > 0:
                return cached
        except OSError:
            _staged_cache.pop(source_path, None)      # 副本被删，重新暂存

    try:
        size = os.path.getsize(source_path)
    except OSError as e:
        emit("native-safe: 无法读取 %s 的大小: %r" % (source_path, e), "warning")
        return source_path

    if size > max_bytes:
        emit("native-safe: %s 超过 %d 字节，不暂存" % (source_path, max_bytes),
             "warning")
        return source_path

    try:
        with open(source_path, "rb") as f:
            digest = hashlib.sha1(f.read()).hexdigest()
    except OSError as e:
        emit("native-safe: 读取 %s 失败: %r" % (source_path, e), "warning")
        return source_path

    name = _ascii_filename(os.path.basename(source_path))
    bases = base_dirs if base_dirs is not None else staging_base_dirs()
    failures = []

    for base in bases:
        target = os.path.join(base, digest[:16], name)
        try:
            if not _is_intact_copy(target, digest, size):
                _write_copy(target, source_path)
            _staged_cache[source_path] = target
            emit("native-safe: 已暂存 %s -> %s（原生库在 Windows 上打不开非 ASCII 路径）"
                 % (source_path, target), "info")
            return target
        except OSError as e:
            failures.append("%s: %r" % (base, e))

    emit("native-safe: 无法暂存 %s 到 ASCII 目录，原生库可能打不开它 (%s)"
         % (source_path, "; ".join(failures) if failures else "无可用目录"),
         "warning")
    return source_path


def ensure_native_safe(path: str,
                       base_dirs: Optional[list] = None,
                       max_bytes: int = DEFAULT_MAX_BYTES,
                       platform: Optional[str] = None,
                       log=None) -> str:
    """交给原生库之前调用：需要时返回 ASCII 副本路径，否则原样返回。

    空串原样返回（调用方自己决定怎么处理缺失的模型）。
    """
    if not path or not needs_native_safe(path, platform):
        return path
    if not os.path.isfile(path):
        return path
    return stage_model(path, base_dirs=base_dirs, max_bytes=max_bytes, log=log)


def ensure_dir_native_safe(dir_path: str,
                           platform: Optional[str] = None,
                           log=None) -> str:
    """把**目录**转成 ASCII 安全形式。

    用于 sherpa 的模型目录（一个模型目录下有多个文件，
    逐文件暂存反而更麻烦）。实际做法是把整个目录搬到 ASCII 暂存区。
    """
    if not dir_path or not needs_native_safe(dir_path, platform):
        return dir_path
    if not os.path.isdir(dir_path):
        return dir_path

    emit = log or (lambda msg, level="info": None)
    cached = _staged_cache.get(dir_path)
    if cached and os.path.isdir(cached):
        return cached

    bases = staging_base_dirs()
    if not bases:
        emit("native-safe: 无可用 ASCII 暂存目录", "warning")
        return dir_path

    # 用目录名的哈希做键，内容变了也能相对稳定（同一版本复用同一份副本）
    key = hashlib.sha1(os.path.abspath(dir_path).encode("utf-8")).hexdigest()[:16]
    name = _ascii_filename(os.path.basename(os.path.abspath(dir_path)))

    for base in bases:
        target = os.path.join(base, key, name)
        try:
            if not os.path.isdir(target) or not os.listdir(target):
                os.makedirs(os.path.dirname(target), exist_ok=True)
                if os.path.isdir(target):
                    shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(dir_path, target)
            _staged_cache[dir_path] = target
            emit("native-safe: 已暂存目录 %s -> %s" % (dir_path, target), "info")
            return target
        except OSError as e:
            emit("native-safe: 暂存目录 %s 失败: %r" % (base, e), "warning")

    return dir_path


def reset_cache_for_test() -> None:
    """仅供测试：清空每进程缓存，模拟「新进程」。"""
    _staged_cache.clear()