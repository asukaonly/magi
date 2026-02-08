# Magi - AI Agent Framework

一个轻量级、可本地部署的AI Agent框架，支持自循环执行、自感知状态和自处理逻辑。

## 特性

- **自循环执行**: 基于Sense-Plan-Act-Reflect循环模型，Agent可持续自主运行
- **自感知能力**: 支持多种感知源（用户消息、传感器、摄像头、麦克风等）
- **自处理机制**: 从经验中学习，沉淀可复用能力，支持人机协作
- **插件系统**: 灵活的插件接口，支持自定义工具和扩展
- **本地优先**: 支持完全本地部署，数据完全可控
- **Web UI**: 提供可视化管理界面，实时监控Agent状态

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+

### 安装

#### 后端

```bash
cd backend
pip install -r requirements.txt
```

#### 前端

```bash
cd frontend
npm install
```

### 配置

复制示例配置文件并修改：

```bash
cp configs/agent.yaml.example configs/agent.yaml
# 编辑 configs/agent.yaml，设置LLM API密钥等
```

### 启动

#### 启动后端

```bash
cd backend
uvicorn src.api.main:app --reload --port 8000
```

#### 启动前端

```bash
cd frontend
npm run dev
```

访问 http://localhost:5173 查看Web UI。

## 项目结构

```
magi/
├── backend/               # Python后端
│   ├── src/
│   │   ├── magi/         # 框架核心包
│   │   │   ├── core/     # 核心模块
│   │   │   ├── awareness/# 自感知模块
│   │   │   ├── processing/# 自处理模块
│   │   │   ├── plugins/  # 插件系统
│   │   │   ├── tools/    # 工具系统
│   │   │   ├── memory/   # 记忆系统
│   │   │   ├── llm/      # LLM适配器
│   │   │   ├── events/   # 事件系统
│   │   │   └── config/   # 配置管理
│   │   └── api/          # API层
│   └── requirements.txt
├── frontend/             # TypeScript前端
│   ├── src/
│   │   ├── components/   # React组件
│   │   ├── pages/        # 页面
│   │   └── ...
│   └── package.json
└── configs/              # 配置文件
```

## 开发指南

### 开发自定义工具

```python
from magi.tools import Tool, ToolResult

class MyTool(Tool):
    async def execute(self, params: dict) -> ToolResult:
        # 实现工具逻辑
        result = await self.do_something(params)
        return ToolResult(success=True, data=result)

    @property
    def schema(self):
        return {
            "name": "my_tool",
            "description": "My custom tool",
            "parameters": {
                "param1": {"type": "string", "required": true}
            }
        }
```

### 开发自定义传感器

```python
from magi.awareness import Sensor, Perception, PerceptionType

class MySensor(Sensor):
    @property
    def perception_type(self) -> PerceptionType:
        return PerceptionType.CUSTOM

    async def sense(self) -> Optional[Perception]:
        # 实现感知逻辑
        data = await self.collect_data()
        return Perception(
            type="custom",
            source="my_sensor",
            data=data,
            timestamp=time.time()
        )
```

### 开发插件

```python
from magi.plugins import Plugin

class MyPlugin(Plugin):
    async def before_sense(self, context):
        # 在感知前执行
        pass

    async def after_act(self, result):
        # 在执行后执行
        pass

    def get_tools(self) -> List[Tool]:
        # 返回插件提供的工具
        return [MyTool()]
```

## 文档

- [API文档](./docs/api.md)
- [架构设计](./docs/architecture.md)
- [插件开发指南](./docs/plugins.md)
- [部署指南](./docs/deployment.md)

## 许可证

MIT License

## 贡献

欢迎提交Issue和Pull Request！
