# -*- coding: utf-8 -*-
"""
SubAI Translator —— FastAPI后端服务（二期重构版）
=================================================

重构重点：
1. 集成正式Pipeline（替换pipeline_smoke.py）
2. 任务状态持久化（SQLite）
3. 并发控制（TaskQueue）
4. 翻译缓存（TranslationCache）
5. 支持多格式输出（SRT/VTT/ASS/JSON）
6. 实时进度回调（刷新频率≤1秒）
7. 双模式支持（本地LLM/云端翻译）

API路由：
- GET  /api/health                    健康检查
- POST /api/transcode                 提交转码任务
- GET  /api/task/{task_id}            查询任务状态
- GET  /api/output/{filename}         下载输出文件
- GET  /api/history                   查询历史记录
- POST /api/terminology               添加术语
- GET  /api/terminology               查询术语列表
- POST /api/terminology/import        导入术语
- GET  /api/cache/stats               查询缓存统计
- POST /api/cache/clear               清空缓存
- GET  /api/queue/stats               查询队列统计
- POST /api/config/reload             重载配置
"""
from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from src.config import config, reload_config, persist_env
from src.cancel import (
    TaskCancelled,
    cancel as cancel_task_token,
    register as register_cancel_token,
    unregister as unregister_cancel_token,
)
from src.db.tasks import TaskManager, TaskRecord, get_task_manager
from src.db.terminology import AsyncTerminologyManager
from src.cache.translation_cache import TranslationCache, get_translation_cache
from src.queue.task_queue import TaskQueue, get_task_queue
from src.compose import burn_hardsub, mux_softsub
from src.tts import get_engine as get_tts_engine, synthesize_segments, voice_for_language
from src import llm as llm_module
from src.plugins import init_plugins
from src.plugins import registry as plugin_registry
from src.plugins.manifest import VALID_KINDS as PLUGIN_KINDS
from src.subtitles import load_task_segments, save_task_segments
from src.logging_config import setup_logging
from src.auth.dependencies import get_current_user, get_current_admin
from src.auth.security import create_access_token
from src.auth.users import UserRecord, UserManager, get_user_manager
from src.backup.manager import AsyncBackupManager
from src.security.middleware import (
    ip_filter_middleware,
    rate_limit_middleware,
    security_headers_middleware,
)
from src.monitoring.metrics import REGISTRY, collect_system_metrics
from src.monitoring.alerts import AlertManager, build_default_alert_manager
from src.monitoring.middleware import request_metrics_middleware

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 请求/响应模型
# --------------------------------------------------------------------------- #

class TranscodeRequest(BaseModel):
    """转码请求"""
    video_path: str
    mode: str = "asr"  # asr 或 hardsub
    source_lang: Optional[str] = None  # 如果为None，使用pipeline默认值
    target_lang: str = "en"
    output_format: str = "srt"  # srt/vtt/ass/json
    terms_file: Optional[str] = None  # 术语库文件路径
    priority: str = "medium"  # high/medium/low


class BatchTranscodeItem(BaseModel):
    """批量转码的单个子任务"""
    video_path: str
    mode: str = "asr"
    source_lang: Optional[str] = None
    target_lang: str = "en"
    output_format: str = "srt"
    terms_file: Optional[str] = None
    priority: str = "medium"


class BatchTranscodeRequest(BaseModel):
    """批量转码请求"""
    items: list[BatchTranscodeItem] = Field(..., min_length=1, max_length=50, description="批量任务列表（1-50 个）")


class RegisterRequest(BaseModel):
    """注册请求"""
    username: str = Field(..., min_length=3, max_length=64, description="用户名")
    password: str = Field(..., min_length=6, max_length=128, description="密码（至少6位）")
    email: Optional[str] = Field(default=None, description="邮箱（可选）")


class LoginRequest(BaseModel):
    """登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str = Field(..., description="旧密码")
    new_password: str = Field(..., min_length=6, max_length=128, description="新密码（至少6位）")


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str = "2.0.0"
    llm_mode: str = config.llm.mode
    asr_device: str = config.asr.device
    queue_stats: dict = {}


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    video_path: str
    mode: str
    source_lang: Optional[str]
    target_lang: str
    output_format: str
    status: str
    progress: float
    message: str
    result_files: list[str]
    created_at: str
    updated_at: str
    completed_at: Optional[str]
    error_message: Optional[str]


class BurnRequest(BaseModel):
    """硬字幕烧录请求（四期 4.2）"""
    video_path: str
    subtitle_path: str
    output_name: Optional[str] = None
    crf: int = Field(default=18, ge=0, le=51)
    preset: str = "medium"
    font_name: Optional[str] = None
    font_size: Optional[int] = Field(default=None, ge=8, le=200)


class MuxTrack(BaseModel):
    """软字幕轨"""
    path: str
    language: Optional[str] = None
    title: Optional[str] = None


class MuxRequest(BaseModel):
    """软字幕封装请求（四期 4.2）"""
    video_path: str
    tracks: list[MuxTrack] = Field(..., min_length=1)
    output_name: Optional[str] = None


class DubSegment(BaseModel):
    """配音字幕段"""
    start: float = Field(..., ge=0)
    end: float = Field(..., gt=0)
    text: str


class DubRequest(BaseModel):
    """配音请求（四期 4.1）"""
    segments: list[DubSegment] = Field(..., min_length=1)
    language: Optional[str] = None
    voice: Optional[str] = None
    rate: int = Field(default=0, ge=-10, le=10)
    output_name: Optional[str] = None


class LlmTestRequest(BaseModel):
    """翻译端点连通性测试请求"""
    mode: Optional[str] = None


class LlmModeRequest(BaseModel):
    """翻译模式切换请求"""
    mode: str
    cloud_url: Optional[str] = None
    cloud_model: Optional[str] = None
    cloud_api_key: Optional[str] = None


class SubtitleSegment(BaseModel):
    """单条字幕（在线编辑）"""
    start: float
    end: float
    source: str = ""
    translation: str = ""
    index: Optional[int] = None


class SubtitleSaveRequest(BaseModel):
    """字幕写回请求"""
    segments: list[SubtitleSegment] = Field(..., min_length=1)


# --------------------------------------------------------------------------- #
# 全局资源
# --------------------------------------------------------------------------- #

task_manager: Optional[TaskManager] = None
task_queue_obj: Optional[TaskQueue] = None
translation_cache_obj: Optional[TranslationCache] = None
user_manager_obj: Optional[UserManager] = None
terminology_manager_obj: Optional[AsyncTerminologyManager] = None
backup_manager_obj: Optional[AsyncBackupManager] = None
auto_backup_task: Optional[asyncio.Task] = None
alert_manager_obj: Optional[AlertManager] = None
alert_loop_task: Optional[asyncio.Task] = None


# --------------------------------------------------------------------------- #
# 生命周期管理
# --------------------------------------------------------------------------- #

async def _auto_backup_loop():
    """自动备份后台任务（间隔由配置决定）"""
    interval = config.backup.auto_backup_interval_hours * 3600
    while True:
        await asyncio.sleep(interval)
        try:
            manifest = await backup_manager_obj.create_backup()
            logger.info("自动备份完成: %s", manifest["id"])
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error("自动备份失败: %s", e)


def _collect_snapshot() -> dict:
    """
    组装用于告警评估的运行时快照：
    系统资源 + 队列状态 + 任务/请求累计指标。
    """
    system = collect_system_metrics()

    queue_size = 0
    max_queue_size = 0
    running_count = 0
    if task_queue_obj is not None:
        queue_size = task_queue_obj.queue_size
        max_queue_size = task_queue_obj.max_queue_size
        running_count = task_queue_obj.running_count

    # 请求延迟 P99（从直方图 bucket 估算）
    p99 = None
    hist = REGISTRY.snapshot()["histograms"].get(
        "subai_request_duration_seconds"
    )
    if hist and hist["count"] > 0:
        total = hist["count"]
        threshold = int(total * 0.99) or 1
        cum = 0
        for bound in sorted(hist["buckets"]):
            cum += hist["buckets"][bound]
            if cum >= threshold:
                p99 = bound
                break

    return {
        "memory_percent": system.get("memory_percent"),
        "cpu_percent": system.get("cpu_percent"),
        "queue_size": queue_size,
        "max_queue_size": max_queue_size,
        "running_count": running_count,
        "task_succeeded": int(REGISTRY.get_counter("subai_task_completed_total")),
        "task_failed": int(REGISTRY.get_counter("subai_task_failed_total")),
        "request_latency_p99": p99,
    }


async def _alert_loop():
    """告警巡检后台任务（间隔由配置决定）"""
    interval = config.monitoring.alert_check_interval_seconds
    while True:
        await asyncio.sleep(interval)
        if alert_manager_obj is not None:
            alert_manager_obj.evaluate(_collect_snapshot())


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 初始化统一日志（级别受 SUBAI_LOG_LEVEL 环境变量控制）
    setup_logging()

    # 启动时初始化
    logger.info("正在启动SubAI Translator API服务...")
    
    global task_manager, task_queue_obj, translation_cache_obj, user_manager_obj, terminology_manager_obj, backup_manager_obj, auto_backup_task, alert_manager_obj, alert_loop_task

    # 初始化任务管理器
    task_manager = await get_task_manager()
    logger.info("任务管理器已初始化")

    # 初始化翻译缓存
    translation_cache_obj = await get_translation_cache()
    logger.info("翻译缓存已初始化")

    # 初始化术语库管理器（异步封装，内部触发 _ensure_db 建表与 user_id 迁移）
    terminology_manager_obj = AsyncTerminologyManager(config.terminology_db)
    logger.info("术语库管理器已初始化")

    # 初始化用户管理器
    user_manager_obj = await get_user_manager()
    logger.info("用户管理器已初始化")

    # 首次启动自动创建默认管理员
    if await user_manager_obj.count_users() == 0:
        await user_manager_obj.create_user(
            username=config.auth.admin_username,
            password=config.auth.admin_password,
            role="admin"
        )
        logger.info(f"已创建默认管理员账户: {config.auth.admin_username}")

    # 初始化任务队列
    max_concurrent = config.get_max_concurrent()
    task_queue_obj = await get_task_queue(task_manager, max_concurrent)
    logger.info(f"任务队列已初始化，最大并发={max_concurrent}")

    # 初始化备份管理器（三期新增）
    backup_manager_obj = AsyncBackupManager(config.backup_dir, config.backup.max_backups)
    logger.info("备份管理器已初始化")

    # 启动自动备份（若启用且间隔>0）
    if config.backup.enabled and config.backup.auto_backup_interval_hours > 0:
        auto_backup_task = asyncio.create_task(_auto_backup_loop())
        logger.info(f"自动备份已启动，间隔={config.backup.auto_backup_interval_hours}小时")

    # 初始化告警管理器（三期：监控与告警）
    alert_manager_obj = build_default_alert_manager()
    logger.info("告警管理器已初始化")

    # 启动告警巡检（若启用且间隔>0）
    if config.monitoring.enabled and config.monitoring.alert_check_interval_seconds > 0:
        alert_loop_task = asyncio.create_task(_alert_loop())
        logger.info(f"告警巡检已启动，间隔={config.monitoring.alert_check_interval_seconds}秒")

    # 初始化插件系统（四期 4.3）：失败不影响主流程
    try:
        plugin_count = init_plugins()
        logger.info(f"插件系统已初始化，发现 {plugin_count} 个插件")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"插件系统初始化失败（不影响主流程）: {e!r}")

    logger.info("API服务启动完成")
    
    yield
    
    # 关闭时清理
    logger.info("正在关闭API服务...")
    if auto_backup_task:
        auto_backup_task.cancel()
    if alert_loop_task:
        alert_loop_task.cancel()
    if task_queue_obj:
        await task_queue_obj.shutdown()
    if task_manager:
        await task_manager.close()
    if translation_cache_obj:
        await translation_cache_obj.close()
    if user_manager_obj:
        await user_manager_obj.close()
    logger.info("API服务已关闭")


# --------------------------------------------------------------------------- #
# FastAPI应用
# --------------------------------------------------------------------------- #

app = FastAPI(
    title="SubAI Translator API",
    description="AI视频字幕识别与翻译服务",
    version="2.0.0",
    lifespan=lifespan
)

# CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 安全中间件（三期）：注册顺序决定执行顺序，后注册的先执行（请求方向）
# 请求方向：ip_filter → rate_limit → security_headers → 路由
app.middleware("http")(security_headers_middleware)
app.middleware("http")(rate_limit_middleware)
app.middleware("http")(ip_filter_middleware)
# 指标中间件放在最外层，统计含安全过滤在内的完整请求耗时
app.middleware("http")(request_metrics_middleware)


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #

def ensure_output_dir() -> str:
    """确保输出目录存在"""
    os.makedirs(config.out_dir, exist_ok=True)
    return config.out_dir


def clean_task_id(task_id: str) -> str:
    """清理任务ID（去除非法字符）"""
    return task_id.replace("/", "_").replace("\\", "_").replace("..", "_")


def get_video_filename(video_path: str) -> str:
    """获取视频文件名（不含扩展名）"""
    return Path(video_path).stem


def _scope_user_id(current_user: UserRecord) -> Optional[str]:
    """
    计算数据隔离范围（三期数据隔离）

    管理员返回 None（不过滤，可查看/管理全部数据），
    普通用户返回自身 user_id（仅能访问属于自己的数据）。
    """
    if current_user.role == "admin":
        return None
    return current_user.user_id


# --------------------------------------------------------------------------- #
# Pipeline进度回调
# --------------------------------------------------------------------------- #

async def pipeline_progress_callback(progress: float, message: str, task_id: Optional[str] = None) -> None:
    """
    Pipeline进度回调函数（适配pipeline.py的签名）
    
    接收Pipeline的进度更新，实时写入任务状态
    
    Args:
        progress: 进度值（0.0-1.0）
        message: 进度消息
        task_id: 任务ID（从闭包捕获）
    """
    global task_manager
    
    if task_manager is None:
        return
    
    # 更新任务状态
    await task_manager.update_task(
        task_id=task_id or progress_callback_task_id,
        status="processing",
        progress=progress,
        message=message
    )


# 全局变量：存储当前任务的task_id（因为pipeline.py不支持额外参数）
progress_callback_task_id: str = ""


# --------------------------------------------------------------------------- #
# 任务处理函数
# --------------------------------------------------------------------------- #

async def process_transcode_task(
    task_id: str,
    video_path: str,
    mode: str = "asr",
    source_lang: Optional[str] = None,
    target_lang: str = "en",
    output_format: str = "srt",
    terms_file: Optional[str] = None
) -> None:
    """
    处理转码任务（核心逻辑）
    
    集成正式Pipeline，支持进度回调
    使用run_in_executor避免阻塞事件循环
    
    Args:
        task_id: 任务ID
        video_path: 视频文件路径
        mode: 识别模式（asr/hardsub）
        source_lang: 源语言
        target_lang: 目标语言
        output_format: 输出格式
        terms_file: 术语库文件
    """
    global task_manager, translation_cache_obj, progress_callback_task_id
    
    if task_manager is None:
        raise RuntimeError("任务管理器未初始化")
    
    # 设置全局task_id（供进度回调使用）
    progress_callback_task_id = task_id

    # 注册协作式取消令牌：DELETE /api/task/{id} 置位后，流水线会在下一个检查点中止
    cancel_token = register_cancel_token(task_id)
    
    # 更新任务状态为processing
    await task_manager.update_task(
        task_id=task_id,
        status="processing",
        progress=0.0,
        message="任务已开始处理"
    )
    
    try:
        # 导入正式Pipeline
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from src.pipeline import run_pipeline

        # 构建Pipeline参数
        output_dir = ensure_output_dir()

        # 捕获当前事件循环，供同步线程内的进度回调跨线程提交协程
        main_loop = asyncio.get_running_loop()

        def _thread_safe_progress_cb(progress: float, message: str) -> None:
            """
            在 run_in_executor 同步线程中触发的进度回调。
            用 run_coroutine_threadsafe 把回调协程安全送回主事件循环。
            """
            coro = pipeline_progress_callback(progress, message, task_id)
            try:
                future = asyncio.run_coroutine_threadsafe(coro, main_loop)
                # 不阻塞线程，但记录异常便于排查
                future.add_done_callback(
                    lambda f: logger.error("进度回调失败: %r", f.exception())
                    if f.exception() else None
                )
            except Exception as e:
                logger.warning("跨线程提交进度回调失败: %r", e)

        # 收集翻译统计（术语命中 / 缓存命中 / 失败行数），用于区分完全成功、部分失败、翻译全失败
        stats: dict = {}

        # 在线程池中执行同步的run_pipeline函数
        result = await main_loop.run_in_executor(
            None,  # 使用默认线程池
            lambda: run_pipeline(
                video=video_path,
                mode=mode,
                source_lang=source_lang,
                target_lang=target_lang,
                terms_file=terms_file,
                output_format=output_format,
                progress_callback=_thread_safe_progress_cb,
                stats=stats,
                should_cancel=cancel_token.is_set,
            )
        )

        files = result if isinstance(result, list) else []
        failed = int(stats.get("failed", 0) or 0)
        total = int(stats.get("total", 0) or 0)
        terms = int(stats.get("terms", 0) or 0)
        cache_hits = int(stats.get("cache_hits", 0) or 0)

        if total and failed >= total:
            # 翻译整体失败：任务标记失败，但保留识别结果（run_pipeline 已额外输出原文转录）
            await task_manager.update_task(
                task_id=task_id,
                status="failed",
                progress=1.0,
                message="翻译全部失败，已保留原文转录",
                error_message="翻译后端不可用：%d/%d 行翻译失败" % (failed, total),
                result_files=files,
            )
            REGISTRY.inc("subai_task_failed_total")
            logger.error("任务 %s 翻译全部失败（%d/%d）", task_id, failed, total)
        elif failed:
            await task_manager.update_task(
                task_id=task_id,
                status="completed",
                progress=1.0,
                message="完成（%d/%d 行未翻译，已保留原文 · 术语命中 %d · 缓存命中 %d）" % (failed, total, terms, cache_hits),
                result_files=files,
            )
            REGISTRY.inc("subai_task_completed_total")
            logger.warning("任务 %s 部分翻译失败（%d/%d）", task_id, failed, total)
        else:
            await task_manager.update_task(
                task_id=task_id,
                status="completed",
                progress=1.0,
                message="任务完成（%d 行 · 术语命中 %d · 缓存命中 %d）" % (total, terms, cache_hits),
                result_files=files,
            )
            REGISTRY.inc("subai_task_completed_total")

        logger.info(f"任务 {task_id} 处理完成，输出文件数: {len(files)}")
        
    except TaskCancelled:
        # 协作式取消：正常控制流，标记 cancelled 后直接返回（不 re-raise，
        # 以免任务队列的异常分支再把它覆盖成 failed）
        await task_manager.update_task(
            task_id=task_id,
            status="cancelled",
            message="任务已取消",
            error_message="cancelled by user",
        )
        REGISTRY.inc("subai_task_cancelled_total")
        logger.info("任务 %s 已被用户取消（协作式中止）", task_id)
        return

    except Exception as e:
        # 更新任务状态为failed
        await task_manager.update_task(
            task_id=task_id,
            status="failed",
            error_message=str(e)
        )
        REGISTRY.inc("subai_task_failed_total")
        logger.error(f"任务 {task_id} 处理失败: {e}", exc_info=True)
        raise
    finally:
        # 清空全局task_id 与取消令牌
        progress_callback_task_id = ""
        unregister_cancel_token(task_id)


# --------------------------------------------------------------------------- #
# API路由
# --------------------------------------------------------------------------- #

@app.get("/api/health")
async def health_check():
    """健康检查"""
    queue_stats = {}
    if task_queue_obj:
        queue_stats = await task_queue_obj.get_stats()
    
    return HealthResponse(
        status="ok",
        llm_mode=config.llm.mode,
        asr_device=config.asr.device,
        queue_stats=queue_stats
    )


@app.get("/api/system/asr-device")
async def asr_device_info(current_user: UserRecord = Depends(get_current_user)):
    """ASR 设备明细（配置值 / 实际生效值 / CUDA 支持 / 空闲显存 / DLL 目录）。"""
    return config.describe_asr_device()


@app.get("/api/metrics")
async def metrics():
    """
    监控指标（Prometheus 文本格式）

    供 Prometheus / Grafana 抓取。默认路径 /api/metrics（可用
    SUBAI_MONITORING_METRICS_PATH 覆盖，但需同步修改本路由装饰器）。
    """
    if not config.monitoring.enabled:
        raise HTTPException(status_code=404, detail="监控未启用")
    return Response(
        content=REGISTRY.to_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.post("/api/auth/register")
async def register(request: RegisterRequest):
    """注册新用户（默认 role=user）"""
    global user_manager_obj

    if user_manager_obj is None:
        raise RuntimeError("用户管理器未初始化")

    try:
        user = await user_manager_obj.create_user(
            username=request.username,
            password=request.password,
            role="user",
            email=request.email
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"message": "注册成功", "user": user.to_dict()}


@app.post("/api/auth/login")
async def login(request: LoginRequest):
    """登录，返回 JWT 访问令牌"""
    global user_manager_obj

    if user_manager_obj is None:
        raise RuntimeError("用户管理器未初始化")

    user = await user_manager_obj.verify_credentials(request.username, request.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    expires_in = config.auth.jwt_expires_hours * 3600
    token = create_access_token(
        user_id=user.user_id,
        username=user.username,
        role=user.role,
        secret=config.auth.jwt_secret,
        expires_in_seconds=expires_in
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": expires_in,
        "user": user.to_dict()
    }


@app.get("/api/auth/me")
async def auth_me(current_user: UserRecord = Depends(get_current_user)):
    """查询当前登录用户信息"""
    return current_user.to_dict()


@app.post("/api/auth/change-password")
async def change_password(
    request: ChangePasswordRequest,
    current_user: UserRecord = Depends(get_current_user)
):
    """修改当前用户密码"""
    global user_manager_obj

    if user_manager_obj is None:
        raise RuntimeError("用户管理器未初始化")

    verified = await user_manager_obj.verify_credentials(
        current_user.username, request.old_password
    )
    if not verified:
        raise HTTPException(status_code=400, detail="旧密码错误")

    await user_manager_obj.change_password(current_user.user_id, request.new_password)
    return {"message": "密码已修改"}


@app.post("/api/upload")
async def upload_video_file(
    file: UploadFile,
    current_user: UserRecord = Depends(get_current_user)
):
    """
    上传视频文件（multipart/form-data，需认证）

    将上传的文件保存到 config.uploads_dir，返回保存后的绝对路径，
    供后续 /api/transcode 提交任务使用。浏览器与桌面端均可调用。

    返回：
    - filename: 原始文件名
    - video_path: 保存后的绝对路径
    - size_bytes: 文件大小（字节）
    """
    allowed_exts = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".ts"}
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()

    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext or '未知'}")

    uploads_dir = config.uploads_dir
    os.makedirs(uploads_dir, exist_ok=True)

    # 生成唯一文件名，避免同名覆盖
    safe_name = Path(filename).name
    dest = os.path.join(uploads_dir, f"{uuid.uuid4().hex[:12]}_{safe_name}")

    # 上传大小上限（MB → 字节），仅普通用户受限（admin 豁免）
    max_bytes = config.quota.max_upload_mb * 1024 * 1024
    total = 0
    try:
        with open(dest, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)  # 1MB 分块写入
                if not chunk:
                    break
                total += len(chunk)
                # 配额检查：普通用户上传大小上限（写入前校验，避免残留超限字节）
                if config.quota.enabled and current_user.role != "admin" and total > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"上传文件超过大小上限（{config.quota.max_upload_mb}MB）"
                    )
                f.write(chunk)
    except HTTPException:
        # 业务异常（如大小超限）：清理残留文件后重新抛出
        if os.path.exists(dest):
            os.remove(dest)
        raise
    except Exception:
        # 写入失败时清理残留文件
        if os.path.exists(dest):
            os.remove(dest)
        raise HTTPException(status_code=500, detail="文件保存失败")
    finally:
        await file.close()

    return {
        "filename": safe_name,
        "video_path": dest,
        "size_bytes": total,
    }


async def _submit_one_transcode(item, current_user: UserRecord) -> dict:
    """
    提交单个转码任务（供单任务与批量接口复用）。

    Args:
        item: TranscodeRequest 或 BatchTranscodeItem（字段一致）
        current_user: 当前用户

    Returns:
        成功：{"task_id", "status", "video_path"}
        失败：{"video_path", "error"}
    """
    global task_manager, task_queue_obj

    if task_manager is None or task_queue_obj is None:
        raise RuntimeError("服务未初始化")

    # 验证视频文件
    if not os.path.exists(item.video_path):
        return {"video_path": item.video_path, "error": f"视频文件不存在: {item.video_path}"}

    # 生成任务ID
    task_id = str(uuid.uuid4())[:8]
    video_filename = get_video_filename(item.video_path)
    task_id = f"{task_id}_{clean_task_id(video_filename)}"

    # 创建任务记录（归属当前用户，实现数据隔离）
    task = await task_manager.create_task(
        task_id=task_id,
        video_path=item.video_path,
        mode=item.mode,
        source_lang=item.source_lang,
        target_lang=item.target_lang,
        output_format=item.output_format,
        terms_file=item.terms_file,
        user_id=current_user.user_id
    )

    # 提交到任务队列
    success = await task_queue_obj.submit(
        task_id=task_id,
        callback=process_transcode_task,
        priority=item.priority,
        video_path=item.video_path,
        mode=item.mode,
        source_lang=item.source_lang,
        target_lang=item.target_lang,
        output_format=item.output_format,
        terms_file=item.terms_file
    )

    if not success:
        await task_manager.update_task(task_id=task_id, status="failed", message="任务队列已满")
        return {"video_path": item.video_path, "error": "任务队列已满"}

    return {"task_id": task_id, "status": task.status, "video_path": item.video_path}


@app.post("/api/transcode")
async def transcode(
    request: TranscodeRequest,
    background_tasks: BackgroundTasks,
    current_user: UserRecord = Depends(get_current_user)
):
    """
    提交单个转码任务（需认证）

    请求体：
    - video_path: 视频文件路径
    - mode: 识别模式（asr/hardsub）
    - source_lang: 源语言（可选）
    - target_lang: 目标语言（默认en）
    - output_format: 输出格式（srt/vtt/ass/json）
    - terms_file: 术语库文件（可选）
    - priority: 优先级（high/medium/low）
    """
    global task_manager

    if task_manager is None:
        raise RuntimeError("服务未初始化")

    # 配额检查：普通用户活跃任务数上限（admin 豁免）
    if config.quota.enabled and current_user.role != "admin":
        active = await task_manager.count_active_tasks(current_user.user_id)
        if active >= config.quota.max_active_tasks:
            raise HTTPException(
                status_code=429,
                detail=f"活跃任务数已达上限（{config.quota.max_active_tasks}），请等待任务完成后再提交"
            )

    result = await _submit_one_transcode(request, current_user)
    if "error" in result:
        if result["error"].startswith("视频文件不存在"):
            raise HTTPException(status_code=404, detail=result["error"])
        raise HTTPException(status_code=503, detail=result["error"])

    return {
        "task_id": result["task_id"],
        "status": result["status"],
        "message": "任务已提交到队列"
    }


@app.post("/api/transcode/batch")
async def transcode_batch(
    request: BatchTranscodeRequest,
    current_user: UserRecord = Depends(get_current_user)
):
    """
    批量提交转码任务（需认证，部分失败不影响其他）

    请求体：
    - items: 子任务列表（1-50 个），每个字段同单任务接口

    返回：
    - total / succeeded / failed: 总数 / 成功数 / 失败数
    - tasks: 每个子任务的结果（含 task_id 或 error）
    """
    global task_manager

    if task_manager is None:
        raise RuntimeError("服务未初始化")

    # 配额检查：活跃任务 + 批量数量 不能超过上限
    if config.quota.enabled and current_user.role != "admin":
        active = await task_manager.count_active_tasks(current_user.user_id)
        if active + len(request.items) > config.quota.max_active_tasks:
            raise HTTPException(
                status_code=429,
                detail=f"批量提交将超过活跃任务数上限（{config.quota.max_active_tasks}），当前活跃 {active} 个"
            )

    # 逐个提交，收集结果
    results = []
    succeeded = 0
    for item in request.items:
        result = await _submit_one_transcode(item, current_user)
        results.append(result)
        if "task_id" in result:
            succeeded += 1

    return {
        "total": len(request.items),
        "succeeded": succeeded,
        "failed": len(request.items) - succeeded,
        "tasks": results,
    }


@app.get("/api/task/{task_id}")
async def get_task(
    task_id: str,
    current_user: UserRecord = Depends(get_current_user)
):
    """查询任务状态（需认证，普通用户只能查自己的任务）"""
    global task_manager

    if task_manager is None:
        raise RuntimeError("任务管理器未初始化")

    task = await task_manager.get_task(task_id, user_id=_scope_user_id(current_user))

    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    return TaskStatusResponse(**task.to_dict())


@app.delete("/api/task/{task_id}")
async def delete_task(
    task_id: str,
    current_user: UserRecord = Depends(get_current_user)
):
    """
    取消/删除任务（需认证，普通用户只能操作自己的任务）

    - 正在处理的任务：置位协作式取消令牌，流水线会在**下一个检查点**主动中止
      （抽音轨前 / 识别后 / 每个翻译批次前 / 写盘前），并标记 cancelled；
    - 正在排队的任务：同样置位并标记 cancelled；
    - 已完成任务：仅做软删除（标记 archived）。

    说明：Python 线程无法被安全强杀，因此采用协作式取消；中止粒度取决于当前
    处于哪一步——最坏情况是"当前这一步跑完"（例如 ASR 推理本身不可中断）。
    """
    global task_manager, task_queue_obj

    if task_manager is None:
        raise RuntimeError("任务管理器未初始化")

    task = await task_manager.get_task(task_id, user_id=_scope_user_id(current_user))
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    if task.status in ("completed", "failed"):
        # 已结束的任务只标记 archived，不动历史
        await task_manager.update_task(
            task_id=task_id,
            status="archived",
            message="用户已归档"
        )
        return {"task_id": task_id, "message": "已归档"}

    # 先置位协作式取消令牌：若任务正在执行，流水线会在下一个检查点主动中止
    signalled = cancel_task_token(task_id)

    # 进行中或排队：标记 cancelled
    await task_manager.update_task(
        task_id=task_id,
        status="cancelled",
        message="用户已取消（已通知执行线程中止）" if signalled else "用户已取消",
        error_message="cancelled by user"
    )
    return {
        "task_id": task_id,
        "message": "已取消，执行线程将在下一个检查点中止" if signalled else "已取消",
        "signalled": signalled,
    }


@app.get("/api/output/{filename}")
async def get_output_file(
    filename: str,
    current_user: UserRecord = Depends(get_current_user)
):
    """
    下载输出文件（需认证）
    
    支持所有格式（SRT/VTT/ASS/JSON）
    """
    output_dir = ensure_output_dir()
    file_path = os.path.join(output_dir, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"文件不存在: {filename}")
    
    # 设置MIME类型
    mime_type, _ = mimetypes.guess_type(filename)
    if mime_type is None:
        mime_type = "application/octet-stream"
    
    return FileResponse(
        file_path,
        media_type=mime_type,
        filename=filename
    )


@app.get("/api/history")
async def get_history(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: UserRecord = Depends(get_current_user)
):
    """
    查询历史记录（需认证，普通用户只能看到自己的任务）
    
    参数：
    - status: 按状态过滤（可选）
    - limit: 返回数量限制
    - offset: 偏移量
    """
    global task_manager
    
    if task_manager is None:
        raise RuntimeError("任务管理器未初始化")
    
    tasks = await task_manager.list_tasks(
        status=status,
        user_id=_scope_user_id(current_user),
        limit=limit,
        offset=offset
    )
    
    return {
        "tasks": [task.to_dict() for task in tasks],
        "total": len(tasks)
    }


@app.get("/api/terminology")
async def get_terminology(
    category: Optional[str] = None,
    priority: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 100,
    current_user: UserRecord = Depends(get_current_user)
):
    """
    查询术语列表（需认证）

    普通用户可看到系统术语 + 自己的术语；管理员可看到全部术语。

    参数：
    - category: 按分类过滤（可选）
    - priority: 按优先级过滤（可选）
    - keyword: 关键词搜索（可选）
    - limit: 返回数量限制
    """
    global terminology_manager_obj

    if terminology_manager_obj is None:
        raise RuntimeError("术语库管理器未初始化")

    user_id = _scope_user_id(current_user)
    terms = await terminology_manager_obj.list_terms(
        category=category,
        priority=priority,
        keyword=keyword,
        user_id=user_id,
        include_system=(user_id is not None)
    )

    # list_terms 不内置 limit，这里截断
    terms = terms[:limit]

    return {"terms": terms, "total": len(terms)}


@app.post("/api/terminology")
async def add_term(
    request: dict,
    current_user: UserRecord = Depends(get_current_user)
):
    """
    添加术语（需认证，术语归属当前用户）
    
    请求体：
    - source_text: 源文本
    - translation: 译文
    - priority: 优先级（high/medium/low，默认medium）
    - category: 分类（可选）
    """
    global terminology_manager_obj

    source_text = request.get("source_text", "").strip()
    translation = request.get("translation", "").strip()
    priority = request.get("priority", "medium")
    category = request.get("category", "custom")
    
    if not source_text or not translation:
        raise HTTPException(status_code=400, detail="source_text和translation不能为空")
    
    if terminology_manager_obj is None:
        raise RuntimeError("术语库管理器未初始化")

    # 配额检查：普通用户术语数上限（admin 豁免）
    if config.quota.enabled and current_user.role != "admin":
        stats = await terminology_manager_obj.get_stats(user_id=current_user.user_id)
        if stats["total_terms"] >= config.quota.max_terms:
            raise HTTPException(
                status_code=429,
                detail=f"术语数量已达上限（{config.quota.max_terms}）"
            )

    # admin 添加的术语作为系统术语（user_id=None，全局共享）；普通用户归属自己
    term_user_id = None if current_user.role == "admin" else current_user.user_id
    await terminology_manager_obj.add_term(
        source=source_text,
        translation=translation,
        priority=priority,
        category=category,
        user_id=term_user_id
    )

    return {"message": "术语已添加"}


@app.post("/api/terminology/import")
async def import_terms(
    file: UploadFile,
    current_user: UserRecord = Depends(get_current_user)
):
    """
    导入术语（JSON格式，需认证，术语归属当前用户）
    
    支持格式：
    [
        {"source_text": "Hello", "translation": "你好", "priority": "high"},
        ...
    ]
    """
    global terminology_manager_obj

    if terminology_manager_obj is None:
        raise RuntimeError("术语库管理器未初始化")

    content = await file.read()
    try:
        terms = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="术语必须是合法JSON")
    
    if not isinstance(terms, list):
        raise HTTPException(status_code=400, detail="术语必须是JSON数组")
    
    # admin 导入的术语作为系统术语（user_id=None）；普通用户归属自己
    term_user_id = None if current_user.role == "admin" else current_user.user_id

    # 配额检查：普通用户术语数上限（admin 豁免），导入时截断到剩余额度
    remaining = None
    if config.quota.enabled and current_user.role != "admin":
        stats = await terminology_manager_obj.get_stats(user_id=current_user.user_id)
        current_count = stats["total_terms"]
        if current_count >= config.quota.max_terms:
            raise HTTPException(
                status_code=429,
                detail=f"术语数量已达上限（{config.quota.max_terms}）"
            )
        remaining = config.quota.max_terms - current_count

    inserted = 0
    for term in terms:
        if remaining is not None and inserted >= remaining:
            logger.warning(f"导入术语达到配额上限，已截断（上限 {config.quota.max_terms}）")
            break
        try:
            source_text = (term.get("source_text") or "").strip()
            translation = (term.get("translation") or "").strip()
            priority = term.get("priority", "medium")
            category = term.get("category", "custom")
            
            if source_text and translation:
                await terminology_manager_obj.add_term(
                    source=source_text,
                    translation=translation,
                    priority=priority,
                    category=category,
                    user_id=term_user_id
                )
                inserted += 1
        except Exception as e:
            logger.warning(f"导入术语失败: {e}")
    
    return {"message": f"成功导入 {inserted} 个术语"}


@app.delete("/api/terminology/{source}")
async def delete_term(
    source: str,
    current_user: UserRecord = Depends(get_current_user)
):
    """
    删除术语（需认证）

    - 普通用户：仅可删除自己的术语
    - 管理员：删除系统术语（user_id IS NULL）

    路径参数：
    - source: 术语原文（需 URL 编码）
    """
    global terminology_manager_obj

    if terminology_manager_obj is None:
        raise RuntimeError("术语库管理器未初始化")

    target_user_id = None if current_user.role == "admin" else current_user.user_id
    deleted = await terminology_manager_obj.delete_term(source, user_id=target_user_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"术语不存在或无权删除: {source}")

    return {"message": "术语已删除"}


@app.get("/api/cache/stats")
async def cache_stats(current_user: UserRecord = Depends(get_current_admin)):
    """查询缓存统计（仅管理员）"""
    global translation_cache_obj
    
    if translation_cache_obj is None:
        raise RuntimeError("翻译缓存未初始化")
    
    stats = await translation_cache_obj.get_stats()
    return stats


@app.post("/api/cache/clear")
async def cache_clear(current_user: UserRecord = Depends(get_current_admin)):
    """清空缓存（仅管理员）"""
    global translation_cache_obj
    
    if translation_cache_obj is None:
        raise RuntimeError("翻译缓存未初始化")
    
    count = await translation_cache_obj.clear()
    return {"message": f"已清空 {count} 条缓存"}


@app.get("/api/queue/stats")
async def queue_stats(current_user: UserRecord = Depends(get_current_admin)):
    """查询队列统计（仅管理员）"""
    global task_queue_obj
    
    if task_queue_obj is None:
        raise RuntimeError("任务队列未初始化")
    
    return await task_queue_obj.get_stats()


@app.post("/api/config/reload")
async def config_reload(current_user: UserRecord = Depends(get_current_admin)):
    """重载配置（仅管理员）"""
    global config
    
    # reload_config 原地更新配置对象，保持各模块引用有效；此处同步本模块引用
    config = reload_config()
    return {"message": "配置已重载", "config": {
        "llm_mode": config.llm.mode,
        "asr_device": config.asr.device,
        "max_concurrent": config.get_max_concurrent()
    }}


# --------------------------------------------------------------------------- #
# 备份与恢复（仅管理员）
# --------------------------------------------------------------------------- #

@app.post("/api/admin/backup")
async def backup_create(current_user: UserRecord = Depends(get_current_admin)):
    """创建完整备份（术语库/任务库/用户库/缓存/配置快照）"""
    global backup_manager_obj
    if backup_manager_obj is None:
        raise RuntimeError("备份管理器未初始化")
    manifest = await backup_manager_obj.create_backup()
    return manifest


@app.get("/api/admin/backups")
async def backup_list(current_user: UserRecord = Depends(get_current_admin)):
    """列出所有备份（按时间倒序）"""
    global backup_manager_obj
    if backup_manager_obj is None:
        raise RuntimeError("备份管理器未初始化")
    return await backup_manager_obj.list_backups()


@app.delete("/api/admin/backup/{backup_id}")
async def backup_delete(backup_id: str, current_user: UserRecord = Depends(get_current_admin)):
    """删除指定备份"""
    global backup_manager_obj
    if backup_manager_obj is None:
        raise RuntimeError("备份管理器未初始化")
    if not await backup_manager_obj.delete_backup(backup_id):
        raise HTTPException(status_code=404, detail=f"备份不存在: {backup_id}")
    return {"message": "备份已删除"}


@app.post("/api/admin/backup/{backup_id}/restore")
async def backup_restore(backup_id: str, current_user: UserRecord = Depends(get_current_admin)):
    """
    恢复备份（仅管理员）

    流程：关闭活动管理器 → 覆盖恢复文件 → 重新初始化管理器。
    术语库管理器无持久连接，恢复后下次访问自动生效。
    """
    global task_manager, task_queue_obj, translation_cache_obj, user_manager_obj, backup_manager_obj

    if backup_manager_obj is None:
        raise RuntimeError("备份管理器未初始化")

    # 0. 校验备份存在（在关闭管理器之前，避免关闭后恢复失败导致状态不一致）
    backups = await backup_manager_obj.list_backups()
    if not any(b["id"] == backup_id for b in backups):
        raise HTTPException(status_code=404, detail=f"备份不存在: {backup_id}")

    # 1. 关闭队列与各管理器（释放文件句柄，确保 Windows 下可覆盖）
    if task_queue_obj:
        await task_queue_obj.shutdown()
    if task_manager:
        await task_manager.close()
    if translation_cache_obj:
        await translation_cache_obj.close()
    if user_manager_obj:
        await user_manager_obj.close()

    # 2. 重置各模块单例，使重新初始化走全新连接
    import src.db.tasks as tasks_mod
    import src.auth.users as users_mod
    import src.cache.translation_cache as cache_mod
    import src.queue.task_queue as queue_mod

    tasks_mod.task_manager = None
    users_mod._user_manager = None
    cache_mod.translation_cache = None
    queue_mod.task_queue = None

    # 3. 恢复文件
    result = await backup_manager_obj.restore_backup(backup_id)

    # 4. 重新初始化管理器
    task_manager = await get_task_manager()
    translation_cache_obj = await get_translation_cache()
    user_manager_obj = await get_user_manager()
    task_queue_obj = await get_task_queue(task_manager, config.get_max_concurrent())

    return {"message": "备份已恢复", **result}


# --------------------------------------------------------------------------- #
# 视频合成（四期 4.2）
# --------------------------------------------------------------------------- #

@app.post("/api/video/burn")
async def video_burn(request: BurnRequest, current_user: UserRecord = Depends(get_current_user)):
    """硬字幕烧录：把字幕烧进画面，输出到 output 目录。"""
    if not os.path.isfile(request.video_path):
        raise HTTPException(status_code=404, detail=f"视频不存在: {request.video_path}")
    if not os.path.isfile(request.subtitle_path):
        raise HTTPException(status_code=404, detail=f"字幕不存在: {request.subtitle_path}")

    stem = Path(request.video_path).stem
    filename = request.output_name or f"{stem}.hardsub.mp4"
    out_path = os.path.join(ensure_output_dir(), filename)
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: burn_hardsub(
                request.video_path, request.subtitle_path, out_path,
                crf=request.crf, preset=request.preset,
                font_name=request.font_name, font_size=request.font_size,
            ),
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"硬字幕烧录失败: {e}")
    return {"output_path": out_path, "filename": filename}


@app.post("/api/video/mux")
async def video_mux(request: MuxRequest, current_user: UserRecord = Depends(get_current_user)):
    """软字幕封装：把一条或多条字幕作为独立轨封装进 MKV。"""
    if not os.path.isfile(request.video_path):
        raise HTTPException(status_code=404, detail=f"视频不存在: {request.video_path}")
    for t in request.tracks:
        if not os.path.isfile(t.path):
            raise HTTPException(status_code=404, detail=f"字幕不存在: {t.path}")

    stem = Path(request.video_path).stem
    filename = request.output_name or f"{stem}.softsub.mkv"
    out_path = os.path.join(ensure_output_dir(), filename)
    tracks = [t.model_dump() for t in request.tracks]
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: mux_softsub(request.video_path, tracks, out_path))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"软字幕封装失败: {e}")
    return {"output_path": out_path, "filename": filename}


# --------------------------------------------------------------------------- #
# 语音合成（四期 4.1）
# --------------------------------------------------------------------------- #

@app.get("/api/tts/voices")
async def tts_voices(current_user: UserRecord = Depends(get_current_user)):
    """列出当前可用的 TTS 音色。"""
    try:
        engine = get_tts_engine()
        return {"engine": engine.name, "voices": engine.list_voices()}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"TTS 后端不可用: {e}")


@app.post("/api/tts/dub")
async def tts_dub(request: DubRequest, current_user: UserRecord = Depends(get_current_user)):
    """为字幕段落生成与时间轴对齐的配音音轨。"""
    try:
        engine = get_tts_engine()
        voices = engine.list_voices()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"TTS 后端不可用: {e}")

    voice = request.voice or voice_for_language(request.language, voices)
    # 目标语言是否存在匹配音色：没有就会回落到默认音色，可能根本合成不出声音
    voice_matched = True
    if not request.voice and request.language:
        voice_matched = voice is not None
    workdir = os.path.join(ensure_output_dir(), "dub_" + uuid.uuid4().hex[:8])
    segments = [s.model_dump() for s in request.segments]
    # 默认文件名带随机后缀：否则多次配音会互相覆盖同一个 dub_merged.wav
    merged_name = request.output_name or ("dub_%s.wav" % uuid.uuid4().hex[:8])

    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: synthesize_segments(
                segments, workdir, engine=engine, voice=voice,
                rate=request.rate, merged_name=merged_name,
            ),
        )
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"语音合成失败: {e}")

    # 合并音轨移到输出根目录：/api/output/{filename} 的路径参数不接受子目录，
    # 分段 wav 仍留在 workdir，只有合并结果需要能被前端直接下载。
    merged_src = result.get("merged")
    if merged_src and os.path.isfile(merged_src):
        filename = os.path.basename(merged_src)
        dst = os.path.join(ensure_output_dir(), filename)
        if os.path.abspath(merged_src) != os.path.abspath(dst):
            shutil.move(merged_src, dst)
        result["merged"] = dst
        result["filename"] = filename

    silent = int(result.get("silent_clips", 0) or 0)
    if silent or not voice_matched:
        logger.warning(
            "配音可能为静音: language=%s voice=%s voice_matched=%s silent_clips=%d",
            request.language, voice, voice_matched, silent,
        )

    return {**result, "voice": voice, "engine": engine.name, "voice_matched": voice_matched}


# --------------------------------------------------------------------------- #
# 翻译后端状态与切换
# --------------------------------------------------------------------------- #

@app.get("/api/llm/status")
async def llm_status(current_user: UserRecord = Depends(get_current_user)):
    """当前翻译模式、有效端点与各模式可用性（不返回任何密钥明文）。"""
    return llm_module.status()


@app.post("/api/llm/test")
async def llm_test(request: LlmTestRequest, current_user: UserRecord = Depends(get_current_user)):
    """对当前（或指定）模式的翻译端点做真实连通性测试，用于"确定感"与排障。"""
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, lambda: llm_module.test_endpoint(request.mode))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/llm/mode")
async def llm_set_mode(request: LlmModeRequest, current_user: UserRecord = Depends(get_current_admin)):
    """切换翻译模式（仅管理员）；可同时提交云端端点/模型/密钥，并持久化到 .env。"""
    mode = (request.mode or "").strip().lower()
    if mode not in ("local", "cloud", "hybrid"):
        raise HTTPException(status_code=400, detail="mode 必须是 local / cloud / hybrid")

    updates = {"SUBAI_LLM_MODE": mode}
    if request.cloud_url is not None:
        config.llm.cloud_url = request.cloud_url.strip()
        updates["SUBAI_LLM_CLOUD_URL"] = config.llm.cloud_url
    if request.cloud_model is not None:
        config.llm.cloud_model = request.cloud_model.strip()
        updates["SUBAI_LLM_CLOUD_MODEL"] = config.llm.cloud_model
    if request.cloud_api_key:
        config.llm.cloud_api_key = request.cloud_api_key.strip()
        updates["SUBAI_LLM_CLOUD_API_KEY"] = config.llm.cloud_api_key

    if mode in ("cloud", "hybrid"):
        url, _model, key = config.get_llm_endpoint()
        if not url:
            raise HTTPException(status_code=400, detail="云端模式需要配置云端 API 地址（cloud_url）")
        if not key:
            raise HTTPException(status_code=400, detail="云端模式需要配置 API Key（cloud_api_key）")

    config.llm.mode = mode
    try:
        persist_env(updates)
    except Exception as e:  # noqa: BLE001
        logger.warning("持久化 LLM 设置失败: %s", e)

    return llm_module.status()


# --------------------------------------------------------------------------- #
# 术语模式（强制锁定 / 软提示）
# --------------------------------------------------------------------------- #

class TermModeRequest(BaseModel):
    """术语模式切换请求"""
    mode: str


@app.get("/api/translation/settings")
async def translation_settings(current_user: UserRecord = Depends(get_current_user)):
    """翻译相关设置（当前仅术语模式）。"""
    return {
        "term_mode": config.term.mode,
        "available": [
            {
                "value": "strict",
                "label": "强制锁定",
                "description": "术语译名 100% 一致；术语作定语时句式可能略生硬",
            },
            {
                "value": "hint",
                "label": "软提示",
                "description": "把术语作为要求交给模型，语句更自然，但不保证逐字一致",
            },
        ],
    }


@app.post("/api/translation/term-mode")
async def set_term_mode(request: TermModeRequest, current_user: UserRecord = Depends(get_current_admin)):
    """切换术语模式（仅管理员），并持久化到 .env。"""
    mode = (request.mode or "").strip().lower()
    if mode not in ("strict", "hint"):
        raise HTTPException(status_code=400, detail="mode 必须是 strict / hint")

    config.term.mode = mode
    try:
        persist_env({"SUBAI_TERM_MODE": mode})
    except Exception as e:  # noqa: BLE001
        logger.warning("持久化术语模式失败: %s", e)
    return {"term_mode": config.term.mode}


# --------------------------------------------------------------------------- #
# 字幕读取与写回（在线字幕编辑）
# --------------------------------------------------------------------------- #

@app.get("/api/task/{task_id}/subtitles")
async def get_task_subtitles(task_id: str, current_user: UserRecord = Depends(get_current_user)):
    """读取任务产出的字幕（优先 JSON，其次双语 SRT，最后单语 SRT）。"""
    global task_manager
    if task_manager is None:
        raise RuntimeError("任务管理器未初始化")

    task = await task_manager.get_task(task_id, user_id=_scope_user_id(current_user))
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    data = load_task_segments(task.result_files or [])
    if not data["segments"]:
        raise HTTPException(
            status_code=404,
            detail="该任务还没有可编辑的字幕文件（可能仍在处理中，或未输出字幕）",
        )
    return {"task_id": task_id, "status": task.status, **data}


@app.post("/api/task/{task_id}/subtitles")
async def save_task_subtitles(
    task_id: str,
    request: SubtitleSaveRequest,
    current_user: UserRecord = Depends(get_current_user),
):
    """把编辑后的字幕写回原文件（JSON 或 SRT）。"""
    global task_manager
    if task_manager is None:
        raise RuntimeError("任务管理器未初始化")

    task = await task_manager.get_task(task_id, user_id=_scope_user_id(current_user))
    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    data = load_task_segments(task.result_files or [])
    if not data["file"]:
        raise HTTPException(status_code=404, detail="该任务没有可写回的字幕文件")

    segments = [s.model_dump() for s in request.segments]
    saved = save_task_segments(data["file"], data["kind"], segments)
    return {"saved": saved, "count": len(segments), "kind": data["kind"]}


# --------------------------------------------------------------------------- #
# 监控与告警（仅管理员，三期）
# --------------------------------------------------------------------------- #

@app.get("/api/admin/metrics")
async def admin_metrics(current_user: UserRecord = Depends(get_current_admin)):
    """查看当前运行时指标（JSON，含系统资源/队列/请求累计）"""
    return {
        "snapshot": _collect_snapshot(),
        "metrics": REGISTRY.snapshot(),
    }


@app.get("/api/admin/alerts")
async def admin_alerts(current_user: UserRecord = Depends(get_current_admin)):
    """查看当前活跃告警与最近告警历史"""
    if alert_manager_obj is None:
        raise RuntimeError("告警管理器未初始化")

    # 主动评估一次，返回最新状态
    alert_manager_obj.evaluate(_collect_snapshot())

    return {
        "active": [a.to_dict() for a in alert_manager_obj.active_alerts()],
        "history": [a.to_dict() for a in alert_manager_obj.recent_history(limit=50)],
    }


# --------------------------------------------------------------------------- #
# 插件系统（四期 4.3）
# --------------------------------------------------------------------------- #

def _require_plugin(plugin_id: str):
    """取插件记录，不存在则 404（避免把 KeyError 变成 500）。"""
    record = plugin_registry.get(plugin_id)
    if record is None:
        raise HTTPException(status_code=404, detail="插件不存在: %s" % plugin_id)
    return record


@app.get("/api/plugins")
async def list_plugins(kind: Optional[str] = None, detail: bool = False,
                       current_user: UserRecord = Depends(get_current_user)):
    """列出插件与状态；detail=true 时附带能力列表与可用性探测。"""
    return {
        "plugins": plugin_registry.list(kind=kind, detail=detail),
        "stats": plugin_registry.stats(),
        "kinds": list(PLUGIN_KINDS),
    }


@app.get("/api/plugins/marketplace")
async def plugin_marketplace(query: Optional[str] = None, kind: Optional[str] = None,
                             current_user: UserRecord = Depends(get_current_user)):
    """插件目录（本地索引，不联网）。"""
    return {
        "entries": plugin_registry.marketplace(query=query, kind=kind),
        "note": "目录来自本地索引；远端安装/更新尚未实现，避免假装能联网下载",
    }


@app.get("/api/plugins/{plugin_id}")
async def get_plugin(plugin_id: str, current_user: UserRecord = Depends(get_current_user)):
    """单个插件详情（含能力与可用性）。"""
    return _require_plugin(plugin_id).to_dict(detail=True)


@app.post("/api/plugins/reload")
async def reload_plugins(current_user: UserRecord = Depends(get_current_admin)):
    """重新扫描插件目录（仅管理员）。"""
    count = plugin_registry.reload()
    return {"discovered": count, "stats": plugin_registry.stats()}


@app.post("/api/plugins/{plugin_id}/enable")
async def enable_plugin(plugin_id: str, current_user: UserRecord = Depends(get_current_admin)):
    """启用插件（仅管理员）；状态持久化到 data/plugins.json。"""
    record = _require_plugin(plugin_id)
    ok = plugin_registry.set_enabled(plugin_id, True)
    if not ok and record.error:
        raise HTTPException(status_code=400, detail="插件存在错误，无法启用: %s" % record.error)
    return record.to_dict(detail=True)


@app.post("/api/plugins/{plugin_id}/disable")
async def disable_plugin(plugin_id: str, current_user: UserRecord = Depends(get_current_admin)):
    """停用插件（仅管理员）。停用即停用：对应能力会真的不可用。"""
    record = _require_plugin(plugin_id)
    plugin_registry.set_enabled(plugin_id, False)
    return record.to_dict(detail=True)


@app.post("/api/plugins/{plugin_id}/probe")
async def probe_plugin(plugin_id: str, current_user: UserRecord = Depends(get_current_admin)):
    """对插件做一次真实探测（如翻译插件的端点连通性）。"""
    record = _require_plugin(plugin_id)
    if not record.enabled or not record.loaded or record.instance is None:
        raise HTTPException(status_code=400, detail="插件未启用或未加载，无法探测")
    probe = getattr(record.instance, "probe", None)
    if not callable(probe):
        return {"plugin_id": plugin_id, "supported": False,
                "detail": "该插件不支持探测"}
    try:
        return {"plugin_id": plugin_id, "supported": True, "result": probe()}
    except Exception as e:  # noqa: BLE001
        return {"plugin_id": plugin_id, "supported": True, "error": repr(e)}


# --------------------------------------------------------------------------- #
# 启动入口
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import uvicorn

    # HTTPS 支持（三期安全加固）：启用时加载 TLS 证书
    ssl_kwargs = {}
    if config.security.enable_https and config.security.ssl_certfile:
        ssl_kwargs = {
            "ssl_certfile": config.security.ssl_certfile,
            "ssl_keyfile": config.security.ssl_keyfile or None,
        }

    uvicorn.run(
        "src.api.server:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.reload,
        **ssl_kwargs
    )