# -*- coding: utf-8 -*-
"""
SubAI Translator —— 配置加载回归测试（v3.1.1）
================================================

背景: .env 中出现 SUBAI_LLM_MODE 这类"分段配置键"时,主配置类曾把它当作未知字段,
抛 extra_forbidden 导致**整个后端无法启动**。本测试锁定该行为不再回归。
"""
from __future__ import annotations

import os

from src.config import SubAIConfig


class TestDotEnvNestedKeys:
    def test_nested_keys_in_env_file_do_not_crash(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text(
            "SUBAI_LLM_MODE=cloud\nSUBAI_LLM_CLOUD_MODEL=gpt-4o-mini\n",
            encoding="utf-8",
        )
        # 模拟 _load_env_file 的效果（注入 os.environ），分段配置由此读取
        monkeypatch.setenv("SUBAI_LLM_MODE", "cloud")
        monkeypatch.setenv("SUBAI_LLM_CLOUD_MODEL", "gpt-4o-mini")

        cfg = SubAIConfig(_env_file=str(env))   # 不应抛 extra_forbidden
        assert cfg.llm.mode == "cloud"
        assert cfg.llm.cloud_model == "gpt-4o-mini"

    def test_unknown_top_level_key_is_ignored(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("SUBAI_THIS_KEY_DOES_NOT_EXIST=1\n", encoding="utf-8")
        cfg = SubAIConfig(_env_file=str(env))   # 忽略未知键而不是崩溃
        assert cfg.llm.mode in ("local", "cloud", "hybrid")

    def test_defaults_without_env(self, tmp_path, monkeypatch):
        for k in ("SUBAI_LLM_MODE", "SUBAI_LLM_CLOUD_MODEL"):
            monkeypatch.delenv(k, raising=False)
        cfg = SubAIConfig(_env_file=str(tmp_path / "nope.env"))
        assert cfg.llm.mode == "local"
