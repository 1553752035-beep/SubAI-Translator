# -*- coding: utf-8 -*-
"""四期深化：插件市场远端安装（安全优先）。

对外部代码必须假设它是恶意的，因此这里设了四道闸：
1. **必须有 sha256** —— 索引条目缺 download_url 或 sha256 一律拒绝，不做"无校验安装"；
2. **必须显式确认** —— 调用方要传 confirm=True，接口返回里也写清"安装后不会自动启用"；
3. **体积双限** —— 下载体积与解压后体积都有上限，防压缩炸弹；
4. **防目录穿越** —— 压缩包内出现绝对路径或 .. 直接拒绝，且不允许覆盖已存在的插件目录。

安装完成后插件处于**未启用**状态，必须由管理员显式启用 —— 这样"下载"与"执行"是两步。
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import shutil
import zipfile
from typing import Optional

from src.config import config

logger = logging.getLogger(__name__)


class InstallError(RuntimeError):
    """安装被拒绝或失败（原因会原样返回给调用方）。"""


def _human(n: int) -> str:
    return "%.1f MB" % (n / 1048576.0)


def safe_extract_zip(blob: bytes, dest: str) -> list:
    """安全解压：拒绝绝对路径 / .. / 超限，返回解出的文件名列表。"""
    limit = int(config.plugins.max_unpack_mb) * 1048576
    names: list = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile as e:
        raise InstallError("不是合法的 zip 包: %s" % e)
    with zf:
        total = 0
        for info in zf.infolist():
            raw = info.filename.replace("\\", "/")
            if raw.startswith("/") or os.path.isabs(info.filename):
                raise InstallError("压缩包包含绝对路径，已拒绝: %s" % info.filename)
            parts = [p for p in raw.split("/") if p not in ("", ".")]
            if any(p == ".." for p in parts):
                raise InstallError("压缩包包含目录穿越，已拒绝: %s" % info.filename)
            total += int(info.file_size)
            if total > limit:
                raise InstallError("解压后体积超过上限（%s）" % _human(limit))
        os.makedirs(dest, exist_ok=True)
        zf.extractall(dest)
        names = [i.filename for i in zf.infolist()]
    return names


def _flatten_single_dir(dest: str) -> None:
    """若解压后只有一层子目录且含 plugin.json，把它提到根（常见打包方式）。"""
    if os.path.isfile(os.path.join(dest, "plugin.json")):
        return
    entries = [e for e in os.listdir(dest) if not e.startswith("__MACOSX")]
    if len(entries) != 1:
        return
    inner = os.path.join(dest, entries[0])
    if not os.path.isdir(inner) or not os.path.isfile(os.path.join(inner, "plugin.json")):
        return
    for name in os.listdir(inner):
        shutil.move(os.path.join(inner, name), os.path.join(dest, name))
    os.rmdir(inner)


async def install_from_entry(entry: dict, plugins_dir: str, confirm: bool = False,
                             transport=None) -> dict:
    """按市场索引条目安装插件。返回安装结果（含路径与后续操作提示）。"""
    if not confirm:
        raise InstallError("安装外部插件会执行其代码，必须显式确认（confirm=true）")

    url = str(entry.get("download_url") or "").strip()
    expect = str(entry.get("sha256") or "").strip().lower()
    if not url or not url.lower().startswith(("http://", "https://")):
        raise InstallError("该条目没有可用的 download_url")
    if len(expect) != 64:
        raise InstallError("该条目缺少 sha256 校验值 —— 出于安全拒绝无校验安装")

    name = str(entry.get("name") or entry.get("id") or "").strip()
    if not name or any(c in name for c in "\\/:*?\"<>|"):
        raise InstallError("条目 name 不合法（不能为空或包含路径字符）")

    dest = os.path.join(plugins_dir, name)
    if os.path.exists(dest):
        raise InstallError("目标目录已存在，请先自行处理: %s" % dest)

    import httpx

    limit = int(config.plugins.max_download_mb) * 1048576
    timeout = httpx.Timeout(30.0, read=120.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                 transport=transport) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            raise InstallError("下载失败: %r" % (e,))
    blob = resp.content
    if len(blob) > limit:
        raise InstallError("下载体积超过上限（%s > %s）" % (_human(len(blob)), _human(limit)))

    got = hashlib.sha256(blob).hexdigest()
    if got != expect:
        raise InstallError("sha256 校验失败：期望 %s…，实际 %s…" % (expect[:12], got[:12]))

    names = safe_extract_zip(blob, dest)
    _flatten_single_dir(dest)
    manifest_path = os.path.join(dest, "plugin.json")
    if not os.path.isfile(manifest_path):
        shutil.rmtree(dest, ignore_errors=True)
        raise InstallError("压缩包里没有 plugin.json（已回滚安装）")

    # 关键安全步骤：强制 enabled_by_default=false。
    # 否则清单里写 enabled_by_default=true 的插件会在 reload 时被自动加载 ——
    # 那就等于"下载即执行"，与"安装/执行分离"的承诺矛盾。
    try:
        import json as _json

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = _json.load(f)
        manifest["enabled_by_default"] = False
        with open(manifest_path, "w", encoding="utf-8") as f:
            _json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(dest, ignore_errors=True)
        raise InstallError("plugin.json 不是合法 JSON，已回滚: %r" % (e,))

    logger.info("插件已安装（未启用）: %s -> %s", name, dest)
    return {
        "installed": True,
        "name": name,
        "path": dest,
        "sha256": got,
        "files": len(names),
        "enabled": False,
        "notice": "已安装但**未启用**：请到插件列表确认无误后手动启用（启用即开始执行其代码）",
    }
