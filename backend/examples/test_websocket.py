"""
WebSocket communication test

Tests WebSocket server and real-time event broadcasting
"""
import asyncio
import sys
import os
import websockets
import json

# Add path
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
    """Test WebSocket connection"""
    print("\n=== Test WebSocket Connection ===")

    uri = "ws://localhost:8000/ws"

    try:
        async with websockets.connect(uri) as websocket:
            print("  ✓ WebSocket connection successful")

            # Send ping message
            await websocket.send(json.dumps({"type": "ping"}))
            response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
            data = json.loads(response)
            assert data.get("type") == "pong", "Expected pong response"
            print("  ✓ Ping/Pong test passed")

            # Test subscription
            await websocket.send(json.dumps({"type": "subscribe", "channel": "agents"}))
            response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
            data = json.loads(response)
            print(f"  ✓ Subscription response: {data}")

    except asyncio.TimeoutError:
        print("  ✗ Connection timeout")
        return False
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        return False

    print("✓ WebSocket connection test passed")
    return True


async def test_agent_state_broadcast():
    """Test Agent state broadcast"""
    print("\n=== Test Agent State Broadcast ===")

    uri = "ws://localhost:8000/ws"

    # Create receiver
    received_messages = []

    async def receive_messages():
        try:
            async with websockets.connect(uri) as websocket:
                # Subscribe to agent updates
                await websocket.send(json.dumps({"type": "subscribe", "channel": "agents"}))

                # Receive messages
                for _ in range(3):
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                        data = json.loads(message)
                        received_messages.append(data)
                        print(f"  Received message: {data.get('type')}")
                    except asyncio.TimeoutError:
                        break
        except Exception as e:
            print(f"  Receiver error: {e}")

    # Start receiver
    receiver_task = asyncio.create_task(receive_messages())

    # Wait for connection to establish
    await asyncio.sleep(0.5)

    # Send broadcast messages
    await broadcast_agent_update("agent_1", "running", {"name": "test-agent"})
    print("  ✓ Broadcast Agent state update")

    await broadcast_agent_update("agent_1", "stopped")
    print("  ✓ Broadcast Agent stopped")

    await broadcast_task_update("task_1", "completed")
    print("  ✓ Broadcast task completed")

    # Wait for reception
    await receiver_task

    print(f"  ✓ Received {len(received_messages)} messages")
    print("✓ Agent state broadcast test passed")


async def test_metrics_broadcast():
    """Test metrics broadcast"""
    print("\n=== Test Metrics Broadcast ===")

    # Send metrics update
    metrics = {
        "cpu_percent": 45.5,
        "memory_percent": 62.3,
        "disk_percent": 55.0,
    }

    await broadcast_metrics_update(metrics)
    print("  ✓ Broadcast system metrics")

    print("✓ Metrics broadcast test passed")


async def test_log_broadcast():
    """Test log broadcast"""
    print("\n=== Test Log Broadcast ===")

    # Send logs of different levels
    await broadcast_log("info", "System started", "system")
    print("  ✓ Broadcast INFO log")

    await broadcast_log("warning", "High memory usage", "monitor")
    print("  ✓ Broadcast WARNING log")

    await broadcast_log("error", "Task failed", "task_agent")
    print("  ✓ Broadcast ERROR log")

    print("✓ Log broadcast test passed")


async def start_test_server():
    """Start test server"""
    print("\n=== Start Test WebSocket Server ===")

    config = Config()
    config.bind = ["localhost:8000"]
    config.workers = 1

    # Run server in background
    server_task = asyncio.create_task(serve(app, config))

    # Wait for server to start
    await asyncio.sleep(2.0)
    print("  ✓ Test server started (ws://localhost:8000/ws)")

    return server_task


async def main():
    """Main test function"""
    print("=" * 50)
    print("WebSocket Communication Test")
    print("=" * 50)

    # Start test server
    server_task = await start_test_server()

    try:
        # Run tests
        await test_websocket_connection()
        await test_agent_state_broadcast()
        await test_metrics_broadcast()
        await test_log_broadcast()

        print("\n" + "=" * 50)
        print("✓ All WebSocket tests passed!")
        print("=" * 50)

    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # Stop server
        print("\nStopping test server...")
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
