"""内置插件：把宿主已有的翻译 / OCR / TTS 能力包装成插件。

这些不是"样例插件"，而是宿主默认能力的正规入口：
- OCR 与 TTS 已被主流程按 provider 取用（见 pipeline.hardsub_segments 与 tts.get_engine），
  因此停用某个插件会真实改变主流程行为；
- 翻译插件通过注册表暴露能力，翻译的唯一实现仍是 pipeline._call_llm
  （避免 pipeline 与 plugins 循环依赖）。
"""
from __future__ import annotations

import importlib.util
import os

BUILTIN_MANIFESTS = [
    {
        "id": "subai.translator.local-llm",
        "name": "本地大模型翻译",
        "kind": "translator",
        "version": "1.0.0",
        "description": "通过本机 OpenAI 兼容端点（如 koboldcpp）翻译字幕，完全离线。",
        "author": "内置",
        "entry": "builtin:LocalLlmTranslator",
        "builtin": True,
        "enabled_by_default": True,
        "priority": 10,
        "tags": ["翻译", "本地", "离线"],
    },
    {
        "id": "subai.translator.cloud-llm",
        "name": "云端大模型翻译",
        "kind": "translator",
        "version": "1.0.0",
        "description": "通过 OpenAI 兼容的云端接口翻译字幕，需要配置地址与密钥。",
        "author": "内置",
        "entry": "builtin:CloudLlmTranslator",
        "builtin": True,
        "enabled_by_default": True,
        "priority": 20,
        "tags": ["翻译", "云端"],
    },
    {
        "id": "subai.ocr.rapidocr",
        "name": "RapidOCR 硬字幕识别",
        "kind": "ocr",
        "version": "1.0.0",
        "description": "从视频画面中识别硬编码字幕，CPU 可跑，无需显卡。",
        "author": "内置",
        "entry": "builtin:RapidOcrEngine",
        "builtin": True,
        "enabled_by_default": True,
        "priority": 10,
        "tags": ["OCR", "硬字幕", "离线"],
    },
    {
        "id": "subai.tts.sapi",
        "name": "Windows SAPI 语音合成",
        "kind": "tts",
        "version": "1.0.0",
        "description": "使用系统内置语音合成配音，离线可用（仅 Windows）。",
        "author": "内置",
        "entry": "builtin:SapiTtsEngine",
        "builtin": True,
        "enabled_by_default": True,
        "priority": 10,
        "tags": ["配音", "TTS", "离线"],
    },
    {
        "id": "subai.tts.edge",
        "name": "Edge TTS 在线语音合成",
        "kind": "tts",
        "version": "1.0.0",
        "description": "微软 Edge 在线语音（音色多、更自然），需要联网。",
        "author": "内置",
        "entry": "builtin:EdgeTtsEngine",
        "builtin": True,
        "enabled_by_default": True,
        "priority": 20,
        "tags": ["配音", "TTS", "在线"],
    },
]


class LocalLlmTranslator:
    """本地大模型翻译（包装 pipeline._call_llm 的本地端点）。"""

    capabilities = ["translate", "probe"]

    def probe(self) -> dict:
        from src import llm

        return llm.test_endpoint("local")

    def translate_batch(self, texts, target: str, **kwargs) -> list:
        from src.config import config
        from src.pipeline import _call_llm  # 延迟导入：避免 plugins 与 pipeline 循环依赖

        return [
            _call_llm(t, target, url=config.llm.local_url,
                      model=config.llm.local_model, api_key="", **kwargs)
            for t in texts
        ]


class CloudLlmTranslator:
    """云端大模型翻译（包装同一实现的云端端点）。"""

    capabilities = ["translate", "probe"]

    def available(self) -> bool:
        from src.config import config

        return bool(config.llm.cloud_url)

    def probe(self) -> dict:
        from src import llm

        return llm.test_endpoint("cloud")

    def translate_batch(self, texts, target: str, **kwargs) -> list:
        from src.config import config
        from src.pipeline import _call_llm

        return [
            _call_llm(t, target, url=config.llm.cloud_url,
                      model=config.llm.cloud_model,
                      api_key=config.llm.cloud_api_key, **kwargs)
            for t in texts
        ]


class RapidOcrEngine:
    """RapidOCR 硬字幕识别（主流程实际取用的 OCR provider）。"""

    capabilities = ["recognize"]

    def available(self) -> bool:
        # 用 find_spec 而不是真正 import：import 重达秒级，列表接口不该付出这个代价
        return importlib.util.find_spec("rapidocr_onnxruntime") is not None

    def create_engine(self):
        from rapidocr_onnxruntime import RapidOCR

        return RapidOCR()

    def texts_from_frame(self, engine, frame, min_score: float) -> list:
        """识别一帧并返回通过置信度阈值的文本片段。

        兼容不同 RapidOCR 版本的返回格式 [box, text, score]，score 可能是
        str / float / numpy 标量；与重构前的内联实现保持完全一致的语义。
        """
        res, _ = engine(frame)
        parts: list = []
        for item in res or []:
            try:
                _box, _text, _score = item
            except (TypeError, ValueError):
                continue
            try:
                _score = float(_score)
            except (TypeError, ValueError):
                _score = 0.0
            if _score >= min_score and _text and str(_text).strip():
                parts.append(str(_text))
        return parts


class SapiTtsEngine:
    """Windows SAPI 语音合成（主流程实际取用的 TTS provider）。"""

    capabilities = ["synthesize", "voices"]

    def __init__(self) -> None:
        self._voices = None

    def available(self) -> bool:
        if os.name != "nt":
            return False
        return bool(self.list_voices())

    def create_engine(self):
        from src.tts import WindowsSapiEngine

        return WindowsSapiEngine()

    def list_voices(self) -> list:
        if self._voices is None:
            try:
                self._voices = self.create_engine().list_voices()
            except Exception:  # noqa: BLE001
                self._voices = []
        return self._voices


class EdgeTtsEngine:
    """Edge TTS 在线语音合成。"""

    capabilities = ["synthesize", "voices"]

    def available(self) -> bool:
        return importlib.util.find_spec("edge_tts") is not None

    def create_engine(self):
        from src.tts import EdgeTTSEngine

        return EdgeTTSEngine()


