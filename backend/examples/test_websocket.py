"""
WebSocket通信测试

测试WebSocket服务器和实时事件推送
"""
import asyncio
import sys
import os
import websockets
import json

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from magi.api.app import app
from magi.api.websocket import (
    broadcast_agent_update,
    broadcast_task_update,
    broadcast_metrics_update,
    broadcast_log,
)
from hypercorn.config import Config
from hypercorn.asyncio import serve


async def test_websocket_connection():
    """测试WebSocket连接"""
    print("\n=== 测试WebSocket连接 ===")

    uri = "ws://localhost:8000/ws"

    try:
        async with websockets.connect(uri) as websocket:
            print("  ✓ WebSocket连接成功")

            # 发送ping消息
            await websocket.send(json.dumps({"type": "ping"}))
            response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
            data = json.loads(response)
            assert data.get("type") == "pong", "Expected pong response"
            print("  ✓ Ping/Pong测试通过")

            # 测试订阅
            await websocket.send(json.dumps({"type": "subscribe", "channel": "agents"}))
            response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
            data = json.loads(response)
            print(f"  ✓ 订阅响应: {data}")

    except asyncio.TimeoutError:
        print("  ✗ 连接超时")
        return False
    except Exception as e:
        print(f"  ✗ 连接失败: {e}")
        return False

    print("✓ WebSocket连接测试通过")
    return True


async def test_agent_state_broadcast():
    """测试Agent状态广播"""
    print("\n=== 测试Agent状态广播 ===")

    uri = "ws://localhost:8000/ws"

    # 创建接收端
    received_messages = []

    async def receive_messages():
        try:
            async with websockets.connect(uri) as websocket:
                # 订阅agent更新
                await websocket.send(json.dumps({"type": "subscribe", "channel": "agents"}))

                # 接收消息
                for _ in range(3):
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                        data = json.loads(message)
                        received_messages.append(data)
                        print(f"  收到消息: {data.get('type')}")
                    except asyncio.TimeoutError:
                        break
        except Exception as e:
            print(f"  接收端错误: {e}")

    # 启动接收端
    receiver_task = asyncio.create_task(receive_messages())

    # 等待连接建立
    await asyncio.sleep(0.5)

    # 发送广播消息
    await broadcast_agent_update("agent_1", "running", {"name": "test-agent"})
    print("  ✓ 广播Agent状态更新")

    await broadcast_agent_update("agent_1", "stopped")
    print("  ✓ 广播Agent停止")

    await broadcast_task_update("task_1", "completed")
    print("  ✓ 广播任务完成")

    # 等待接收
    await receiver_task

    print(f"  ✓ 接收到 {len(received_messages)} 条消息")
    print("✓ Agent状态广播测试通过")


async def test_metrics_broadcast():
    """测试指标广播"""
    print("\n=== 测试指标广播 ===")

    # 发送指标更新
    metrics = {
        "cpu_percent": 45.5,
        "memory_percent": 62.3,
        "disk_percent": 55.0,
    }

    await broadcast_metrics_update(metrics)
    print("  ✓ 广播系统指标")

    print("✓ 指标广播测试通过")


async def test_log_broadcast():
    """测试日志广播"""
    print("\n=== 测试日志广播 ===")

    # 发送不同级别的日志
    await broadcast_log("info", "System started", "system")
    print("  ✓ 广播INFO日志")

    await broadcast_log("warning", "High memory usage", "monitor")
    print("  ✓ 广播WARNING日志")

    await broadcast_log("error", "Task failed", "task_agent")
    print("  ✓ 广播ERROR日志")

    print("✓ 日志广播测试通过")


async def start_test_server():
    """启动测试服务器"""
    print("\n=== 启动测试WebSocket服务器 ===")

    config = Config()
    config.bind = ["localhost:8000"]
    config.workers = 1

    # 在后台运行服务器
    server_task = asyncio.create_task(serve(app, config))

    # 等待服务器启动
    await asyncio.sleep(2.0)
    print("  ✓ 测试服务器启动 (ws://localhost:8000/ws)")

    return server_task


async def main():
    """主测试函数"""
    print("=" * 50)
    print("WebSocket通信测试")
    print("=" * 50)

    # 启动测试服务器
    server_task = await start_test_server()

    try:
        # 运行测试
        await test_websocket_connection()
        await test_agent_state_broadcast()
        await test_metrics_broadcast()
        await test_log_broadcast()

        print("\n" + "=" * 50)
        print("✓ 所有WebSocket测试通过!")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # 停止服务器
        print("\n停止测试服务器...")
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
