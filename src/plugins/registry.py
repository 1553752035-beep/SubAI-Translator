"""插件注册表：发现 / 生命周期 / 能力解析 / 状态持久化。

设计要点
1. 发现阶段零代码执行：只读 plugin.json；坏清单只会变成一条带 error 的记录，
   绝不让整个服务起不来（桌面应用的插件目录是用户可写的，必须容错）。
2. 能力解析（kind）：translator / ocr / tts。同一能力可有多个插件，
   provider(kind) 返回"已启用且加载成功"的第一个（先内置、再外部，最后按 id，顺序稳定可预测）。
3. 状态持久化：只把 enabled 映射写进 data/plugins.json，插件代码永不落盘到状态里。
4. unload 即丢引用：宿主约定插件不得持有不可释放的全局资源。
"""
from __future__ import annotations

import importlib
import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any, Optional

from src.config import config
from src.plugins.manifest import (
    ManifestError,
    PluginManifest,
    load_manifest_file,
    parse_manifest,
)

logger = logging.getLogger(__name__)

#: 状态文件名（位于 data/ 下）
STATE_FILENAME = "plugins.json"


@dataclass
class PluginRecord:
    """单个插件的运行时记录（清单 + 状态 + 实例）。"""

    manifest: PluginManifest
    source: str = ""
    external: bool = False
    enabled: bool = False
    loaded: bool = False
    instance: Any = None
    error: str = ""

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def kind(self) -> str:
        return self.manifest.kind

    def state(self) -> str:
        if self.error:
            return "error"
        if self.enabled and self.loaded:
            return "enabled"
        if self.enabled:
            return "pending"
        return "disabled"

    def to_dict(self, detail: bool = False) -> dict:
        d = dict(self.manifest.to_dict())
        d.update(
            {
                "source": self.source,
                "external": self.external,
                "enabled": self.enabled,
                "loaded": self.loaded,
                "state": self.state(),
                "error": self.error,
            }
        )
        if detail:
            caps = getattr(self.instance, "capabilities", None)
            d["capabilities"] = list(caps) if caps else []
            d["available"] = self._probe_available()
        return d

    def _probe_available(self) -> bool:
        """调用插件的 available()（可选接口）；异常一律视为不可用，不向上抛。"""
        if self.instance is None:
            return False
        probe = getattr(self.instance, "available", None)
        if not callable(probe):
            return True
        try:
            return bool(probe())
        except Exception:  # noqa: BLE001
            return False


class PluginRegistry:
    """插件注册表。实例化参数全部可注入，便于测试与多实例。"""

    def __init__(
        self,
        plugins_dir: Optional[str] = None,
        state_path: Optional[str] = None,
        builtin_manifests: Optional[list] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._records: dict = {}
        self._plugins_dir = plugins_dir
        self._state_path = state_path
        if builtin_manifests is None:
            from src.plugins.builtin import BUILTIN_MANIFESTS

            builtin_manifests = BUILTIN_MANIFESTS
        self._builtin_manifests = builtin_manifests
        self._state_cache: Optional[dict] = None

    # ------------------------------------------------------------------ 路径
    @property
    def plugins_dir(self) -> str:
        return self._plugins_dir or config.plugins_dir

    @property
    def state_path(self) -> str:
        return self._state_path or config.paths.resolve(config.paths.plugins_state)

    # ------------------------------------------------------------------ 状态
    def _state(self) -> dict:
        if self._state_cache is None:
            data: dict = {}
            try:
                p = self.state_path
                if os.path.isfile(p):
                    with open(p, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    if isinstance(raw, dict) and isinstance(raw.get("enabled"), dict):
                        data = {str(k): bool(v) for k, v in raw["enabled"].items()}
            except Exception as e:  # noqa: BLE001
                logger.warning("读取插件状态失败，使用默认值: %r", e)
            self._state_cache = data
        return self._state_cache

    def _save_state(self) -> None:
        try:
            p = self.state_path
            parent = os.path.dirname(os.path.abspath(p))
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"enabled": self._state()}, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            logger.warning("保存插件状态失败: %r", e)

    # ------------------------------------------------------------------ 发现
    def discover(self) -> int:
        """扫描内置清单与外部插件目录，返回发现的插件数量。"""
        with self._lock:
            self._records = {}
            for item in self._builtin_manifests:
                try:
                    m = parse_manifest(item, source="builtin")
                except ManifestError as e:  # 内置清单写错属于开发错误
                    logger.error("内置插件清单不合法: %s", e)
                    continue
                self._records[m.id] = PluginRecord(
                    manifest=m, source="builtin", external=False
                )

            directory = self.plugins_dir
            if os.path.isdir(directory):
                for name in sorted(os.listdir(directory)):
                    pdir = os.path.join(directory, name)
                    if not os.path.isdir(pdir):
                        continue
                    manifest_path = os.path.join(pdir, "plugin.json")
                    if not os.path.isfile(manifest_path):
                        continue
                    try:
                        m = load_manifest_file(manifest_path)
                    except ManifestError as e:
                        # 坏清单也要出现在列表里（带 error），否则用户无从知晓
                        rid = "invalid.%s" % name.lower()
                        self._records[rid] = PluginRecord(
                            manifest=PluginManifest(id=rid, name=name, kind=""),
                            source=manifest_path,
                            external=True,
                            error=str(e),
                        )
                        continue
                    if m.id in self._records:
                        logger.warning("插件 id 冲突，忽略外部插件 %s（%s）", m.id, manifest_path)
                        continue
                    self._records[m.id] = PluginRecord(
                        manifest=m, source=manifest_path, external=True
                    )

            self._apply_state()
            if config.plugins.autoload:
                for rid in list(self._records):
                    rec = self._records[rid]
                    if rec.enabled and not rec.error:
                        self.load(rid)
            return len(self._records)

    def _apply_state(self) -> None:
        state = self._state()
        for rec in self._records.values():
            if rec.id in state:
                rec.enabled = bool(state[rec.id])
            else:
                rec.enabled = bool(rec.manifest.enabled_by_default)

    # ------------------------------------------------------------------ 生命周期
    def load(self, plugin_id: str) -> bool:
        with self._lock:
            rec = self._records.get(plugin_id)
            if rec is None:
                raise KeyError(plugin_id)
            if rec.loaded:
                return True
            if rec.error and rec.instance is None:
                return False
            entry = rec.manifest.entry
            if not entry:
                rec.error = "清单未声明 entry"
                return False
            try:
                mod_name, cls_name = entry.split(":", 1)
                if mod_name == "builtin":
                    mod = importlib.import_module("src.plugins.builtin")
                else:
                    if rec.external and not config.plugins.allow_external:
                        rec.error = "外部插件加载被禁用（SUBAI_PLUGIN_ALLOW_EXTERNAL=false）"
                        return False
                    mod = importlib.import_module(mod_name)
                cls = getattr(mod, cls_name, None)
                if cls is None:
                    rec.error = "入口类不存在: %s" % entry
                    return False
                rec.instance = cls() if isinstance(cls, type) else cls
                rec.loaded = True
                rec.error = ""
                logger.info("插件已加载: %s (%s)", rec.id, rec.manifest.name)
                return True
            except Exception as e:  # noqa: BLE001
                rec.error = "加载失败: %r" % (e,)
                logger.warning("插件加载失败 %s: %r", plugin_id, e)
                return False

    def unload(self, plugin_id: str) -> bool:
        with self._lock:
            rec = self._records.get(plugin_id)
            if rec is None:
                raise KeyError(plugin_id)
            rec.instance = None
            rec.loaded = False
            return True

    def set_enabled(self, plugin_id: str, enabled: bool) -> bool:
        """启用/停用插件；返回操作后的 enabled 取值（坏插件不允许启用）。"""
        with self._lock:
            rec = self._records.get(plugin_id)
            if rec is None:
                raise KeyError(plugin_id)
            if enabled and rec.error and rec.instance is None:
                return False
            rec.enabled = bool(enabled)
            self._state()[plugin_id] = bool(enabled)
            self._save_state()
            if enabled:
                self.load(plugin_id)
            else:
                self.unload(plugin_id)
            return rec.enabled

    # ------------------------------------------------------------------ 查询
    def _ordered(self) -> list:
        """稳定顺序：priority 小者先，其次内置优先，最后按 id。"""
        return sorted(
            self._records.values(),
            key=lambda r: (r.manifest.priority, 0 if r.manifest.builtin else 1, r.manifest.id),
        )

    def ensure_loaded(self) -> int:
        """首次调用时自动发现（幂等）；已发现过则直接返回数量。"""
        with self._lock:
            if not self._records:
                return self.discover()
            return len(self._records)

    def instance(self, plugin_id: str):
        """按 id 取"已启用且加载成功"的插件实例；否则返回 None。"""
        with self._lock:
            self.ensure_loaded()
            rec = self._records.get(plugin_id)
            if rec is None or not rec.enabled or not rec.loaded:
                return None
            return rec.instance

    def get(self, plugin_id: str) -> Optional[PluginRecord]:
        self.ensure_loaded()
        return self._records.get(plugin_id)

    def list(self, kind: Optional[str] = None, detail: bool = False) -> list:
        with self._lock:
            self.ensure_loaded()
            return [
                r.to_dict(detail=detail)
                for r in self._ordered()
                if kind is None or r.kind == kind
            ]

    def providers(self, kind: str) -> list:
        """某能力下当前可用的插件实例（已启用且加载成功），按优先级排序。"""
        with self._lock:
            self.ensure_loaded()
            return [
                r.instance
                for r in self._ordered()
                if r.kind == kind and r.enabled and r.loaded and r.instance is not None
            ]

    def provider(self, kind: str):
        """某能力当前生效的插件实例（优先级最高者）；没有则返回 None（调用方需自带回退）。"""
        found = self.providers(kind)
        return found[0] if found else None

    def stats(self) -> dict:
        with self._lock:
            self.ensure_loaded()
            records = self._ordered()
            by_kind: dict = {}
            for r in records:
                if not r.kind:
                    continue
                by_kind.setdefault(r.kind, {"total": 0, "enabled": 0})
                by_kind[r.kind]["total"] += 1
                if r.enabled and r.loaded:
                    by_kind[r.kind]["enabled"] += 1
            return {
                "total": len(records),
                "enabled": sum(1 for r in records if r.enabled and r.loaded),
                "errors": sum(1 for r in records if r.error),
                "by_kind": by_kind,
            }

    # ------------------------------------------------------------------ 插件目录
    def marketplace(self, query: Optional[str] = None, kind: Optional[str] = None) -> list:
        self.ensure_loaded()
        """插件目录（本地索引，不联网）。

        插件目录下若有 marketplace.json 则作为目录内容，否则回退为"内置插件即目录"。
        安装/更新需要远端仓库，当前未实现——这里只提供可搜索的目录视图，不假装能联网下载。
        """
        entries: list = []
        index_path = os.path.join(self.plugins_dir, "marketplace.json")
        if os.path.isfile(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    entries = [e for e in raw if isinstance(e, dict)]
            except Exception as e:  # noqa: BLE001
                logger.warning("插件目录索引读取失败: %r", e)

        if not entries:
            entries = [
                {
                    "id": m.get("id"),
                    "name": m.get("name"),
                    "kind": m.get("kind"),
                    "version": m.get("version", "1.0.0"),
                    "description": m.get("description", ""),
                    "author": m.get("author", "内置"),
                    "rating": None,
                    "installed": True,
                    "builtin": True,
                }
                for m in self._builtin_manifests
            ]

        installed_ids = {r.id for r in self._ordered()}
        for e in entries:
            e.setdefault("installed", e.get("id") in installed_ids)

        if kind:
            entries = [e for e in entries if str(e.get("kind", "")) == kind]
        if query:
            q = query.strip().lower()
            entries = [
                e
                for e in entries
                if q in str(e.get("name", "")).lower()
                or q in str(e.get("id", "")).lower()
                or q in str(e.get("description", "")).lower()
            ]
        return entries

    def reload(self) -> int:
        """重新扫描（含清空状态缓存，便于测试与热更新）。"""
        with self._lock:
            self._state_cache = None
            return self.discover()


#: 全局单例（API 层与服务启动使用）
registry = PluginRegistry()


def init_plugins() -> int:
    """服务启动时调用：发现并（按配置）自动加载插件。绝不抛异常。"""
    try:
        return registry.discover()
    except Exception as e:  # noqa: BLE001
        logger.error("插件系统初始化失败（不影响主流程）: %r", e)
        return 0
