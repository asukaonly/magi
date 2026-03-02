#!/bin/bash
# 重启后端服务（安全版：PID文件 + 命令签名校验）

set -u

PROJECT_ROOT="/Users/asuka/code/magi"
BACKEND_DIR="$PROJECT_ROOT/backend"
PID_FILE="$BACKEND_DIR/.backend_uvicorn.pid"
APP_CMD_PATTERN="uvicorn magi.backend_app:create_backend_app"
FULL_CMD="python -m uvicorn magi.backend_app:create_backend_app --host 0.0.0.0 --port 8000 --factory --app-dir src --reload --env-file .env"
PORT=8000

is_target_process() {
    local pid="$1"
    if ! ps -p "$pid" > /dev/null 2>&1; then
        return 1
    fi
    local cmd
    cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
    [[ "$cmd" == *"$APP_CMD_PATTERN"* ]]
}

stop_backend() {
    echo "🛑 Stopping backend server..."

    local pid=""
    if [ -f "$PID_FILE" ]; then
        pid="$(cat "$PID_FILE" 2>/dev/null || true)"
        if [[ -n "$pid" ]] && is_target_process "$pid"; then
            echo "Stopping PID from file: $pid"
            kill -TERM "$pid" 2>/dev/null || true
            for _ in {1..20}; do
                if ! ps -p "$pid" > /dev/null 2>&1; then
                    break
                fi
                sleep 0.2
            done
            if ps -p "$pid" > /dev/null 2>&1; then
                echo "Process still running, force kill PID: $pid"
                kill -KILL "$pid" 2>/dev/null || true
            fi
        fi
        rm -f "$PID_FILE"
    fi

    # 兜底：只清理命令签名匹配的进程，不按端口误杀
    local fallback_pids
    fallback_pids="$(pgrep -f "$APP_CMD_PATTERN" 2>/dev/null || true)"
    if [[ -n "$fallback_pids" ]]; then
        echo "Stopping matched backend processes: $fallback_pids"
        while IFS= read -r fp; do
            [[ -z "$fp" ]] && continue
            kill -TERM "$fp" 2>/dev/null || true
        done <<< "$fallback_pids"
        sleep 1
    fi

    # 兜底：清理仍占用后端端口的监听进程（例如 uvicorn reload 子进程）
    local port_pids
    port_pids="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "$port_pids" ]]; then
        echo "Stopping processes on port ${PORT}: $port_pids"
        while IFS= read -r pp; do
            [[ -z "$pp" ]] && continue
            kill -TERM "$pp" 2>/dev/null || true
        done <<< "$port_pids"
        sleep 1

        local remain_port_pids
        remain_port_pids="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)"
        if [[ -n "$remain_port_pids" ]]; then
            echo "Force killing remaining port ${PORT} processes: $remain_port_pids"
            while IFS= read -r rpp; do
                [[ -z "$rpp" ]] && continue
                kill -KILL "$rpp" 2>/dev/null || true
            done <<< "$remain_port_pids"
        fi
    fi
}

start_backend() {
    echo "🚀 Starting backend server..."
    cd "$BACKEND_DIR"

    # 显式加载 backend/.env，避免依赖 python-dotenv 是否可用
    if [ -f ".env" ]; then
        set -a
        source ".env"
        set +a
    fi

    nohup $FULL_CMD > logs/backend.log 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$PID_FILE"

    sleep 2

    if is_target_process "$new_pid"; then
        echo "✅ Backend server started (PID: $new_pid)"
        echo "📝 Logs: tail -f backend/logs/backend.log"
        echo "🔗 API: http://localhost:8000"
    else
        echo "❌ Failed to start backend server"
        echo "📝 Check logs: cat backend/logs/backend.log"
        exit 1
    fi
}

stop_backend
start_backend
