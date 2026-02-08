# Magi AI Agent Framework - 开发规范

## 📋 项目概述

Magi是一个本地可部署的AI Agent框架，具备自感知、自处理和自循环能力。

### 核心特性

- **自感知模块**：感知外部世界（用户消息、传感器数据、系统事件）
- **自处理模块**：处理感知输入，积累能力，从失败中学习
- **Agent循环**：Sense-Plan-Act-Reflect四阶段循环
- **三层Agent架构**：MasterAgent → TaskAgent → WorkerAgent
- **插件系统**：可扩展的插件/Skills机制
- **工具注册表**：统一的工具管理和执行
- **记忆存储**：5层架构（L1-L5）

## 📁 目录结构

```
magi/
├── backend/                          # Python后端
│   ├── configs/                      # 配置文件
│   │   └── agent.yaml                # Agent配置示例
│   ├── data/                         # 数据目录（运行时生成）
│   │   ├── chromadb/                 # 向量数据库
│   │   ├── events/                   # 事件存储
│   │   └── memories/                 # 记忆存储
│   ├── examples/                     # 示例代码
│   │   ├── test_basic.py             # 基础测试
│   │   ├── test_memory.py            # 记忆测试
│   │   ├── test_complete_framework.py # 完整框架测试
│   │   ├── test_worker_agent.py      # WorkerAgent测试
│   │   └── demo.py                   # 框架演示
│   ├── src/
│   │   ├── magi/                     # 主模块
│   │   │   ├── awareness/            # 自感知模块
│   │   │   │   ├── base.py           # 核心数据结构
│   │   │   │   ├── manager.py        # 感知管理器
│   │   │   │   ├── sensors.py        # 内置传感器
│   │   │   │   └── __init__.py
│   │   │   ├── processing/           # 自处理模块
│   │   │   │   ├── base.py           # 核心数据结构
│   │   │   │   ├── module.py         # 自处理模块
│   │   │   │   ├── complexity.py     # 复杂度评估
│   │   │   │   ├── capability.py     # 能力提取/验证
│   │   │   │   ├── failure_learning.py # 失败学习
│   │   │   │   ├── human_in_loop.py  # 人机协作
│   │   │   │   ├── learning.py       # 渐进式学习
│   │   │   │   ├── context.py        # 上下文感知
│   │   │   │   ├── experience_replay.py # 经验回放
│   │   │   │   └── __init__.py
│   │   │   ├── core/                 # Agent核心
│   │   │   │   ├── agent.py          # Agent基类
│   │   │   │   ├── master_agent.py   # Master Agent
│   │   │   │   ├── task_agent.py     # Task Agent
│   │   │   │   ├── worker_agent.py   # Worker Agent
│   │   │   │   ├── loop.py           # 循环引擎
│   │   │   │   ├── task_database.py  # 任务数据库
│   │   │   │   ├── monitoring.py     # 系统监控
│   │   │   │   ├── timeout.py        # 超时计算
│   │   │   │   └── __init__.py
│   │   │   ├── events/               # 事件系统
│   │   │   │   ├── events.py         # 事件定义
│   │   │   │   ├── backend.py        # 后端接口
│   │   │   │   ├── memory_backend.py # 内存后端
│   │   │   │   ├── sqlite_backend.py # SQLite后端
│   │   │   │   └── __init__.py
│   │   │   ├── llm/                  # LLM适配器
│   │   │   │   ├── base.py           # LLM接口
│   │   │   │   ├── openai.py         # OpenAI适配器
│   │   │   │   ├── anthropic.py      # Anthropic适配器
│   │   │   │   └── __init__.py
│   │   │   ├── memory/               # 记忆存储
│   │   │   │   ├── store.py          # 统一接口
│   │   │   │   ├── self_memory.py    # L1: 自我记忆
│   │   │   │   ├── other_memory.py   # L2: 他人记忆
│   │   │   │   ├── raw_event_store.py # L1: 原始事件
│   │   │   │   └── capability_store.py # L5: 能力记忆
│   │   │   ├── plugins/              # 插件系统
│   │   │   │   ├── base.py           # 插件基类
│   │   │   │   ├── manager.py        # 插件管理器
│   │   │   │   └── __init__.py
│   │   │   ├── tools/                # 工具系统
│   │   │   │   ├── base.py           # Tool基类
│   │   │   │   ├── registry.py       # 工具注册表
│   │   │   │   └── __init__.py
│   │   │   ├── config/               # 配置管理
│   │   │   │   └── settings.py       # 配置加载
│   │   │   └── __init__.py
│   │   ├── tests/                    # 测试代码
│   │   │   ├── unit/                 # 单元测试
│   │   │   ├── integration/          # 集成测试
│   │   │   └── fixtures/             # 测试固件
│   │   └── api/                      # API层（待实现）
│   ├── pyproject.toml                # Python项目配置
│   ├── requirements.txt              # Python依赖
│   └── README.md                     # 后端README
│
├── frontend/                         # TypeScript前端（待实现）
│   ├── public/                       # 静态资源
│   ├── src/
│   │   ├── api/                      # API客户端
│   │   ├── components/               # React组件
│   │   ├── hooks/                    # 自定义Hooks
│   │   ├── pages/                    # 页面
│   │   ├── stores/                   # 状态管理
│   │   ├── types/                    # TypeScript类型
│   │   └── utils/                    # 工具函数
│   ├── package.json                  # Node.js配置
│   ├── vite.config.ts                # Vite配置
│   └── tsconfig.json                 # TypeScript配置
│
├── openspec/                         # OpenSpec规范
│   ├── changes/                      # 变更记录
│   │   ├── ai-agent-framework/       # AI框架变更
│   │   └── archive/                  # 已归档变更
│   └── specs/                        # 主规范
│
├── .gitignore                        # Git忽略文件
├── agents.md                         # 本文档
└── README.md                         # 项目README
```

## 📝 代码规范

### Python代码规范

#### 1. 命名规范

- **类名**：`PascalCase`（如`PerceptionManager`）
- **函数/方法**：`snake_case`（如`get_agent_profile`）
- **变量**：`snake_case`（如`max_retries`）
- **常量**：`UPPER_SNAKE_CASE`（如`MAX_QUEUE_SIZE`）
- **私有成员**：`_leading_underscore`（如`_queue`）
- **受保护成员**：`_leading_underscore`（如``_on_start`）

#### 2. 文件组织

每个模块应包含：
1. **模块文档字符串**：描述模块用途
2. **导入**：标准库 → 第三方库 → 本地模块
3. **类/函数定义**：按逻辑顺序组织
4. **`__init__.py`**：导出公共接口

```python
"""
模块文档字符串

简要描述模块功能和职责
"""
import asyncio
from typing import Dict, Any

from .base import BaseClass


class MyClass(BaseClass):
    """类文档字符串"""

    def __init__(self, config: Dict[str, Any]):
        """初始化方法"""
        self.config = config

    async def process(self) -> Any:
        """处理方法"""
        pass
```

#### 3. 类型注解

- 所有公共方法必须添加类型注解
- 使用`typing`模块的类型
- 复杂类型使用`TypeAlias`定义

```python
from typing import Dict, List, Optional, Any

async def execute_task(
    self,
    task_id: str,
    parameters: Dict[str, Any],
    timeout: Optional[float] = None,
) -> Dict[str, Any]:
    """执行任务"""
    pass
```

#### 4. 异步编程规范

- **所有I/O操作必须使用async/await**
- **使用`asyncio.sleep()`代替`time.sleep()`**
- **数据库操作使用异步库（aiosqlite）**
- **正确处理异常和超时**

```python
import asyncio

async def fetch_data(self) -> Dict:
    """异步获取数据"""
    try:
        async with asyncio.timeout(5.0):
            result = await self.api_call()
            return result
    except asyncio.TimeoutError:
        raise
```

#### 5. 文档字符串

使用Google风格的文档字符串：

```python
def calculate_timeout(
    self,
    task_type: TaskType,
    priority: TaskPriority,
) -> float:
    """
    计算任务超时时间

    Args:
        task_type: 任务类型
        priority: 任务优先级

    Returns:
        超时时间（秒）

    Raises:
        ValueError: 如果参数无效

    Example:
        >>> calculator = TimeoutCalculator()
        >>> timeout = calculator.calculate_timeout(TaskType.SIMPLE, TaskPriority.NORMAL)
    """
```

#### 6. 错误处理

- **使用具体的异常类型**
- **提供有用的错误信息**
- **正确记录错误日志**

```python
try:
    result = await self.execute_tool(tool_name, params)
except ToolNotFoundError:
    self.logger.error(f"Tool not found: {tool_name}")
    raise
except Exception as e:
    self.logger.exception(f"Unexpected error executing tool {tool_name}")
    raise
```

#### 7. 日志规范

使用`structlog`进行结构化日志：

```python
import structlog

logger = structlog.get_logger()

logger.info(
    "task_started",
    task_id=task.id,
    task_type=task.type,
)

logger.error(
    "task_failed",
    task_id=task.id,
    error=str(error),
)
```

#### 8. 测试规范

- **单元测试文件**：`test_<module_name>.py`
- **测试类名**：`Test<ClassName>`
- **测试方法名**：`test_<scenario>`

```python
class TestPerceptionManager:
    """PerceptionManager测试"""

    async def test_perceive(self):
        """测试感知收集"""
        manager = PerceptionManager()
        perceptions = await manager.perceive()
        assert len(perceptions) > 0
```

### TypeScript代码规范（前端）

#### 1. 命名规范

- **组件**：`PascalCase`（如`UserDashboard`）
- **函数/变量**：`camelCase`（如`fetchUserData`）
- **类型/接口**：`PascalCase`（如`UserProfile`）
- **常量**：`UPPER_SNAKE_CASE`（如`API_BASE_URL`）

#### 2. 组件规范

使用函数式组件 + Hooks：

```typescript
interface AgentListProps {
  agents: Agent[];
  onSelect: (agent: Agent) => void;
}

export const AgentList: React.FC<AgentListProps> = ({
  agents,
  onSelect,
}) => {
  return (
    <div className="agent-list">
      {agents.map(agent => (
        <AgentCard
          key={agent.id}
          agent={agent}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
};
```

## 🎯 Git提交规范

### 提交消息格式

```
<type>: <subject>

<body>

<footer>
```

### Type类型

| Type | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat: 实现WorkerAgent轻量级任务执行` |
| `fix` | Bug修复 | `fix: 修复Perception缺少timestamp参数` |
| `docs` | 文档更新 | `docs: 更新API文档` |
| `style` | 代码格式（不影响逻辑） | `style: 统一导入顺序` |
| `refactor` | 重构（不改变功能） | `refactor: 优化事件总线性能` |
| `perf` | 性能优化 | `perf: 减少数据库查询次数` |
| `test` | 测试相关 | `test: 添加WorkerAgent单元测试` |
| `chore` | 构建/工具相关 | `chore: 更新依赖版本` |
| `revert` | 回滚提交 | `revert: 回滚feat:xxx` |

### 提交消息示例

#### 简单提交

```bash
feat: 实现WorkerAgent轻量级任务执行Agent

核心功能:
- WorkerAgentConfig配置类
- 任务执行支持(tool_execution/llm_generation/custom)
- 超时控制和重试机制
- 回调系统和指标收集
```

#### 复杂提交

```bash
fix: 修复UserMessageSensor缺少timestamp参数

问题:
- Perception数据类要求timestamp参数
- UserMessageSensor.sense()未传递timestamp
- 导致创建Perception时抛出TypeError

修复:
- 为所有内置传感器添加timestamp参数
- 使用time.time()获取当前时间
- 统一导入time模块

影响文件:
- backend/src/magi/awareness/sensors.py
```

### 提交最佳实践

1. **使用英文**：所有提交消息使用英文
2. **原子化提交**：每个提交只做一件事
3. **清晰简洁**：subject不超过50字符
4. **信息完整**：body说明原因和影响
5. **及时提交**：频繁提交，避免大而全的提交

### 提合命令示例

```bash
# 简单提交
git commit -m "feat: 添加用户消息传感器"

# 多行提交
git commit -m "feat: 实现WorkerAgent

核心功能:
- WorkerAgentConfig配置类
- 超时控制和重试机制
- 完成回调系统

测试:
- 所有测试通过"

# 修复提交
git commit -m "fix: 修复感知管理器去重逻辑

问题: 去重缓存未正确更新
修复: 添加缓存大小限制和FIFO淘汰策略"
```

## 🔄 开发工作流

### 功能开发流程

1. **创建OpenSpec变更**（可选）
   ```bash
   /opsx:new feature-name
   ```

2. **实现功能**
   - 创建/修改代码文件
   - 遵循代码规范
   - 添加类型注解和文档字符串

3. **编写测试**
   - 创建测试文件
   - 覆盖核心场景
   - 确保测试通过

4. **运行测试**
   ```bash
   cd backend
   python examples/test_<feature>.py
   ```

5. **提交代码**
   ```bash
   git add .
   git commit -m "feat: 添加XXX功能"
   git push
   ```

### 分支策略

- `main`：主分支，稳定版本
- `feature/*`：功能开发分支
- `fix/*`：Bug修复分支
- `refactor/*`：重构分支

### 代码审查要点

- [ ] 遵循代码规范
- [ ] 添加类型注解
- [ ] 编写文档字符串
- [ ] 包含单元测试
- [ ] 测试全部通过
- [ ] 更新相关文档

## 📚 参考资源

### Python相关

- [PEP 8 - Style Guide](https://pep8.org/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [Type Hints](https://docs.python.org/3/library/typing.html)
- [AsyncIO](https://docs.python.org/3/library/asyncio.html)

### 框架文档

- [FastAPI](https://fastapi.tiangolo.com/)
- [Pydantic](https://docs.pydantic.dev/)
- [Structlog](https://www.structlog.org/)
- [SQLAlchemy](https://docs.sqlalchemy.org/)

### 前端相关

- [React TypeScript Cheatsheet](https://react-typescript-cheatsheet.netlify.app/)
- [Vite Guide](https://vitejs.dev/guide/)
- [Ant Design](https://ant.design/)

## 🏗️ 架构原则

### 设计原则

1. **单一职责**：每个类/函数只做一件事
2. **开闭原则**：对扩展开放，对修改关闭
3. **依赖倒置**：依赖抽象而非具体实现
4. **接口隔离**：使用细粒度的接口
5. **最少知识**：模块间最小化依赖

### 性能考虑

- **异步优先**：所有I/O使用异步
- **连接池**：数据库使用连接池
- **缓存策略**：合理使用缓存
- **批量操作**：减少数据库往返
- **索引优化**：为查询字段添加索引

### 安全考虑

- **输入验证**：使用Pydantic验证输入
- **SQL注入**：使用参数化查询
- **敏感信息**：使用环境变量
- **权限控制**：工具和插件权限管理
- **错误处理**：不暴露敏感信息

---

**最后更新**：2025-02-08
**维护者**：Magi开发团队
