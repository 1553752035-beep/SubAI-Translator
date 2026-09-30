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
import shutil
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
    tasks_db: str = Field(default_factory=lambda: os.path.join("{root}", "data", "tasks.db"))
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


class AuthConfig(BaseSettings):
    """认证与权限配置（三期新增）"""
    model_config = SettingsConfigDict(env_prefix="SUBAI_AUTH_")
    
    jwt_secret: str = Field(default="subai-translator-dev-secret-change-me", description="JWT签名密钥（生产环境务必用环境变量覆盖）")
    jwt_expires_hours: int = Field(default=24, description="JWT过期时间（小时）")
    users_db: str = Field(default_factory=lambda: os.path.join("{root}", "data", "users.db"))
    admin_username: str = Field(default="admin", description="首次启动自动创建的管理员用户名")
    admin_password: str = Field(default="admin123", description="首次启动自动创建的管理员密码（生产环境务必修改）")


class QuotaConfig(BaseSettings):
    """配额与资源限制配置（三期新增）"""
    model_config = SettingsConfigDict(env_prefix="SUBAI_QUOTA_")
    
    enabled: bool = Field(default=True, description="是否启用配额限制")
    max_active_tasks: int = Field(default=10, description="每用户最大活跃任务数（pending+processing）")
    max_terms: int = Field(default=5000, description="每用户最大术语数")
    max_upload_mb: int = Field(default=2048, description="上传文件大小上限（MB）")


class SecurityConfig(BaseSettings):
    """安全加固配置（三期新增）"""
    model_config = SettingsConfigDict(env_prefix="SUBAI_SECURITY_")
    
    # 频率限制（通用 API，按客户端 IP）
    rate_limit_enabled: bool = Field(default=True, description="是否启用频率限制")
    rate_limit_requests: int = Field(default=120, description="每个时间窗口内每 IP 最大请求数")
    rate_limit_window_seconds: int = Field(default=60, description="频率限制时间窗口（秒）")
    
    # 认证接口限流（登录/注册，更严格，防暴力破解）
    auth_rate_limit_requests: int = Field(default=10, description="认证接口每窗口每 IP 最大请求数")
    auth_rate_limit_window_seconds: int = Field(default=60, description="认证接口限流窗口（秒）")
    
    # IP 白名单/黑名单（JSON 数组格式，如 ["1.2.3.4"]）
    ip_whitelist: list[str] = Field(default_factory=list, description="IP 白名单（非空时仅允许列表内 IP 访问）")
    ip_blacklist: list[str] = Field(default_factory=list, description="IP 黑名单（列表内 IP 拒绝访问）")
    
    # API 密钥（X-API-Key 请求头，用于程序化访问，匹配任一即视为服务账户）
    api_keys: list[str] = Field(default_factory=list, description="允许的 API 密钥列表")
    
    # HTTPS
    enable_https: bool = Field(default=False, description="是否启用 HTTPS（生产环境建议反向代理或此处开启）")
    ssl_certfile: str = Field(default="", description="TLS 证书文件路径")
    ssl_keyfile: str = Field(default="", description="TLS 私钥文件路径")


class BackupConfig(BaseSettings):
    """备份与恢复配置（三期新增）"""
    model_config = SettingsConfigDict(env_prefix="SUBAI_BACKUP_")
    
    enabled: bool = Field(default=True, description="是否启用备份功能")
    backup_dir: str = Field(default_factory=lambda: os.path.join("{root}", "data", "backups"), description="备份存储目录")
    max_backups: int = Field(default=10, description="保留的最大备份数量（超出自动清理）")
    auto_backup_interval_hours: float = Field(default=24.0, description="自动备份间隔（小时），0 表示禁用")


class MonitoringConfig(BaseSettings):
    """监控与告警配置（三期新增）"""
    model_config = SettingsConfigDict(env_prefix="SUBAI_MONITORING_")
    
    enabled: bool = Field(default=True, description="是否启用监控指标采集")
    metrics_path: str = Field(default="/api/metrics", description="Prometheus 抓取路径")
    alert_check_interval_seconds: int = Field(default=60, description="告警检查间隔（秒），0 表示禁用后台巡检")
    
    # 告警阈值
    alert_memory_percent: float = Field(default=90.0, description="内存使用率告警阈值（%）")
    alert_queue_percent: float = Field(default=80.0, description="队列积压告警阈值（占最大队列长度的百分比）")
    alert_failure_rate: float = Field(default=0.3, description="任务失败率告警阈值（0-1）")
    alert_latency_seconds: float = Field(default=5.0, description="请求 P99 延迟告警阈值（秒）")


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
    auth: AuthConfig = Field(default_factory=AuthConfig)
    quota: QuotaConfig = Field(default_factory=QuotaConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    backup: BackupConfig = Field(default_factory=BackupConfig)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    
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
        """FFmpeg 可执行文件路径（配置路径不存在时回退到系统 PATH）"""
        resolved = self.paths.resolve(self.paths.ffmpeg)
        if os.path.exists(resolved):
            return resolved
        return shutil.which("ffmpeg") or resolved
    
    @property
    def terminology_db(self) -> str:
        return self.paths.resolve(self.paths.terminology_db)
    
    @property
    def tasks_db(self) -> str:
        return self.paths.resolve(self.paths.tasks_db)
    
    @property
    def uploads_dir(self) -> str:
        return self.paths.resolve(self.paths.uploads_dir)
    
    @property
    def backup_dir(self) -> str:
        return self.paths.resolve(self.backup.backup_dir)
    
    @property
    def cache_db_path(self) -> str:
        return self.paths.resolve(self.cache.db_path)
    
    @property
    def users_db(self) -> str:
        return self.paths.resolve(self.auth.users_db)
    
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
    """
    重新加载配置（用于测试或热更新）

    采用原地更新而非替换对象：保持 config 对象身份稳定，
    使各处 `from src.config import config` 的引用在热更新后仍然有效
    （否则依赖注入 / 中间件等模块会持有旧对象引用，读到过期配置）。
    """
    global config
    new_config = SubAIConfig()
    for field_name in new_config.model_fields:
        setattr(config, field_name, getattr(new_config, field_name))
    return config


def persist_env(updates: dict, env_path: Optional[str] = None) -> str:
    """把若干键写入 .env（存在则整行替换，不存在则追加）。

    用于把运行期修改的设置（如翻译模式）落盘，重启后仍生效。
    打包运行时工作目录即安装目录，.env 与 config 的 env_file 位置一致。
    """
    path = env_path or os.path.join(_project_root(), ".env")
    lines: list[str] = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    for key, value in updates.items():
        new_line = "%s=%s" % (key, value)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == key or stripped.startswith(key + "="):
                lines[i] = new_line
                break
        else:
            lines.append(new_line)

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path