# -*- coding: utf-8 -*-
"""四期深化：插件市场远端安装 —— 安全闸门 + 端到端安装测试。"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from src.plugins.installer import InstallError, install_from_entry, safe_extract_zip


def run(coro):
    return asyncio.run(coro)


MANIFEST = {
    "id": "demo.ocr.echo",
    "name": "回显 OCR",
    "kind": "ocr",
    "entry": "demo_plugin:EchoOcr",
    "enabled_by_default": True,   # 故意写 true：安装器必须把它改成 false
}


def make_zip(manifest=None, prefix="", extra=None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(prefix + "plugin.json", json.dumps(manifest or MANIFEST, ensure_ascii=False))
        z.writestr(prefix + "demo_plugin.py", "class EchoOcr:\n    capabilities = [\"recognize\"]\n")
        for name, content in (extra or {}).items():
            z.writestr(name, content)
    return buf.getvalue()


def start_server(blob: bytes):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(blob)))
            self.end_headers()
            self.wfile.write(blob)

        def log_message(self, *args):
            return

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d/demo.zip" % srv.server_address[1]


def entry_for(blob: bytes, url: str, **over) -> dict:
    entry = {
        "id": "demo.ocr.echo",
        "name": "demo-plugin",
        "kind": "ocr",
        "download_url": url,
        "sha256": hashlib.sha256(blob).hexdigest(),
    }
    entry.update(over)
    return entry


class TestInstallGuards:
    def test_requires_explicit_confirm(self, tmp_path):
        blob = make_zip()
        srv, url = start_server(blob)
        try:
            with pytest.raises(InstallError) as ei:
                run(install_from_entry(entry_for(blob, url), str(tmp_path), confirm=False))
            assert "确认" in str(ei.value)
            assert os.listdir(tmp_path) == []           # 什么都没落盘
        finally:
            srv.shutdown()

    def test_requires_sha256(self, tmp_path):
        blob = make_zip()
        entry = entry_for(blob, "http://127.0.0.1:1/x.zip")
        entry["sha256"] = ""
        with pytest.raises(InstallError) as ei:
            run(install_from_entry(entry, str(tmp_path), confirm=True))
        assert "sha256" in str(ei.value)

    def test_requires_download_url(self, tmp_path):
        entry = {"id": "x", "name": "x", "sha256": "a" * 64}
        with pytest.raises(InstallError) as ei:
            run(install_from_entry(entry, str(tmp_path), confirm=True))
        assert "download_url" in str(ei.value)

    def test_bad_hash_rejected_and_nothing_written(self, tmp_path):
        blob = make_zip()
        srv, url = start_server(blob)
        try:
            entry = entry_for(blob, url, sha256="0" * 64)
            with pytest.raises(InstallError) as ei:
                run(install_from_entry(entry, str(tmp_path), confirm=True))
            assert "校验失败" in str(ei.value)
            assert os.listdir(tmp_path) == []
        finally:
            srv.shutdown()

    def test_existing_dir_rejected(self, tmp_path):
        blob = make_zip()
        srv, url = start_server(blob)
        try:
            os.makedirs(tmp_path / "demo-plugin")
            with pytest.raises(InstallError) as ei:
                run(install_from_entry(entry_for(blob, url), str(tmp_path), confirm=True))
            assert "已存在" in str(ei.value)
        finally:
            srv.shutdown()

    def test_zip_slip_rejected(self, tmp_path):
        blob = make_zip(extra={"../evil.txt": "pwned"})
        srv, url = start_server(blob)
        try:
            with pytest.raises(InstallError) as ei:
                run(install_from_entry(entry_for(blob, url), str(tmp_path), confirm=True))
            assert "穿越" in str(ei.value)
            assert not (tmp_path.parent / "evil.txt").exists()   # 没有逃出目标目录
        finally:
            srv.shutdown()

    def test_safe_extract_rejects_absolute_path(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("/tmp/abs.txt", "x")
        with pytest.raises(InstallError) as ei:
            safe_extract_zip(buf.getvalue(), str(tmp_path))
        assert "绝对路径" in str(ei.value)

    def test_unpack_limit(self, tmp_path, monkeypatch):
        from src.config import config as _cfg
        monkeypatch.setattr(_cfg.plugins, "max_unpack_mb", 0)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.txt", "x" * 4096)
        with pytest.raises(InstallError) as ei:
            safe_extract_zip(buf.getvalue(), str(tmp_path / "out"))
        assert "上限" in str(ei.value)


class TestInstallSuccess:
    def test_install_flattens_and_forces_disabled(self, tmp_path):
        blob = make_zip(prefix="demo-plugin-1.0/")     # 常见：打包多一层目录
        srv, url = start_server(blob)
        try:
            result = run(install_from_entry(entry_for(blob, url), str(tmp_path),
                                            confirm=True,
                                            transport=None))
            assert result["installed"] is True
            assert result["enabled"] is False
            dest = tmp_path / "demo-plugin"
            assert (dest / "plugin.json").is_file()
            assert (dest / "demo_plugin.py").is_file()   # 已从子目录提到根
            manifest = json.loads((dest / "plugin.json").read_text(encoding="utf-8"))
            assert manifest["enabled_by_default"] is False   # 强制不自动启用
            assert "未启用" in result["notice"]
        finally:
            srv.shutdown()


@pytest.fixture
def install_env(tmp_path, monkeypatch):
    """隔离插件目录与状态文件，并重置注册表单例状态。"""
    from src.config import config as _cfg
    from src.plugins import registry as plugin_registry   # 注意：这是注册表实例，不是模块

    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir()
    monkeypatch.setattr(_cfg.paths, "plugins_dir", str(plugins_dir))
    monkeypatch.setattr(_cfg.paths, "plugins_state", str(tmp_path / "plugins.json"))
    monkeypatch.setattr(plugin_registry, "_plugins_dir", str(plugins_dir))
    monkeypatch.setattr(plugin_registry, "_state_path", str(tmp_path / "plugins.json"))
    plugin_registry.reload()
    yield plugins_dir
    plugin_registry._plugins_dir = None
    plugin_registry._state_path = None
    plugin_registry.reload()


class TestInstallApi:
    def test_install_flow_via_api(self, client, auth_headers, install_env):
        plugins_dir = install_env
        blob = make_zip()
        srv, url = start_server(blob)
        try:
            # 市场索引里放一条可安装条目
            (plugins_dir / "marketplace.json").write_text(json.dumps([{
                "id": "demo.ocr.echo", "name": "demo-plugin", "kind": "ocr",
                "version": "1.0.0", "description": "演示插件", "author": "test",
                "download_url": url, "sha256": hashlib.sha256(blob).hexdigest(),
            }], ensure_ascii=False), encoding="utf-8")

            ok = client.get("/api/plugins/marketplace", headers=auth_headers)
            assert ok.status_code == 200
            assert any(e["id"] == "demo.ocr.echo" for e in ok.json()["entries"])

            # 未确认 -> 400
            bad = client.post("/api/plugins/marketplace/install", headers=auth_headers,
                              json={"id": "demo.ocr.echo", "confirm": False})
            assert bad.status_code == 400 and "确认" in bad.json()["detail"]

            # 未知条目 -> 404
            missing = client.post("/api/plugins/marketplace/install", headers=auth_headers,
                                  json={"id": "nope", "confirm": True})
            assert missing.status_code == 404

            # 正常安装 -> 200，且被识别为"已安装但未启用"
            good = client.post("/api/plugins/marketplace/install", headers=auth_headers,
                               json={"id": "demo.ocr.echo", "confirm": True})
            assert good.status_code == 200, good.text
            body = good.json()
            assert body["installed"] is True and body["enabled"] is False
            listing = client.get("/api/plugins", headers=auth_headers).json()["plugins"]
            installed = [p for p in listing if p["id"] == "demo.ocr.echo"]
            assert installed and installed[0]["enabled"] is False   # 需人工启用
        finally:
            srv.shutdown()

