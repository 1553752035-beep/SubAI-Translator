"""插件系统（四期 4.3）。

对外只需要两样东西：
    from src.plugins import registry, init_plugins
"""
from src.plugins.manifest import (
    ManifestError,
    PluginManifest,
    load_manifest_dir,
    load_manifest_file,
    parse_manifest,
)
from src.plugins.registry import PluginRecord, PluginRegistry, init_plugins, registry
from src.plugins.seams import CapabilityDisabled, ocr_provider, tts_engine

__all__ = [
    "ManifestError",
    "PluginManifest",
    "PluginRecord",
    "CapabilityDisabled",
    "PluginRegistry",
    "init_plugins",
    "ocr_provider",
    "tts_engine",
    "load_manifest_dir",
    "load_manifest_file",
    "parse_manifest",
    "registry",
]
