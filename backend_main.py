# -*- coding: utf-8 -*-
"""
SubAI Translator —— 后端打包入口（PyInstaller）
================================================

用 PyInstaller 打包时以本文件为入口，生成 subai-backend.exe。
打包后以编程方式启动 FastAPI，避免 uvicorn 字符串导入在 frozen 环境下的路径问题。

资源目录说明：
- models/（ASR 模型）、bin/（FFmpeg）、data/（数据库）、output/（输出）
  均位于 exe 同级目录，由 config.py 的 _project_root() 在 frozen 环境下自动定位。
"""
import uvicorn

from src.api.server import app
from src.config import config


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        reload=False,
        log_level="info",
    )
