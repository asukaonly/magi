# Magi AI Agent Framework - 后台测试指南

## 📋 目录
1. [环境准备](#环境准备)
2. [启动服务器](#启动服务器)
3. [API测试](#api测试)
4. [工具系统测试](#工具系统测试)
5. [WebSocket测试](#websocket测试)
6. [单元测试](#单元测试)

---

## 环境准备

### 1. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 2. 检查Python版本

```bash
python --version  # 需要 Python 3.10+
```

---

## 启动服务器

### 方式1: 使用启动脚本（推荐）

```bash
cd backend
python run_server.py
```

### 方式2: 直接使用uvicorn

```bash
cd backend
PYTHONPATH=/Users/asuka/code/magi/backend/src uvicorn magi.api.app:create_app --host 0.0.0.0 --port 8000 --reload
```

### 启动成功后你会看到：

```
============================================================
🚀 启动 Magi AI Agent Framework 服务器
============================================================
📡 API服务: http://localhost:8000
📚 API文档: http://localhost:8000/docs
📊 OpenAPI: http://localhost:8000/openapi.json
🔌 WebSocket: ws://localhost:8000/ws
============================================================
```

---

## API测试

### 1. 访问API文档

打开浏览器访问: **http://localhost:8000/docs**

你将看到Swagger UI界面，可以交互式测试所有API。

### 2. 使用curl测试

#### 健康检查
```bash
curl http://localhost:8000/health
```

#### 获取所有Agent
```bash
curl http://localhost:8000/api/v1/agents
```

#### 创建Agent
```bash
curl -X POST http://localhost:8000/api/v1/agents \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test_agent",
    "type": "task",
    "config": {
      "llm_adapter": "openai",
      "model": "gpt-4"
    }
  }'
```

#### 启动Agent
```bash
curl -X POST http://localhost:8000/api/v1/agents/{agent_id}/start
```

### 3. 使用Python测试

创建 `test_api.py`:

```python
import requests

BASE_URL = "http://localhost:8000/api/v1"

# 健康检查
response = requests.get(f"{BASE_URL}/health")
print(f"健康检查: {response.json()}")

# 获取所有Agent
response = requests.get(f"{BASE_URL}/agents")
print(f"Agents: {response.json()}")

# 创建Agent
agent_data = {
    "name": "test_agent",
    "type": "task",
    "config": {
        "llm_adapter": "openai",
        "model": "gpt-4"
    }
}
response = requests.post(f"{BASE_URL}/agents", json=agent_data)
agent = response.json()
print(f"创建Agent: {agent}")
```

---

## 工具系统测试

### 1. 测试基础工具功能

```bash
cd backend
PYTHONPATH=/Users/asuka/code/magi/backend/src python examples/test_tools.py
```

预期输出:
```
==================================================
✓ 所有工具测试通过!
==================================================
```

### 2. 测试高级工具功能

```bash
PYTHONPATH=/Users/asuka/code/magi/backend/src python examples/test_tool_advanced.py
```

这将测试：
- ✅ 权限控制
- ✅ 工具推荐引擎
- ✅ 执行计划器（DAG）
- ✅ 版本管理
- ✅ 循环依赖检测

### 3. 交互式工具测试

创建 `test_tool_interactive.py`:

```python
import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from magi.tools import (
    tool_registry,
    ToolRecommender,
    ExecutionPlanner,
    ToolExecutionContext,
)

async def test_interactive():
    context = ToolExecutionContext(
        agent_id="test",
        workspace=".",
        permissions=["dangerous_tools"],
    )

    # 1. 查看所有工具
    print("可用工具:")
    for tool_name in tool_registry.list_tools():
        info = tool_registry.get_tool_info(tool_name)
        print(f"  - {tool_name}: {info['description']}")

    # 2. 获取工具推荐
    recommender = ToolRecommender(tool_registry)
    recommendations = recommender.recommend_tools(
        "我需要读取文件内容",
        context
    )
    print(f"\n推荐工具: {recommendations}")

    # 3. 执行工具
    result = await tool_registry.execute(
        "bash",
        {"command": "echo 'Hello Magi!'"},
        context
    )
    print(f"\n执行结果: {result.data}")

asyncio.run(test_interactive())
```

---

## WebSocket测试

### 1. 使用Python客户端测试

创建 `test_websocket.py`:

```python
import asyncio
import websockets
import json

async def test_websocket():
    uri = "ws://localhost:8000/ws/test_client"

    async with websockets.connect(uri) as websocket:
        print("✓ WebSocket连接成功")

        # 接收消息
        while True:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                data = json.loads(message)
                print(f"收到消息: {data}")

                # 解析消息类型
                event_type = data.get("type")
                if event_type == "agent_update":
                    print(f"  Agent状态更新: {data.get('data', {})}")
                elif event_type == "task_update":
                    print(f"  任务更新: {data.get('data', {})}")
                elif event_type == "log":
                    print(f"  日志: {data.get('data', {})}")

            except asyncio.TimeoutError:
                print("等待消息...")
                continue

asyncio.run(test_websocket())
```

### 2. 使用浏览器测试

打开浏览器控制台，运行：

```javascript
// 连接WebSocket
const ws = new WebSocket('ws://localhost:8000/ws/browser_client');

ws.onopen = () => {
    console.log('✓ WebSocket连接成功');
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('收到消息:', data);
};

ws.onerror = (error) => {
    console.error('WebSocket错误:', error);
};

ws.onclose = () => {
    console.log('WebSocket连接关闭');
};
```

---

## 单元测试

### 运行所有测试

```bash
cd backend

# 工具系统测试
PYTHONPATH=/Users/asuka/code/magi/backend/src python examples/test_tools.py

# 高级功能测试
PYTHONPATH=/Users/asuka/code/magi/backend/src python examples/test_tool_advanced.py
```

### 查看测试覆盖率

```bash
pip install pytest pytest-cov
cd backend
pytest --cov=src/magi --cov-report=html
```

---

## 快速验证清单

- [ ] 服务器成功启动（访问 http://localhost:8000）
- [ ] API文档可访问（http://localhost:8000/docs）
- [ ] 基础工具测试通过
- [ ] 高级工具测试通过
- [ ] 可以通过API创建Agent
- [ ] WebSocket连接成功

---

## 常见问题

### Q: 端口8000被占用怎么办？
A: 修改 `run_server.py` 中的端口号，或使用命令行参数：
```bash
uvicorn magi.api.app:create_app --port 8001
```

### Q: 如何查看日志？
A: 服务器日志会直接输出到控制台。查看配置文件中的日志路径。

### Q: 如何停止服务器？
A: 在终端按 `Ctrl+C`

### Q: 测试时报错 "Module not found"
A: 确保设置了正确的PYTHONPATH：
```bash
export PYTHONPATH=/Users/asuka/code/magi/backend/src
```

---

## 下一步

1. ✅ 完成基础功能测试
2. 📝 编写自定义工具示例
3. 🚀 创建完整的Agent示例
4. 📊 性能测试和压力测试
5. 🐛 提交发现的Bug

需要帮助？查看文档或提Issue！
