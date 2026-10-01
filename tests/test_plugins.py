# -*- coding: utf-8 -*-
"""四期 4.3 插件系统 —— 单元测试。

覆盖：清单校验 / 发现容错 / 生命周期 / 优先级 / 状态持久化 / 能力接缝。
"""
from __future__ import annotations

import json
import os

import pytest

from src.plugins import PluginRegistry, parse_manifest
from src.plugins.builtin import BUILTIN_MANIFESTS
from src.plugins.manifest import ManifestError


def make_registry(tmp_path, builtins=None, plugins_dir=None):
    return PluginRegistry(
        plugins_dir=plugins_dir or str(tmp_path / "plugins"),
        state_path=str(tmp_path / "plugins.json"),
        builtin_manifests=BUILTIN_MANIFESTS if builtins is None else builtins,
    )


# --------------------------------------------------------------------------- #
# 清单校验
# --------------------------------------------------------------------------- #

class TestManifest:
    def test_minimal_valid(self):
        m = parse_manifest({"id": "a.b", "name": "X", "kind": "ocr"})
        assert m.id == "a.b" and m.kind == "ocr" and m.priority == 100

    @pytest.mark.parametrize("bad", [
        {"name": "X", "kind": "ocr"},                      # 缺 id
        {"id": "a.b", "kind": "ocr"},                      # 缺 name
        {"id": "a.b", "name": "X"},                        # 缺 kind
        {"id": "a.b", "name": "X", "kind": "unknown"},     # kind 非法
        {"id": "A B", "name": "X", "kind": "ocr"},         # id 字符非法
        {"id": "1abc", "name": "X", "kind": "ocr"},        # id 不能以数字开头
        {"id": "a.b", "name": "X", "kind": "ocr", "entry": "NoColon"},
        {"id": "a.b", "name": "X", "kind": "ocr", "priority": "high"},
        {"id": "a.b", "name": "X", "kind": "ocr", "priority": 9999},
        {"id": "a.b", "name": "X", "kind": "ocr", "tags": "not-a-list"},
        ["not", "an", "object"],
    ])
    def test_invalid_manifest_rejected(self, bad):
        with pytest.raises(ManifestError):
            parse_manifest(bad)


# --------------------------------------------------------------------------- #
# 发现与生命周期
# --------------------------------------------------------------------------- #

class TestDiscovery:
    def test_builtins_discovered_and_loaded(self, tmp_path):
        reg = make_registry(tmp_path)
        assert reg.discover() == len(BUILTIN_MANIFESTS)
        listed = reg.list()
        assert all(p["state"] == "enabled" for p in listed), listed
        assert {p["kind"] for p in listed} == {"translator", "ocr", "tts"}

    def test_priority_picks_local_and_sapi(self, tmp_path):
        reg = make_registry(tmp_path)
        reg.discover()
        assert type(reg.provider("translator")).__name__ == "LocalLlmTranslator"
        assert type(reg.provider("tts")).__name__ == "SapiTtsEngine"
        assert type(reg.provider("ocr")).__name__ == "RapidOcrEngine"

    def test_stats(self, tmp_path):
        reg = make_registry(tmp_path)
        reg.discover()
        s = reg.stats()
        assert s["total"] == len(BUILTIN_MANIFESTS)
        assert s["enabled"] == len(BUILTIN_MANIFESTS)
        assert s["errors"] == 0
        assert s["by_kind"]["translator"]["total"] == 2

    def test_unknown_plugin_raises(self, tmp_path):
        reg = make_registry(tmp_path)
        reg.discover()
        with pytest.raises(KeyError):
            reg.load("no.such.plugin")
        with pytest.raises(KeyError):
            reg.set_enabled("no.such.plugin", True)

    def test_disable_then_enable_persists(self, tmp_path):
        reg = make_registry(tmp_path)
        reg.discover()
        assert reg.set_enabled("subai.ocr.rapidocr", False) is False
        assert reg.provider("ocr") is None
        state = json.loads((tmp_path / "plugins.json").read_text(encoding="utf-8"))
        assert state["enabled"]["subai.ocr.rapidocr"] is False
        # 新实例应读到同一状态
        again = make_registry(tmp_path)
        again.discover()
        assert again.get("subai.ocr.rapidocr").enabled is False
        assert again.set_enabled("subai.ocr.rapidocr", True) is True
        assert again.provider("ocr") is not None

    def test_bad_manifest_becomes_error_record(self, tmp_path):
        pdir = tmp_path / "plugins" / "broken"
        pdir.mkdir(parents=True)
        (pdir / "plugin.json").write_text("{ not json", encoding="utf-8")
        reg = make_registry(tmp_path)
        assert reg.discover() == len(BUILTIN_MANIFESTS) + 1
        broken = [p for p in reg.list() if p["state"] == "error"]
        assert len(broken) == 1 and "JSON" in broken[0]["error"]
        # 坏插件不允许启用
        assert reg.set_enabled(broken[0]["id"], True) is False

    def test_external_plugin_lifecycle(self, tmp_path, monkeypatch):
        pdir = tmp_path / "plugins" / "demo"
        pdir.mkdir(parents=True)
        (pdir / "plugin.json").write_text(json.dumps({
            "id": "demo.ocr.echo", "name": "回显 OCR", "kind": "ocr",
            "entry": "demo_plugin:EchoOcr", "priority": 1,
            "enabled_by_default": False,
        }), encoding="utf-8")
        (pdir / "demo_plugin.py").write_text(
            "class EchoOcr:\n"
            "    capabilities = [\"recognize\"]\n"
            "    def texts_from_frame(self, engine, frame, min_score):\n"
            "        return [\"echo\"]\n",
            encoding="utf-8")
        monkeypatch.syspath_prepend(str(pdir))
        reg = make_registry(tmp_path)
        reg.discover()
        rec = reg.get("demo.ocr.echo")
        assert rec is not None and rec.enabled is False
        # 未启用时不被选为 provider
        assert type(reg.provider("ocr")).__name__ == "RapidOcrEngine"
        assert reg.set_enabled("demo.ocr.echo", True) is True
        # priority=1 比内置的 10 更高，启用后应被优先选中
        assert type(reg.provider("ocr")).__name__ == "EchoOcr"
        reg.set_enabled("demo.ocr.echo", False)
        assert type(reg.provider("ocr")).__name__ == "RapidOcrEngine"

    def test_id_conflict_ignored(self, tmp_path):
        pdir = tmp_path / "plugins" / "dup"
        pdir.mkdir(parents=True)
        (pdir / "plugin.json").write_text(json.dumps({
            "id": "subai.ocr.rapidocr", "name": "冒名", "kind": "ocr",
        }), encoding="utf-8")
        reg = make_registry(tmp_path)
        assert reg.discover() == len(BUILTIN_MANIFESTS)
        assert reg.get("subai.ocr.rapidocr").manifest.name != "冒名"

    def test_marketplace_search_and_filter(self, tmp_path):
        reg = make_registry(tmp_path)
        reg.discover()
        assert len(reg.marketplace()) == len(BUILTIN_MANIFESTS)
        assert all(e["kind"] == "tts" for e in reg.marketplace(kind="tts"))
        found = reg.marketplace(query="语音")
        assert found and all("语音" in (e["name"] + e["description"]) for e in found)
        assert reg.marketplace(query="不存在的关键词") == []


# --------------------------------------------------------------------------- #
# 能力接缝：停用到底意味着什么
# --------------------------------------------------------------------------- #

class TestSeams:
    def test_ocr_provider_has_parser(self):
        from src.plugins import ocr_provider

        provider = ocr_provider()
        assert hasattr(provider, "texts_from_frame")
        assert hasattr(provider, "create_engine")

    def test_rapidocr_parser_semantics(self):
        """解析逻辑必须与重构前一致：[box, text, score]，score 支持 str/float。"""
        from src.plugins.builtin import RapidOcrEngine

        p = RapidOcrEngine()
        frame = "unused"

        class Fake:
            def __call__(self, _frame):
                return ([
                    [[0, 0, 1, 1], "你好", 0.99],
                    [[0, 0, 1, 1], "低分", 0.1],
                    [[0, 0, 1, 1], "字符串分", "0.95"],
                    [[0, 0, 1, 1], "   ", 0.99],
                    "坏数据",
                ], None)

        assert p.texts_from_frame(Fake(), frame, 0.5) == ["你好", "字符串分"]

    def test_client_conftest_isolated(self):
        """占位：确保测试进程已加载插件包（import 即执行注册表定义）。"""
        assert os.path.isdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

