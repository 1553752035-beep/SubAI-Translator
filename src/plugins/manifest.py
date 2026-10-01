"""插件清单（plugin.json）的解析与校验。

清单是插件与宿主之间唯一的契约：宿主只依赖清单里声明的字段，
**发现阶段不 import 插件代码**，因此坏插件不会拖垮整个服务。
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

#: 宿主认识的能力（kind）。新增能力时同时更新 registry 的解析逻辑。
VALID_KINDS = ("translator", "ocr", "tts")

_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class ManifestError(ValueError):
    """清单缺失或字段不合法。"""


@dataclass
class PluginManifest:
    id: str
    name: str
    kind: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    entry: str = ""
    builtin: bool = False
    enabled_by_default: bool = True
    homepage: str = ""
    priority: int = 100
    tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _require(data: dict, key: str, where: str) -> Any:
    if key not in data or data[key] in (None, ""):
        raise ManifestError("%s 缺少必填字段: %s" % (where, key))
    return data[key]


def parse_manifest(data: Any, source: str = "") -> PluginManifest:
    """把已解析的 JSON 对象转成 PluginManifest，字段不合法直接抛 ManifestError。"""
    where = source or "plugin.json"
    if not isinstance(data, dict):
        raise ManifestError("%s 必须是 JSON 对象" % where)

    pid = str(_require(data, "id", where)).strip()
    if not _ID_RE.match(pid):
        raise ManifestError(
            "%s 的 id 不合法: %r（只允许小写字母/数字与 . _ -，且以字母开头）" % (where, pid)
        )

    kind = str(_require(data, "kind", where)).strip().lower()
    if kind not in VALID_KINDS:
        raise ManifestError(
            "%s 的 kind 不合法: %r（可选 %s）" % (where, kind, "|".join(VALID_KINDS))
        )

    name = str(_require(data, "name", where)).strip()

    entry = str(data.get("entry") or "").strip()
    if entry and ":" not in entry:
        raise ManifestError(
            "%s 的 entry 必须形如 'module:ClassName' 或 'builtin:ClassName'（当前 %r）" % (where, entry)
        )

    try:
        priority = int(data.get("priority", 100))
    except (TypeError, ValueError):
        raise ManifestError("%s 的 priority 必须是整数" % where)
    if not 0 <= priority <= 1000:
        raise ManifestError("%s 的 priority 必须在 0..1000 之间" % where)

    tags = data.get("tags") or []
    if not isinstance(tags, list):
        raise ManifestError("%s 的 tags 必须是数组" % where)

    return PluginManifest(
        id=pid,
        name=name,
        kind=kind,
        version=str(data.get("version") or "1.0.0"),
        description=str(data.get("description") or ""),
        author=str(data.get("author") or ""),
        entry=entry,
        builtin=bool(data.get("builtin", False)),
        enabled_by_default=bool(data.get("enabled_by_default", True)),
        homepage=str(data.get("homepage") or ""),
        priority=priority,
        tags=[str(t) for t in tags],
    )


def load_manifest_file(path: str) -> PluginManifest:
    """读取单个清单文件（不存在/非法 JSON/字段不合法都会抛 ManifestError）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise ManifestError("清单文件不存在: %s" % path)
    except json.JSONDecodeError as e:
        raise ManifestError("清单不是合法 JSON（%s）: %s" % (path, e))
    return parse_manifest(data, source=path)


def load_manifest_dir(plugin_dir: str, filename: str = "plugin.json") -> PluginManifest:
    return load_manifest_file(os.path.join(plugin_dir, filename))
