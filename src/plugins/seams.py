"""主流程与插件系统之间的接缝（seam）。

规则（很重要，决定了"停用插件"到底意味着什么）：
- 插件系统整体关闭（SUBAI_PLUGIN_ENABLED=false）或初始化异常 -> 返回 None，
  调用方回退到内置实现，主功能不受影响；
- 某个插件被用户显式停用 -> 抛 CapabilityDisabled，**不能偷偷用内置实现顶上**，
  否则"停用"就是假的；
- 插件加载失败 -> 同样视为不可用（抛 CapabilityDisabled 并说明原因）。
"""
from __future__ import annotations

import os
from typing import Optional


class CapabilityDisabled(RuntimeError):
    """该能力对应的插件被停用或不可用（区别于插件系统整体关闭）。"""


def _plugin_system_on() -> bool:
    try:
        from src.config import config

        return bool(config.plugins.enabled)
    except Exception:  # noqa: BLE001
        return False


def _instance(plugin_id: str):
    """取插件实例；插件系统关闭或初始化异常时返回 None。"""
    if not _plugin_system_on():
        return None
    try:
        from src.plugins.registry import registry

        return registry.instance(plugin_id)
    except Exception:  # noqa: BLE001
        return None


def _record(plugin_id: str):
    if not _plugin_system_on():
        return None
    try:
        from src.plugins.registry import registry

        registry.ensure_loaded()
        return registry.get(plugin_id)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #

OCR_PLUGIN_ID = "subai.ocr.rapidocr"


def ocr_provider():
    """返回硬字幕 OCR 的 provider（必须有 create_engine 与 texts_from_frame）。"""
    inst = _instance(OCR_PLUGIN_ID)
    if inst is not None and hasattr(inst, "texts_from_frame"):
        return inst
    if not _plugin_system_on():
        from src.plugins.builtin import RapidOcrEngine

        return RapidOcrEngine()
    rec = _record(OCR_PLUGIN_ID)
    why = (rec.error if rec is not None and rec.error else "已被停用")
    raise CapabilityDisabled(
        "硬字幕识别所需的 OCR 插件不可用（%s）：请到设置页的插件面板启用 %s" % (why, OCR_PLUGIN_ID)
    )


# --------------------------------------------------------------------------- #
# TTS
# --------------------------------------------------------------------------- #

TTS_PLUGIN_IDS = {"sapi": "subai.tts.sapi", "edge": "subai.tts.edge"}


def tts_plugin_id(name: str) -> Optional[str]:
    """把 TTS 后端名映射到插件 id；auto 按平台选择（与内置实现同语义）。"""
    if name == "auto":
        name = "sapi" if os.name == "nt" else "edge"
    return TTS_PLUGIN_IDS.get(name)


def tts_engine(name: str = "auto"):
    """返回 TTS 引擎；插件系统关闭时返回 None（调用方回退内置实现）。"""
    plugin_id = tts_plugin_id(name)
    if plugin_id is None:
        return None
    inst = _instance(plugin_id)
    if inst is not None:
        # 原样抛出插件异常：内置插件的 create_engine 就是重构前的实现，
        # 保持异常类型与文案与"没有插件系统"时完全一致。
        return inst.create_engine()
    if not _plugin_system_on():
        return None
    rec = _record(plugin_id)
    why = (rec.error if rec is not None and rec.error else "已被停用")
    raise CapabilityDisabled("TTS 插件 %s 不可用（%s）" % (plugin_id, why))


# --------------------------------------------------------------------------- #
# 翻译
# --------------------------------------------------------------------------- #


def translator_plugin_ids() -> list:
    """当前可用的翻译插件 id（按优先级）。"""
    try:
        from src.plugins.registry import registry

        return [r.id for r in registry._ordered() if r.kind == "translator" and r.enabled and r.loaded]
    except Exception:  # noqa: BLE001
        return []

