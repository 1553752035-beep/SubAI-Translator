# -*- coding: utf-8 -*-
"""
SubAI Translator 启动脚本（二期）
=================================

用法：
    python tools/start_server.py          # 启动API服务
    python tools/start_server.py --reload  # 开发模式（自动重载）
    python tools/start_server.py --port 9000  # 指定端口
"""
import argparse
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import config
from src.api.server import app
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="启动SubAI Translator API服务")
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help=f"监听地址（默认: {config.server.host}）"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=f"监听端口（默认: {config.server.port}）"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="开发模式（自动重载）"
    )
    
    args = parser.parse_args()
    
    # 覆盖配置
    host = args.host or config.server.host
    port = args.port or config.server.port
    reload = args.reload or config.server.reload
    
    print(f"启动SubAI Translator API服务...")
    print(f"  地址: http://{host}:{port}")
    print(f"  模式: {config.llm.mode}")
    print(f"  ASR设备: {config.asr.device}")
    print(f"  最大并发: {config.get_max_concurrent()}")
    print(f"  重载: {reload}")
    print()
    
    ssl_kwargs = {}
    if config.security.enable_https and config.security.ssl_certfile:
        ssl_kwargs = {
            "ssl_certfile": config.security.ssl_certfile,
            "ssl_keyfile": config.security.ssl_keyfile or None,
        }
        print(f"  HTTPS: 已启用 ({config.security.ssl_certfile})")

    uvicorn.run(
        "src.api.server:app",
        host=host,
        port=port,
        reload=reload,
        **ssl_kwargs
    )


if __name__ == "__main__":
    main()