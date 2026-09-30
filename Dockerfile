# syntax=docker/dockerfile:1
# =============================================================================
# SubAI Translator —— 后端生产镜像（三期：容器化部署）
# =============================================================================
# 默认构建 CPU 推理镜像（体积 ≤ 2GB）。
# GPU 加速镜像见文末注释（需 NVIDIA CUDA 基础镜像 + nvidia-* 运行库；不需要 torch）。
#
# 构建：
#   docker build -t subai-backend:latest .
# 运行：
#   docker run -p 8000:8000 -v ./models:/app/models -v ./data:/app/data subai-backend:latest
#
# 说明：
#   - ASR 模型（faster-whisper-small）体积大，不打包进镜像，运行时挂载到 /app/models；
#   - FFmpeg 通过 apt 安装，config.py 会自动回退到系统 PATH；
#   - 数据（SQLite）与输出文件持久化到 /app/data、/app/output。
# =============================================================================

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim AS runtime

# ---------------------------------------------------------------------------
# 系统依赖
#   ffmpeg           视频抽帧 / 字幕烧录 / 转封装
#   libgl1           以下两项是 opencv-python（硬字幕识别）在无头环境的运行时依赖。
#   libglib2.0-0     启动期并不会 import cv2（延迟到硬字幕任务执行时），
#                    因此缺库时镜像仍能启动，但硬字幕任务会失败。
# ---------------------------------------------------------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libgl1 \
        libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# 创建非 root 用户，降低容器逃逸风险
# 固定 UID/GID=1000：宿主机挂载目录只需 chown 1000:1000 即可被容器内用户写入。
# （用 --system 会自动分配低位 UID，属主对不上会导致挂载卷写入失败。）
# ---------------------------------------------------------------------------
RUN groupadd --gid 1000 subai && \
    useradd --uid 1000 --gid 1000 --create-home subai

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

# ---------------------------------------------------------------------------
# 先装依赖，充分利用层缓存（requirements.txt 变更才重建此层）
# ---------------------------------------------------------------------------
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# 复制源码与入口
# ---------------------------------------------------------------------------
COPY src ./src
COPY backend_main.py ./
COPY pytest.ini ./

# ---------------------------------------------------------------------------
# 运行时目录（data / models / output 建议由编排层挂载持久卷）
# ---------------------------------------------------------------------------
RUN mkdir -p /app/data /app/models /app/output && \
    chown -R subai:subai /app

USER subai

EXPOSE 8000

# 健康检查：依赖 /api/health（无需认证）
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["python", "-m", "uvicorn", "src.api.server:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# （可选）GPU 加速镜像：取消下方注释并替换基础镜像
#   FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04
#   安装 python3.12 + ffmpeg，pip 安装 nvidia-cublas-cu12 / nvidia-cudnn-cu12 后再装 faster-whisper。
# ---------------------------------------------------------------------------
