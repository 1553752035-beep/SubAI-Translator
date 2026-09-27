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
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.config import config, reload_config
from src.db.tasks import TaskManager, TaskRecord, get_task_manager
from src.cache.translation_cache import TranslationCache, get_translation_cache
from src.queue.task_queue import TaskQueue, get_task_queue
from src.logging_config import setup_logging

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


# --------------------------------------------------------------------------- #
# 全局资源
# --------------------------------------------------------------------------- #

task_manager: Optional[TaskManager] = None
task_queue_obj: Optional[TaskQueue] = None
translation_cache_obj: Optional[TranslationCache] = None


# --------------------------------------------------------------------------- #
# 生命周期管理
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 初始化统一日志（级别受 SUBAI_LOG_LEVEL 环境变量控制）
    setup_logging()

    # 启动时初始化
    logger.info("正在启动SubAI Translator API服务...")
    
    global task_manager, task_queue_obj, translation_cache_obj

    # 初始化任务管理器
    task_manager = await get_task_manager()
    logger.info("任务管理器已初始化")

    # 初始化翻译缓存
    translation_cache_obj = await get_translation_cache()
    logger.info("翻译缓存已初始化")

    # 初始化术语库（API 端点用裸 sqlite3，需要先建表）
    from src.db.terminology import TerminologyManager
    TerminologyManager(config.terminology_db)  # 触发 _ensure_db 建表
    logger.info("术语库表已就绪")

    # 初始化任务队列
    max_concurrent = config.get_max_concurrent()
    task_queue_obj = await get_task_queue(task_manager, max_concurrent)
    logger.info(f"任务队列已初始化，最大并发={max_concurrent}")
    
    logger.info("API服务启动完成")
    
    yield
    
    # 关闭时清理
    logger.info("正在关闭API服务...")
    if task_queue_obj:
        await task_queue_obj.shutdown()
    if task_manager:
        await task_manager.close()
    if translation_cache_obj:
        await translation_cache_obj.close()
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
                progress_callback=_thread_safe_progress_cb
            )
        )
        
        # 更新任务状态为completed
        await task_manager.update_task(
            task_id=task_id,
            status="completed",
            progress=1.0,
            message="任务完成",
            result_files=result if isinstance(result, list) else []
        )
        
        logger.info(f"任务 {task_id} 处理完成，输出文件数: {len(result) if isinstance(result, list) else 0}")
        
    except Exception as e:
        # 更新任务状态为failed
        await task_manager.update_task(
            task_id=task_id,
            status="failed",
            error_message=str(e)
        )
        logger.error(f"任务 {task_id} 处理失败: {e}", exc_info=True)
        raise
    finally:
        # 清空全局task_id
        progress_callback_task_id = ""


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


@app.post("/api/upload")
async def upload_video_file(file: UploadFile):
    """
    上传视频文件（multipart/form-data）

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

    total = 0
    try:
        with open(dest, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)  # 1MB 分块写入
                if not chunk:
                    break
                f.write(chunk)
                total += len(chunk)
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


@app.post("/api/transcode")
async def transcode(request: TranscodeRequest, background_tasks: BackgroundTasks):
    """
    提交转码任务
    
    请求体：
    - video_path: 视频文件路径
    - mode: 识别模式（asr/hardsub）
    - source_lang: 源语言（可选）
    - target_lang: 目标语言（默认en）
    - output_format: 输出格式（srt/vtt/ass/json）
    - terms_file: 术语库文件（可选）
    - priority: 优先级（high/medium/low）
    
    返回：
    - task_id: 任务ID
    - status: 任务状态
    """
    global task_manager, task_queue_obj
    
    if task_manager is None or task_queue_obj is None:
        raise RuntimeError("服务未初始化")
    
    # 验证视频文件
    if not os.path.exists(request.video_path):
        raise HTTPException(status_code=404, detail=f"视频文件不存在: {request.video_path}")
    
    # 生成任务ID
    task_id = str(uuid.uuid4())[:8]
    video_filename = get_video_filename(request.video_path)
    task_id = f"{task_id}_{clean_task_id(video_filename)}"
    
    # 创建任务记录
    task = await task_manager.create_task(
        task_id=task_id,
        video_path=request.video_path,
        mode=request.mode,
        source_lang=request.source_lang,
        target_lang=request.target_lang,
        output_format=request.output_format,
        terms_file=request.terms_file
    )
    
    # 提交到任务队列
    success = await task_queue_obj.submit(
        task_id=task_id,
        callback=process_transcode_task,
        priority=request.priority,
        video_path=request.video_path,
        mode=request.mode,
        source_lang=request.source_lang,
        target_lang=request.target_lang,
        output_format=request.output_format,
        terms_file=request.terms_file
    )
    
    if not success:
        await task_manager.update_task(
            task_id=task_id,
            status="failed",
            message="任务队列已满"
        )
        raise HTTPException(status_code=503, detail="任务队列已满，请稍后重试")
    
    return {
        "task_id": task_id,
        "status": task.status,
        "message": "任务已提交到队列"
    }


@app.get("/api/task/{task_id}")
async def get_task(task_id: str):
    """查询任务状态"""
    global task_manager

    if task_manager is None:
        raise RuntimeError("任务管理器未初始化")

    task = await task_manager.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail=f"任务不存在: {task_id}")

    return TaskStatusResponse(**task.to_dict())


@app.delete("/api/task/{task_id}")
async def delete_task(task_id: str):
    """
    取消/删除任务

    - 正在排队的任务：直接从队列移除并标记 cancelled
    - 处理中的任务：标记 cancelled（实际停止依赖 pipeline 协作检查）
    - 已完成任务：仅做软删除（标记 archived）

    注意：长任务真正的硬中止需要 pipeline 协做支持——这里先做软取消，
    状态字段直接置为 cancelled（前端按失败处理）。
    """
    global task_manager, task_queue_obj

    if task_manager is None:
        raise RuntimeError("任务管理器未初始化")

    task = await task_manager.get_task(task_id)
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

    # 进行中或排队：标记 cancelled
    await task_manager.update_task(
        task_id=task_id,
        status="cancelled",
        message="用户已取消",
        error_message="cancelled by user"
    )
    return {"task_id": task_id, "message": "已标记取消（pipeline 协做后真正中止）"}


@app.get("/api/output/{filename}")
async def get_output_file(filename: str):
    """
    下载输出文件
    
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
    offset: int = 0
):
    """
    查询历史记录
    
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
    limit: int = 100
):
    """
    查询术语列表
    
    参数：
    - category: 按分类过滤（可选）
    - priority: 按优先级过滤（可选）
    - keyword: 关键词搜索（可选）
    - limit: 返回数量限制
    """
    import sqlite3
    
    conn = sqlite3.connect(config.terminology_db)
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM terminology WHERE 1=1"
    params = []

    if category:
        query += " AND category = ?"
        params.append(category)

    if priority:
        query += " AND priority = ?"
        params.append(priority)

    if keyword:
        # 注：术语库表 schema 用列名 `source`（由 TerminologyManager._ensure_db 建立）
        query += " AND (source LIKE ? OR translation LIKE ?)"
        params.extend([f"%{keyword}%", f"%{keyword}%"])

    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    
    cursor = conn.execute(query, params)
    terms = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return {"terms": terms, "total": len(terms)}


@app.post("/api/terminology")
async def add_term(request: dict):
    """
    添加术语
    
    请求体：
    - source_text: 源文本
    - translation: 译文
    - priority: 优先级（high/medium/low，默认medium）
    - category: 分类（可选）
    """
    import sqlite3
    
    source_text = request.get("source_text", "").strip()
    translation = request.get("translation", "").strip()
    priority = request.get("priority", "medium")
    category = request.get("category", "")
    
    if not source_text or not translation:
        raise HTTPException(status_code=400, detail="source_text和translation不能为空")
    
    conn = sqlite3.connect(config.terminology_db)
    now = datetime.now().isoformat()
    cursor = conn.execute(
        """INSERT INTO terminology (source, translation, priority, category, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (source_text, translation, priority, category, now, now)
    )
    conn.commit()
    conn.close()

    return {
        "message": "术语已添加",
        "term_id": cursor.lastrowid
    }


@app.post("/api/terminology/import")
async def import_terms(file: UploadFile):
    """
    导入术语（JSON格式）
    
    支持格式：
    [
        {"source_text": "Hello", "translation": "你好", "priority": "high"},
        ...
    ]
    """
    import sqlite3
    
    content = await file.read()
    terms = json.loads(content)
    
    if not isinstance(terms, list):
        raise HTTPException(status_code=400, detail="术语必须是JSON数组")
    
    conn = sqlite3.connect(config.terminology_db)
    now = datetime.now().isoformat()
    inserted = 0
    
    for term in terms:
        try:
            source_text = term.get("source_text", "").strip()
            translation = term.get("translation", "").strip()
            priority = term.get("priority", "medium")
            category = term.get("category", "")
            
            if source_text and translation:
                conn.execute(
                    """INSERT OR IGNORE INTO terminology (source, translation, priority, category, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (source_text, translation, priority, category, now, now)
                )
                inserted += 1
        except Exception as e:
            logger.warning(f"导入术语失败: {e}")
    
    conn.commit()
    conn.close()
    
    return {"message": f"成功导入 {inserted} 个术语"}


@app.get("/api/cache/stats")
async def cache_stats():
    """查询缓存统计"""
    global translation_cache_obj
    
    if translation_cache_obj is None:
        raise RuntimeError("翻译缓存未初始化")
    
    stats = await translation_cache_obj.get_stats()
    return stats


@app.post("/api/cache/clear")
async def cache_clear():
    """清空缓存"""
    global translation_cache_obj
    
    if translation_cache_obj is None:
        raise RuntimeError("翻译缓存未初始化")
    
    count = await translation_cache_obj.clear()
    return {"message": f"已清空 {count} 条缓存"}


@app.get("/api/queue/stats")
async def queue_stats():
    """查询队列统计"""
    global task_queue_obj
    
    if task_queue_obj is None:
        raise RuntimeError("任务队列未初始化")
    
    return await task_queue_obj.get_stats()


@app.post("/api/config/reload")
async def config_reload():
    """重载配置"""
    global config
    
    reload_config()
    return {"message": "配置已重载", "config": {
        "llm_mode": config.llm.mode,
        "asr_device": config.asr.device,
        "max_concurrent": config.get_max_concurrent()
    }}


# --------------------------------------------------------------------------- #
# 启动入口
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "src.api.server:app",
        host=config.server.host,
        port=config.server.port,
        reload=config.server.reload
    )