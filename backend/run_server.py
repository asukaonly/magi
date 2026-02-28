#!/usr/bin/env python3
"""
Magi AI Agent Framework - 服务器启动脚本

启动FastAPI服务器和WebSocket服务
"""
import sys
import os

# 加载.env文件
from dotenv import load_dotenv
load_dotenv()

# 添加src目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import uvicorn
from magi.backend_app import create_backend_app

# 创建FastAPI应用
app = create_backend_app()

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 启动 Magi AI Agent Framework 服务器")
    print("=" * 60)
    print(f"📡 API服务: http://localhost:8000")
    print(f"📚 API文档: http://localhost:8000/docs")
    print(f"📊 OpenAPI: http://localhost:8000/openapi.json")
    print(f"🔌 WebSocket: ws://localhost:8000/ws")
    print("=" * 60)
    print("按 Ctrl+C 停止服务器")
    print("=" * 60)

    uvicorn.run(
        "magi.backend_app:create_backend_app",  # 使用导入字符串以支持reload
        host="0.0.0.0",
        port=8000,
        reload=True,  # 开发模式，自动重载
        log_level="info",
        factory=True  # app是工厂函数
    )
