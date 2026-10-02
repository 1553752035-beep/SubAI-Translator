# -*- coding: utf-8 -*-
"""五期：云端服务商预设 + 云端优化（关思考 / 自适应 max_tokens / token 统计）。"""
from __future__ import annotations

from src.llm_providers import PROVIDERS, get_provider, list_providers
from src.pipeline import _adaptive_max_tokens, _no_thinking_params, get_token_usage, reset_token_usage


class TestProviders:
    def test_has_enough_providers(self):
        assert len(list_providers()) >= 20          # 用户要求"要全面"

    def test_groups_cover_expected(self):
        groups = {p["group"] for p in list_providers()}
        assert {"国内", "国际", "聚合", "本地"} <= groups

    def test_every_provider_is_usable(self):
        for p in list_providers():
            assert p["id"] and p["name"] and p["base_url"]
            assert p["base_url"].startswith("http")
            assert isinstance(p["models"], list)
            assert p["key_url"].startswith("http")

    def test_ids_unique(self):
        ids = [p.id for p in PROVIDERS]
        assert len(ids) == len(set(ids))

    def test_common_providers_present(self):
        ids = {p.id for p in PROVIDERS}
        for want in ("deepseek", "qwen", "doubao", "kimi", "zhipu", "siliconflow",
                     "openai", "gemini", "openrouter", "ollama"):
            assert want in ids, want

    def test_get_provider(self):
        assert get_provider("deepseek")["name"].startswith("DeepSeek")
        assert get_provider("不存在的") == {}

    def test_chat_model_recommended_not_reasoner(self):
        # 翻译场景默认推 chat（reasoner 会思考、更贵更慢）
        assert "deepseek-chat" in get_provider("deepseek")["models"]


class TestCloudOptimizations:
    def test_disable_thinking_for_known_providers(self):
        assert _no_thinking_params("https://api.siliconflow.cn/v1", "x") == {"enable_thinking": False}
        assert _no_thinking_params("https://open.bigmodel.cn/api/paas/v4", "x") == {"enable_thinking": False}
        assert _no_thinking_params("https://dashscope.aliyuncs.com/compatible-mode/v1", "x") == {"enable_thinking": False}
        assert _no_thinking_params("https://openrouter.ai/api/v1", "x") == {"reasoning": {"enabled": False}}
        assert _no_thinking_params("https://api.openai.com/v1", "o4-mini") == {"reasoning_effort": "low"}

    def test_unknown_provider_gets_no_extra_params(self):
        # 不能给不认识的端点发未知参数（会直接报错）
        assert _no_thinking_params("https://api.deepseek.com/v1", "deepseek-chat") == {}
        assert _no_thinking_params("http://127.0.0.1:5001/v1", "koboldcpp") == {}

    def test_max_tokens_adaptive_and_capped(self):
        short = _adaptive_max_tokens("短")
        long = _adaptive_max_tokens("这是一句很长很长很长很长很长很长的字幕文本" * 3)
        assert long >= short
        assert short >= 256 and long <= 1024

    def test_token_usage_accumulates(self):
        reset_token_usage()
        assert get_token_usage()["total"] == 0

