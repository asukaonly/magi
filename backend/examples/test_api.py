"""
API应用测试

测试FastAPI应用的基本功能
"""
import sys
import os

# 添加路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from magi.api.app import app
from fastapi.testclient import TestClient


def test_api_basic():
    """测试API基本功能"""
    print("\n=== 测试API基本功能 ===")

    # 创建测试客户端
    client = TestClient(app)

    # 测试健康检查
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] == True
    print("  ✓ 健康检查端点正常")

    # 测试Swagger文档
    response = client.get("/api/docs")
    assert response.status_code == 200
    print("  ✓ Swagger文档可访问")

    # 测试OpenAPI schema
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    openapi_data = response.json()
    assert "openapi" in openapi_data
    assert "info" in openapi_data
    print("  ✓ OpenAPI schema正常")


def test_agents_api():
    """测试Agent管理API"""
    print("\n=== 测试Agent管理API ===")

    client = TestClient(app)

    # 创建Agent
    response = client.post(
        "/api/agents/",
        json={
            "name": "test-agent",
            "agent_type": "task",
            "config": {"model": "gpt-4"},
        },
    )
    assert response.status_code == 201
    agent = response.json()
    assert agent["name"] == "test-agent"
    assert agent["agent_type"] == "task"
    agent_id = agent["id"]
    print(f"  ✓ 创建Agent: {agent_id}")

    # 获取Agent列表
    response = client.get("/api/agents/")
    assert response.status_code == 200
    agents = response.json()
    assert len(agents) > 0
    print(f"  ✓ 获取Agent列表: {len(agents)} 个")

    # 获取Agent详情
    response = client.get(f"/api/agents/{agent_id}")
    assert response.status_code == 200
    agent_detail = response.json()
    assert agent_detail["id"] == agent_id
    print(f"  ✓ 获取Agent详情")

    # 启动Agent
    response = client.post(
        f"/api/agents/{agent_id}/action",
        json={"action": "start"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["success"] == True
    print(f"  ✓ 启动Agent")

    # 停止Agent
    response = client.post(
        f"/api/agents/{agent_id}/action",
        json={"action": "stop"},
    )
    assert response.status_code == 200
    print(f"  ✓ 停止Agent")

    # 删除Agent
    response = client.delete(f"/api/agents/{agent_id}")
    assert response.status_code == 204
    print(f"  ✓ 删除Agent")


def test_tasks_api():
    """测试任务管理API"""
    print("\n=== 测试任务管理API ===")

    client = TestClient(app)

    # 创建任务
    response = client.post(
        "/api/tasks/",
        json={
            "type": "web_search",
            "data": {"query": "test query"},
            "priority": "high",
        },
    )
    assert response.status_code == 201
    task = response.json()
    assert task["type"] == "web_search"
    assert task["priority"] == "high"
    task_id = task["id"]
    print(f"  ✓ 创建任务: {task_id}")

    # 获取任务列表
    response = client.get("/api/tasks/")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) > 0
    print(f"  ✓ 获取任务列表: {len(tasks)} 个")

    # 获取任务统计
    response = client.get("/api/tasks/stats/summary")
    assert response.status_code == 200
    stats = response.json()
    assert stats["success"] == True
    print(f"  ✓ 获取任务统计")


def test_tools_api():
    """测试工具管理API"""
    print("\n=== 测试工具管理API ===")

    client = TestClient(app)

    # 获取工具列表
    response = client.get("/api/tools/")
    assert response.status_code == 200
    tools = response.json()
    assert len(tools) > 0
    print(f"  ✓ 获取工具列表: {len(tools)} 个")

    # 获取工具详情
    tool_name = tools[0]["name"]
    response = client.get(f"/api/tools/{tool_name}")
    assert response.status_code == 200
    tool = response.json()
    assert tool["name"] == tool_name
    print(f"  ✓ 获取工具详情: {tool_name}")

    # 获取工具分类
    response = client.get("/api/tools/categories/list")
    assert response.status_code == 200
    categories = response.json()
    assert categories["success"] == True
    print(f"  ✓ 获取工具分类")


def test_memory_api():
    """测试记忆管理API"""
    print("\n=== 测试记忆管理API ===")

    client = TestClient(app)

    # 获取记忆列表
    response = client.get("/api/memory/")
    assert response.status_code == 200
    memories = response.json()
    assert len(memories) >= 0
    print(f"  ✓ 获取记忆列表: {len(memories)} 个")

    # 搜索记忆
    response = client.post(
        "/api/memory/search",
        json={"query": "python"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["success"] == True
    print(f"  ✓ 搜索记忆")

    # 获取记忆统计
    response = client.get("/api/memory/stats/summary")
    assert response.status_code == 200
    stats = response.json()
    assert stats["success"] == True
    print(f"  ✓ 获取记忆统计")


def test_metrics_api():
    """测试指标监控API"""
    print("\n=== 测试指标监控API ===")

    client = TestClient(app)

    # 获取系统指标
    response = client.get("/api/metrics/system")
    assert response.status_code == 200
    metrics = response.json()
    assert "cpu_percent" in metrics
    assert "memory_percent" in metrics
    print(f"  ✓ 获取系统指标: CPU={metrics['cpu_percent']}%, 内存={metrics['memory_percent']}%")

    # 获取Agent指标
    response = client.get("/api/metrics/agents")
    assert response.status_code == 200
    agents_metrics = response.json()
    assert len(agents_metrics) >= 0
    print(f"  ✓ 获取Agent指标: {len(agents_metrics)} 个")

    # 获取健康状态
    response = client.get("/api/metrics/health")
    assert response.status_code == 200
    health = response.json()
    assert health["success"] == True
    print(f"  ✓ 获取健康状态: {health['data']['status']}")


def test_error_handling():
    """测试错误处理"""
    print("\n=== 测试错误处理 ===")

    client = TestClient(app)

    # 测试404错误
    response = client.get("/api/agents/nonexistent")
    assert response.status_code == 404
    error = response.json()
    # FastAPI的HTTPException返回{"detail": "..."}格式
    assert "detail" in error
    print("  ✓ 404错误处理正常")

    # 测试400错误（启动已启动的Agent）
    # 先创建并启动Agent
    response = client.post(
        "/api/agents/",
        json={
            "name": "test-agent-2",
            "agent_type": "task",
        },
    )
    agent_id = response.json()["id"]

    response = client.post(
        f"/api/agents/{agent_id}/action",
        json={"action": "start"},
    )
    # 再次启动（应该失败）
    response = client.post(
        f"/api/agents/{agent_id}/action",
        json={"action": "start"},
    )
    assert response.status_code == 400
    print("  ✓ 400错误处理正常")


def main():
    """主测试函数"""
    print("=" * 50)
    print("API应用测试")
    print("=" * 50)

    try:
        test_api_basic()
        test_agents_api()
        test_tasks_api()
        test_tools_api()
        test_memory_api()
        test_metrics_api()
        test_error_handling()

        print("\n" + "=" * 50)
        print("✓ 所有API测试通过!")
        print("=" * 50)

    except AssertionError as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
