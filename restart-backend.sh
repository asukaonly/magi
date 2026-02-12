#!/bin/bash
# 重启后端服务

echo "🛑 Stopping backend server..."

# 查找并杀死 uvicorn 进程
PIDS=$(lsof -ti:8000 2>/dev/null)
if [ -n "$PIDS" ]; then
    echo "Killing processes on port 8000: $PIDS"
    kill -9 $PIDS 2>/dev/null
fi

# 也尝试用 pkill
pkill -9 -f "uvicorn src.magi.api.app" 2>/dev/null

sleep 2

echo "🚀 Starting backend server..."
cd /Users/asuka/code/magi/backend
nohup python -m uvicorn src.magi.api.app:app --host 0.0.0.0 --port 8000 --reload > logs/backend.log 2>&1 &

sleep 2

if lsof -ti:8000 > /dev/null 2>&1; then
    echo "✅ Backend server started"
    echo "📝 Logs: tail -f backend/logs/backend.log"
    echo "🔗 API: http://localhost:8000"
else
    echo "❌ Failed to start backend server"
    echo "📝 Check logs: cat backend/logs/backend.log"
fi
