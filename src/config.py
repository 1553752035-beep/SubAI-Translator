# -*- coding: utf-8 -*-
"""
SubAI Translator —— 集中配置管理（二期新增）
============================================

使用 pydantic-settings 管理所有配置项，支持环境变量覆盖。

配置项分类：
1. 路径配置：项目根目录、模型目录、输出目录等
2. ASR配置：Whisper设备、计算类型、束搜索大小等
3. LLM配置：翻译服务地址、模式（本地/云端）、超时等
4. OCR配置：采样帧率、置信度阈值等
5. 服务器配置：主机、端口、CORS等
6. 并发配置：最大并发数、任务队列大小等
7. 缓存配置：缓存路径、容量、TTL等

环境变量命名规则：
- 所有配置项都可以通过环境变量覆盖
- 环境变量名格式：SUBAI_<CONFIG_SECTION>_<KEY>
- 示例：SUBAI_ASR_DEVICE=cuda 覆盖 asr.device

使用示例：
    from src.config import config
    print(config.asr.device)  # 获取ASR设备配置
    print(config.llm.mode)    # 获取LLM模式配置
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# --------------------------------------------------------------------------- #
# 配置模型
# --------------------------------------------------------------------------- #

def _project_root() -> str:
    """项目根目录：开发模式为 src 的上一级；PyInstaller 打包(frozen)后为 exe 同级目录"""
    if getattr(sys, "frozen", False):
        # sidecar 部署后，模型/FFmpeg/数据等资源由 Tauri 统一放在 exe 同级目录
        # （Tauri resources 按相对路径复制到安装目录根，与 subai-backend.exe 同级）
        return str(Path(sys.executable).parent)
    return str(Path(__file__).parent.parent)


class PathConfig(BaseModel):
    """路径配置"""
    root: str = Field(default_factory=_project_root)
    models_dir: str = Field(default_factory=lambda: os.path.join("{root}", "models", "faster-whisper-small"))
    out_dir: str = Field(default_factory=lambda: os.path.join("{root}", "output"))
    tmp_dir: str = Field(default_factory=lambda: os.path.join("{root}", "output", "_tmp"))
    ffmpeg: str = Field(default_factory=lambda: os.path.join("{root}", "bin", "ffmpeg.exe"))
    terminology_db: str = Field(default_factory=lambda: os.path.join("{root}", "data", "terminology.db"))
    uploads_dir: str = Field(default_factory=lambda: os.path.join("{root}", "data", "uploads"))
    
    def resolve(self, value: str) -> str:
        """解析路径，替换{root}占位符"""
        return value.replace("{root}", self.root)


class ASRConfig(BaseSettings):
    """ASR（语音识别）配置"""
    model_config = SettingsConfigDict(env_prefix="SUBAI_ASR_")
    
    device: str = Field(default="auto", description="设备选择: auto|cuda|cpu")
    compute_type: str = Field(default="auto", description="计算类型: auto|float16|int8|int8_float16")
    beam_size: int = Field(default=5, description="束搜索大小")
    batch_size: int = Field(default=8, description="批量处理大小")
    cpu_threads: int = Field(default=8, description="CPU推理线程数（仅device=cpu时生效）")
    vad_filter: bool = Field(default=True, description="是否启用语音活动检测")
    word_timestamps: bool = Field(default=True, description="是否返回单词级时间戳")


class LLMConfig(BaseSettings):
    """LLM（翻译服务）配置"""
    model_config = SettingsConfigDict(env_prefix="SUBAI_LLM_")
    
    # 模式选择：local=本地koboldcpp, cloud=云端API, hybrid=混合(ASR本地GPU+翻译云端)
    mode: str = Field(default="local", description="翻译模式: local|cloud|hybrid")
    
    # 本地模式配置
    local_url: str = Field(default="http://127.0.0.1:5001/v1/chat/completions", description="本地LLM地址")
    local_model: str = Field(default="koboldcpp", description="本地LLM模型名")
    
    # 云端模式配置
    cloud_url: str = Field(default="", description="云端LLM地址（OpenAI兼容接口）")
    cloud_api_key: str = Field(default="", description="云端LLM API密钥")
    cloud_model: str = Field(default="gpt-4o", description="云端LLM模型名")
    
    # 通用配置
    timeout: float = Field(default=180.0, description="翻译请求超时时间（秒）")
    max_tokens: int = Field(default=256, description="最大输出token数")
    temperature: float = Field(default=0.2, description="翻译温度参数")
    batch_size: int = Field(default=8, description="批量翻译大小")
    
    # 重试配置
    max_retries: int = Field(default=3, description="最大重试次数")
    retry_delay: float = Field(default=1.0, description="重试初始延迟（秒，指数退避）")


class OCRConfig(BaseSettings):
    """OCR（硬字幕识别）配置"""
    model_config = SettingsConfigDict(env_prefix="SUBAI_OCR_")
    
    sample_fps: float = Field(default=2.0, description="采样帧率（帧/秒）")
    min_score: float = Field(default=0.5, description="最低置信度阈值")
    gap_tol: float = Field(default=0.8, description="时间戳合并容忍度（秒）")


class ServerConfig(BaseSettings):
    """服务器配置"""
    model_config = SettingsConfigDict(env_prefix="SUBAI_SERVER_")
    
    host: str = Field(default="0.0.0.0", description="监听地址")
    port: int = Field(default=8000, description="监听端口")
    cors_origins: list[str] = Field(default=["*"], description="CORS允许的来源")
    reload: bool = Field(default=False, description="开发模式是否自动重载")


class ConcurrencyConfig(BaseSettings):
    """并发配置"""
    model_config = SettingsConfigDict(env_prefix="SUBAI_CONCURRENCY_")
    
    # 本地模式：受内存限制，并发数较低
    local_max_concurrent: int = Field(default=2, description="本地模式最大并发数")
    
    # 云端/混合模式：内存充足，并发数可更高
    cloud_max_concurrent: int = Field(default=4, description="云端/混合模式最大并发数")
    
    # 任务队列
    max_queue_size: int = Field(default=100, description="任务队列最大长度")
    
    # 资源监控
    max_memory_usage_gb: float = Field(default=16.0, description="最大内存使用量（GB）")


class CacheConfig(BaseSettings):
    """翻译缓存配置"""
    model_config = SettingsConfigDict(env_prefix="SUBAI_CACHE_")
    
    db_path: str = Field(default_factory=lambda: os.path.join("{root}", "data", "translation_cache.db"))
    max_entries: int = Field(default=10000, description="最大缓存条目数")
    ttl_days: int = Field(default=30, description="缓存有效期（天）")
    eviction_policy: str = Field(default="lru", description="淘汰策略: lru|lfu|fifo")


class SubAIConfig(BaseSettings):
    """主配置类"""
    model_config = SettingsConfigDict(
        env_prefix="SUBAI_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # 子配置
    paths: PathConfig = Field(default_factory=PathConfig)
    asr: ASRConfig = Field(default_factory=ASRConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    ocr: OCRConfig = Field(default_factory=OCRConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    
    # 字幕切分阈值
    max_chars: int = Field(default=20, description="每行最大字符数")
    max_dur: float = Field(default=6.0, description="每行最大时长（秒）")
    break_punct: str = Field(default="。！？!?…；;，,、", description="断句标点")
    
    @property
    def models_dir(self) -> str:
        return self.paths.resolve(self.paths.models_dir)
    
    @property
    def out_dir(self) -> str:
        return self.paths.resolve(self.paths.out_dir)
    
    @property
    def tmp_dir(self) -> str:
        return self.paths.resolve(self.paths.tmp_dir)
    
    @property
    def ffmpeg(self) -> str:
        return self.paths.resolve(self.paths.ffmpeg)
    
    @property
    def terminology_db(self) -> str:
        return self.paths.resolve(self.paths.terminology_db)
    
    @property
    def uploads_dir(self) -> str:
        return self.paths.resolve(self.paths.uploads_dir)
    
    @property
    def cache_db_path(self) -> str:
        return self.paths.resolve(self.cache.db_path)
    
    def get_max_concurrent(self) -> int:
        """根据LLM模式获取最大并发数"""
        if self.llm.mode in ("cloud", "hybrid"):
            return self.concurrency.cloud_max_concurrent
        else:
            return self.concurrency.local_max_concurrent
    
    def get_asr_device(self) -> tuple[str, str]:
        """
        获取ASR设备和计算类型
        
        Returns:
            (device, compute_type) 元组
        """
        if self.asr.device == "auto":
            # 自动检测：检查是否有可用GPU且显存充足
            try:
                import torch
                if torch.cuda.is_available():
                    # 检查显存是否充足（至少4GB）
                    free_mem = torch.cuda.mem_get_info()[0] / (1024**3)
                    if free_mem >= 4.0:
                        return ("cuda", "float16")
            except:
                pass
            return ("cpu", "int8")
        elif self.asr.device == "cuda":
            return ("cuda", "float16")
        else:
            return ("cpu", "int8")
    
    def get_llm_endpoint(self) -> tuple[str, str, str]:
        """
        获取LLM端点配置
        
        Returns:
            (url, model, api_key) 元组
        """
        if self.llm.mode == "local":
            return (self.llm.local_url, self.llm.local_model, "")
        elif self.llm.mode in ("cloud", "hybrid"):
            return (self.llm.cloud_url, self.llm.cloud_model, self.llm.cloud_api_key)
        else:
            # 默认本地
            return (self.llm.local_url, self.llm.local_model, "")


# --------------------------------------------------------------------------- #
# 全局配置实例
# --------------------------------------------------------------------------- #

# 单例模式，全局共享配置
config = SubAIConfig()


def reload_config() -> SubAIConfig:
    """重新加载配置（用于测试或热更新）"""
    global config
    config = SubAIConfig()
    return config