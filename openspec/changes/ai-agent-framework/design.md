## Context

**背景**: 当前AI Agent开发缺乏统一的本地部署框架，开发者需要重复构建基础设施（任务调度、状态管理、工具集成等）。现有方案如LangChain、AutoGPT等或过于复杂，或依赖云端服务，不适合构建轻量级、可控的本地Agent。

**约束条件**:
- 必须支持完全本地部署，不依赖外部云服务
- 框架核心保持轻量，避免过度工程化
- 提供清晰的扩展点，支持自定义插件和工具
- 支持多种LLM后端（OpenAI API、本地模型等）
- 兼容Python 3.10+

**利益相关者**:
- Agent开发者：需要快速构建和部署智能体
- 插件开发者：需要开发可复用的工具和扩展
- 系统运维者：需要监控和维护Agent运行状态

## Goals / Non-Goals

**Goals:**
- 构建轻量级、可本地部署的Agent框架核心
- 提供标准化的插件接口和工具加载机制
- 实现Agent自循环执行引擎，支持基于感知输入的持续运行
- 实现自感知机制，支持Agent感知外部世界（用户、传感器、视觉、听觉等）
- 实现自处理能力，Agent根据感知情况自主决策，并沉淀处理经验
- 支持Human-in-the-Loop，在Agent无法处理时寻求人类帮助
- 提供本地持久化存储，支持Agent记忆和能力管理
- 提供Web UI，可视化监控Agent状态和管理感知输入

**Non-Goals:**
- 不构建完整的Agent应用（仅提供框架能力）
- 不实现云端部署和分布式调度（仅单机本地运行）
- 不内置具体的工具实现（由插件生态提供）
- 不实现多Agent协作（未来版本考虑）

## Decisions

### 1. 整体架构设计：前后端分离的分层模块化架构

**决策**: 采用**Python Core + TypeScript UI**的混合架构，自底向上分为：基础设施层、核心层、API层、UI层

```
┌────────────────────────────────────────────────────────┐
│              UI层 (Web Dashboard)                      │
│         React + TypeScript + TailwindCSS              │
│  - Agent监控面板  - 任务管理界面  - 配置管理           │
│  - 实时日志流    - 记忆可视化    - 性能图表           │
└────────────────────────────────────────────────────────┘
                    ▲ HTTP/WebSocket
                    │
┌────────────────────────────────────────────────────────┐
│              API层 (API Gateway)                       │
│              FastAPI + Python                          │
│  - RESTful API    - WebSocket实时推送                 │
│  - 认证授权      - 请求路由          - 数据校验       │
└────────────────────────────────────────────────────────┘
                    ▲
┌────────────────────────────────────────────────────────┐
│            应用层 (Application)                        │
│     (用户Agent实现、业务逻辑、配置管理)                 │
└────────────────────────────────────────────────────────┘
                    ▲
┌────────────────────────────────────────────────────────┐
│          扩展层 (Extension)                            │
│  (插件、工具、记忆后端、LLM适配器)                      │
└────────────────────────────────────────────────────────┘
                    ▲
┌────────────────────────────────────────────────────────┐
│            核心层 (Core)                               │
│  (Agent引擎、循环控制器、状态管理器)                    │
└────────────────────────────────────────────────────────┘
                    ▲
┌────────────────────────────────────────────────────────┐
│         基础设施层 (Infrastructure)                    │
│  (消息总线、事件系统、日志、配置加载)                   │
└────────────────────────────────────────────────────────┘
```

**理由**:
- **关注点分离**: 每层职责明确，降低耦合
- **可扩展性**: 扩展层提供标准化接口，第三方可自由扩展
- **可测试性**: 分层架构便于单元测试和集成测试
- **渐进式学习**: 用户可从简单API开始，逐步深入底层能力

**替代方案**:
- **微服务架构**: 过于复杂，不适合本地轻量部署
- **单体架构**: 扩展性差，难以插件化

### 2. 核心组件设计

#### 2.1 Agent Core (核心引擎)

**决策**: Agent Core采用生命周期管理模式，提供统一的Agent抽象基类

```python
class Agent:
    def __init__(self, config: AgentConfig):
        self.config = config
        self.state = AgentState.IDLE
        self.memory = MemoryStore()
        self.tool_registry = ToolRegistry()
        self.loop_engine = LoopEngine(self)

    async def start(self):
        """启动Agent，初始化所有组件"""

    async def stop(self):
        """优雅停止Agent"""

    async def run(self, task: Task) -> Result:
        """执行单个任务"""
```

**关键职责**:
- 管理Agent生命周期（初始化、启动、停止、清理）
- 协调各组件（循环引擎、工具注册器、记忆存储）
- 提供任务执行入口

#### 2.2 Loop Engine (自循环引擎)

**决策**: 采用**Sense-Plan-Act-Reflect**循环模型，基于感知输入驱动Agent持续运行

```python
class LoopEngine:
    """Agent循环引擎 - 感知-决策-执行-反思"""

    def __init__(self, agent: Agent, strategy: LoopStrategy):
        self.agent = agent
        self.perception_module = agent.perception_module  # 感知模块
        self.processing_module = agent.processing_module  # 处理模块
        self.strategy = strategy  # STEP/WAVE/CONTINUOUS
        self.is_running = False

    async def start(self):
        """启动循环"""
        self.is_running = True
        logger.info("Agent循环已启动")

        while self.is_running:
            try:
                # 1. Sense - 感知世界
                perceptions = await self.sense()

                if not perceptions:
                    # 无感知输入，等待
                    await self.strategy.wait()
                    continue

                # 2. Plan & Act - 处理每个感知输入
                for perception in perceptions:
                    action = await self.processing_module.process(perception)
                    result = await self.act(action)

                    # 3. Reflect - 反思并学习
                    await self.reflect(perception, action, result)

                    # STEP模式下每处理一个感知后暂停
                    if self.strategy.mode == "STEP":
                        await self.strategy.wait()

                # WAVE模式下处理完一批后暂停
                if self.strategy.mode == "WAVE":
                    await self.strategy.wait()

            except Exception as e:
                logger.error(f"循环执行错误: {e}")
                await self.handle_error(e)

    async def sense(self) -> List[Perception]:
        """感知 - 收集外部世界输入"""
        logger.debug("开始感知...")
        perceptions = await self.perception_module.perceive()
        logger.info(f"感知到 {len(perceptions)} 个输入")
        return perceptions

    async def act(self, action: Action) -> ActionResult:
        """执行 - 执行处理动作"""
        logger.info(f"执行动作: {action.type}")

        if action.type == "use_tool":
            result = await self.agent.tool_registry.execute(
                action.tool_name,
                action.params
            )
        elif action.type == "send_message":
            result = await self.send_message(action.content)
        elif action.type == "wait":
            await asyncio.sleep(action.duration)
            result = ActionResult(success=True)
        else:
            result = await self.execute_custom_action(action)

        return result

    async def reflect(self, perception: Perception,
                     action: Action, result: ActionResult):
        """反思 - 评估结果并更新记忆"""
        logger.info(f"反思: 感知={perception.type}, 动作={action.type}, "
                   f"结果={'成功' if result.success else '失败'}")

        # 更新能力成功率
        if action.capability_id:
            await self.agent.capability_store.update_success_rate(
                action.capability_id,
                result.success
            )

        # 存储经验到记忆
        experience = Experience(
            perception=perception,
            action=action,
            result=result,
            timestamp=time.time()
        )
        await self.agent.memory.store(experience)

        # 发布事件
        await self.agent.event_bus.publish(
            Event(type="cycle_completed", data=experience.dict())
        )
```

**循环策略**:

1. **STEP - 单步模式**（调试用）
```python
class StepStrategy:
    """单步执行策略 - 每处理一个感知后暂停"""
    async def wait(self):
        await input("按Enter继续...")  # 等待用户确认
```

2. **WAVE - 波次模式**（批处理用）
```python
class WaveStrategy:
    """波次执行策略 - 处理一批感知后暂停"""
    def __init__(self, batch_size: int = 10, interval: int = 5):
        self.batch_size = batch_size
        self.interval = interval

    async def wait(self):
        await asyncio.sleep(self.interval)
```

3. **CONTINUOUS - 持续模式**（长期运行）
```python
class ContinuousStrategy:
    """持续执行策略 - 不暂停，持续运行"""
    async def wait(self):
        await asyncio.sleep(0.1)  # 短暂休眠，避免CPU占用
```

**Sense-Plan-Act-Reflect流程图**:
```
┌─────────────────────────────────────────────┐
│ 1. Sense (感知)                             │
│    - 用户消息                               │
│    - 传感器数据                             │
│    - 视觉/听觉输入                          │
│    - 事件触发                               │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 2. Plan (决策)                              │
│    - 查找已有处理能力                       │
│    - 无能力? → 人类介入 / LLM决策           │
│    - 生成处理动作                           │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 3. Act (执行)                               │
│    - 调用工具                               │
│    - 发送消息                               │
│    - 等待/记录                              │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 4. Reflect (反思)                           │
│    - 评估执行结果                           │
│    - 更新能力成功率                         │
│    - 沉淀新的处理能力                       │
│    - 存储经验到记忆                         │
└─────────────────────────────────────────────┘
                    ↓
                返回感知 (持续循环)
```

**理由**:
- **真正的自主智能体**: 基于外部感知而非内部状态驱动
- **可复用能力**: 每次循环都可能沉淀新的处理能力
- **渐进式智能**: 随着时间推移，Agent越来越智能
- **人类协作**: 在不确定时寻求人类帮助
- **灵活控制**: 三种循环策略适应不同场景

#### 2.3 Self-Awareness Module (自感知模块)

**决策**: 采用**多源感知器架构**，支持Agent感知外部世界的各种输入

```python
class PerceptionModule:
    """自感知模块 - Agent的感官系统"""

    def __init__(self):
        self.sensors: Dict[str, Sensor] = {}  # 各种感知器

    def register_sensor(self, name: str, sensor: Sensor):
        """注册感知器"""
        self.sensors[name] = sensor

    async def perceive(self) -> List[Perception]:
        """收集所有感知输入"""
        perceptions = []

        # 并发从所有感知器获取输入
        tasks = [sensor.sense() for sensor in self.sensors.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Perception):
                perceptions.append(result)
            elif isinstance(result, Exception):
                logger.error(f"感知器错误: {result}")

        return perceptions
```

**感知输入类型**:

1. **用户输入感知**
```python
class UserMessageSensor(Sensor):
    """用户消息感知器"""
    async def sense(self) -> Optional[Perception]:
        # 从WebSocket、CLI、API获取用户消息
        message = await self.message_queue.get()
        return Perception(
            type="user_message",
            source="chat",
            data={"text": message, "user_id": message.user_id},
            timestamp=time.time()
        )
```

2. **传感器数据感知**
```python
class SensorDataSensor(Sensor):
    """传感器数据感知器"""
    async def sense(self) -> Optional[Perception]:
        data = await self.read_sensor()
        return Perception(
            type="sensor_data",
            source="temperature_sensor",
            data={"temperature": data.temp, "humidity": data.humidity},
            timestamp=time.time()
        )
```

3. **视觉感知**
```python
class CameraSensor(Sensor):
    """摄像头感知器"""
    async def sense(self) -> Optional[Perception]:
        frame = await self.capture_frame()
        objects = await self.detect_objects(frame)
        return Perception(
            type="vision",
            source="camera",
            data={"frame": frame, "objects": objects},
            timestamp=time.time()
        )
```

4. **听觉感知**
```python
class MicrophoneSensor(Sensor):
    """麦克风感知器"""
    async def sense(self) -> Optional[Perception]:
        audio = await self.listen()
        text = await self.speech_to_text(audio)
        return Perception(
            type="audio",
            source="microphone",
            data={"audio": audio, "text": text},
            timestamp=time.time()
        )
```

5. **事件感知**
```python
class EventSensor(Sensor):
    """事件感知器（定时器、文件变化、Webhook等）"""
    async def sense(self) -> Optional[Perception]:
        event = await self.event_queue.get()
        return Perception(
            type="event",
            source=event.source,
            data=event.payload,
            timestamp=time.time()
        )
```

**感知器插件接口**:
```python
class Sensor(ABC):
    """感知器基类"""
    @abstractmethod
    async def sense(self) -> Optional[Perception]:
        """感知一次，返回感知数据或None"""
        pass

    @property
    @abstractmethod
    def schema(self) -> SensorSchema:
        """返回感知器的元数据"""
        pass
```

**Perception数据结构**:
```python
@dataclass
class Perception:
    """感知输入"""
    type: str              # 感知类型（user_message/sensor_data/vision/audio/event）
    source: str            # 感知源标识
    data: Any              # 感知数据
    timestamp: float       # 时间戳
    priority: int = 0      # 优先级（0=普通，1=重要，2=紧急）
    metadata: Dict = None  # 额外元数据
```

#### 2.4 Self-Processing Module (自处理模块)

**决策**: 采用**能力沉淀机制**，Agent根据感知情况自主决策或寻求人类帮助，并将处理能力沉淀为可复用经验

```python
class SelfProcessingModule:
    """自处理模块 - Agent的决策和经验积累系统"""

    def __init__(self, capability_store: CapabilityStore, llm: LLMAdapter):
        self.capability_store = capability_store  # 能力仓库
        self.llm = llm
        self.human_in_the_loop = True  # 是否启用人工介入

    async def process(self, perception: Perception) -> Action:
        """处理感知输入"""

        # 1. 查找已有处理能力
        existing_capability = await self.capability_store.find(perception)

        if existing_capability:
            # 有经验 -> 自动处理
            logger.info(f"使用已有能力处理: {existing_capability.name}")
            return await self._execute_capability(existing_capability, perception)

        # 2. 无经验 -> 决策如何处理
        action = await self._decide_action(perception)

        # 3. 执行处理
        result = await self._execute_action(action)

        # 4. 沉淀能力
        await self._save_capability(perception, action, result)

        return action

    async def _decide_action(self, perception: Perception) -> Action:
        """决策如何处理感知输入"""

        # 判断是否需要人类介入
        if self.human_in_the_loop and await self._should_ask_human(perception):
            # 交给人类处理
            return await self._ask_human_for_help(perception)

        # 让LLM决策
        return await self._llm_decision(perception)

    async def _should_ask_human(self, perception: Perception) -> bool:
        """判断是否需要人类介入"""
        # 高优先级感知 -> 需要人类确认
        if perception.priority >= 2:
            return True

        # 未知类型的感知 -> 需要人类指导
        if perception.type not in self.known_perception_types:
            return True

        # 涉及重要操作的感知 -> 需要人类授权
        if self._is_critical_operation(perception):
            return True

        return False

    async def _ask_human_for_help(self, perception: Perception) -> Action:
        """向人类请求帮助"""
        # 通过WebSocket、CLI等方式发送请求
        human_response = await self.human_interface.ask(
            f"Agent遇到无法处理的情况:\n{perception}\n请指示如何处理"
        )
        return Action(
            type="human_guided",
            instructions=human_response,
            source="human"
        )

    async def _llm_decision(self, perception: Perception) -> Action:
        """让LLM决策处理方式"""
        prompt = f"""
        感知输入: {perception}
        可用工具: {self.tool_registry.list_tools()}

        请决定如何处理这个感知输入，返回Action。
        """
        response = await self.llm.generate(prompt)
        return self._parse_action(response)

    async def _save_capability(self, perception: Perception,
                               action: Action, result: ActionResult):
        """沉淀处理能力"""
        capability = Capability(
            trigger_pattern=perception,       # 触发模式
            action=action,                    # 处理动作
            result=result,                    # 处理结果
            success_rate=1.0 if result.success else 0.0,
            usage_count=1,
            created_at=time.time()
        )

        await self.capability_store.save(capability)
        logger.info(f"能力已沉淀: {action.name}")
```

**能力仓库**:
```python
class CapabilityStore:
    """能力仓库 - 沉淀和复用处理能力"""

    def __init__(self, vector_db: VectorDB, memory: MemoryStore):
        self.vector_db = vector_db  # 向量数据库，支持语义检索
        self.memory = memory

    async def save(self, capability: Capability):
        """保存能力"""
        # 将触发模式转换为向量
        embedding = await self._embed_capability(capability.trigger_pattern)

        # 存储到向量数据库
        await self.vector_db.add(
            embedding=embedding,
            metadata={
                "action": capability.action.dict(),
                "success_rate": capability.success_rate,
                "usage_count": capability.usage_count,
                "created_at": capability.created_at
            }
        )

    async def find(self, perception: Perception,
                   min_success_rate: float = 0.7) -> Optional[Capability]:
        """查找已有处理能力"""
        # 将感知输入转换为向量
        query_embedding = await self._embed_perception(perception)

        # 语义搜索
        results = await self.vector_db.search(
            query=query_embedding,
            top_k=3,
            filter={"success_rate": {"$gte": min_success_rate}}
        )

        if results:
            # 返回最匹配的能力
            return Capability.from_dict(results[0].metadata)
        return None

    async def update_success_rate(self, capability_id: str,
                                  success: bool):
        """更新能力成功率（持续学习）"""
        capability = await self.get(capability_id)

        # 更新成功率（指数移动平均）
        alpha = 0.3  # 学习率
        new_rate = (1 - alpha) * capability.success_rate + alpha * (1.0 if success else 0.0)

        capability.success_rate = new_rate
        capability.usage_count += 1

        await self.save(capability)
```

**Human-in-the-Loop机制**:
```python
class HumanInterface:
    """人工交互界面"""

    async def ask(self, question: str, timeout: int = 300) -> str:
        """向人类提问并等待回答"""
        request = HumanRequest(
            question=question,
            timestamp=time.time(),
            timeout=timeout
        )

        # 发送到WebSocket、CLI等
        await self.send_to_ui(request)

        # 等待人类响应
        response = await self.wait_for_response(request.id, timeout)
        return response

    async def send_to_ui(self, request: HumanRequest):
        """发送到Web UI"""
        await self.websocket_manager.broadcast({
            "type": "human_help_request",
            "request_id": request.id,
            "question": request.question,
            "timeout": request.timeout
        })

    async def wait_for_response(self, request_id: str,
                                timeout: int) -> str:
        """等待人类响应"""
        # 实现超时等待逻辑
        ...
```

**处理流程图**:
```
感知输入 (Perception)
    ↓
查找已有能力 (CapabilityStore.find)
    ↓
有经验? ──Yes──> 自动执行 ──> 更新成功率
    │ No
    ↓
需要人类介入? ──Yes──> 询问人类 ──> 执行 ──> 沉淀能力
    │ No
    ↓
LLM决策 ──> 执行 ──> 沉淀能力
```

**关键特性**:
1. **多源感知**: 支持用户消息、传感器、视觉、听觉、事件等多种输入
2. **能力沉淀**: 将处理经验存储为可复用能力
3. **语义检索**: 通过向量数据库实现智能匹配
4. **人工介入**: 在无法处理时寻求人类帮助
5. **持续学习**: 根据执行结果动态更新成功率
6. **插件化感知器**: 支持自定义感知器扩展

#### 2.5 Plugin System (插件系统)

**决策**: 采用基于抽象基类（ABC）的插件接口，支持动态加载

**插件类型**:
1. **Tool Plugin (工具插件)**
```python
class Tool(ABC):
    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        """执行工具逻辑"""

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """返回工具的参数schema"""
```

2. **Memory Plugin (记忆插件)**
```python
class MemoryBackend(ABC):
    @abstractmethod
    async def store(self, key: str, value: Any):
        """存储数据"""

    @abstractmethod
    async def retrieve(self, key: str) -> Any:
        """检索数据"""
```

3. **LLM Adapter Plugin (LLM适配器)**
```python
class LLMAdapter(ABC):
    @abstractmethod
    async def generate(self, prompt: str) -> str:
        """生成文本"""
```

**插件加载机制**:
- **内置插件**: 框架自带的基础工具（如文件操作、HTTP请求）
- **本地插件**: 从指定目录加载Python模块
- **远程插件**: 从Git仓库或PyPI安装（可选）

#### 2.6 Tool Registry (工具注册中心)

**决策**: 采用集中式注册表，支持工具的注册、发现、权限控制

```python
class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        """注册工具"""

    def get(self, name: str) -> Tool:
        """获取工具"""

    def list_tools(self) -> List[ToolSchema]:
        """列出所有可用工具"""

    async def execute(self, name: str, params: dict) -> ToolResult:
        """执行工具"""
```

**工具元数据**:
```python
@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: Dict[str, ParameterSchema]  # JSON Schema格式
    permissions: List[str]  # 权限列表（如 "file.read", "network.request"）
```

#### 2.7 Message Bus (消息总线)

**决策**: 采用**发布-订阅模式 + 优先级队列 + 多Backend架构**，实现组件间解耦通信和事件持久化

**核心特性**:
- ✅ 全异步事件处理
- ✅ 支持广播和竞争消费两种传播模式
- ✅ 优先级队列（按事件等级）
- ✅ 背压机制（防止内存爆炸）
- ✅ 事件过滤和负载均衡
- ✅ 可选持久化（三层架构）
- ✅ 错误隔离（单个handler失败不影响其他）

**三层Backend架构**:
```python
# 抽象接口
class MessageBusBackend(ABC):
    @abstractmethod
    async def publish(self, event: Event) -> bool:
        """发布事件"""

    @abstractmethod
    async def subscribe(self, event_type: str, handler: Callable):
        """订阅事件"""

# 实现1: 内存队列（默认，零依赖）
class MemoryMessageBackend(MessageBusBackend):
    """基于asyncio.PriorityQueue的内存队列"""
    - 优点：最快速度、零依赖
    - 缺点：不持久化，重启丢失

# 实现2: SQLite（轻量级持久化）
class SQLiteMessageBackend(MessageBusBackend):
    """基于aiosqlite的持久化队列"""
    - 优点：Python内置、单文件、轻量级
    - 缺点：性能略低于内存
    - 适用：本地部署场景

# 实现3: Redis（可选，分布式）
class RedisMessageBackend(MessageBusBackend):
    """基于Redis Streams的分布式队列"""
    - 优点：分布式、高可用
    - 缺点：需要额外服务
    - 适用：生产环境、多机部署
```

**事件数据结构**（增强版 + 事件等级）:
```python
from enum import IntEnum
from dataclasses import dataclass

class EventLevel(IntEnum):
    """事件等级（影响优先级和持久化策略）"""
    DEBUG = 0      # 调试信息
    INFO = 1       # 普通信息
    WARNING = 2    # 警告
    ERROR = 3      # 错误
    CRITICAL = 4   # 严重错误
    EMERGENCY = 5  # 紧急事件（最高优先级）

@dataclass
class Event:
    """事件数据结构"""
    type: str                    # 事件类型
    data: Any                    # 事件数据
    timestamp: float             # 时间戳
    source: str                  # 事件源
    level: EventLevel            # 事件等级
    correlation_id: Optional[str] = None  # 关联ID（追踪事件链）
    metadata: Dict = None        # 额外元数据
```

**优先级队列 + 背压机制**:
```python
class BoundedPriorityQueue:
    """有界优先级队列 - 防止内存爆炸"""

    def __init__(self, max_size: int = 1000, drop_policy: str = "lowest_priority"):
        """
        Args:
            max_size: 队列最大长度（从配置读取）
            drop_policy: 队列满时的丢弃策略
                - "oldest": 丢弃最旧的事件
                - "lowest_priority": 丢弃优先级最低的事件
                - "reject": 拒绝新事件
        """
        self.max_size = max_size
        self.drop_policy = drop_policy
        self._queue: List[tuple] = []  # (priority, counter, event)

    async def put(self, event: Event) -> bool:
        """放入事件，返回是否成功"""
        priority = event.level.value

        # 队列未满，直接放入
        if len(self._queue) < self.max_size:
            heappush(self._queue, (priority, counter, event))
            return True

        # 队列已满，根据策略处理
        if self.drop_policy == "lowest_priority":
            # 如果新事件优先级更高，替换最低优先级事件
            if priority > self._queue[0][0]:
                heappop(self._queue)
                heappush(self._queue, (priority, counter, event))
                return True
        # ... 其他策略
```

**传播模式**:
```python
class PropagationMode(Enum):
    BROADCAST = "broadcast"      # 广播：所有订阅者都收到
    COMPETING = "competing"      # 竞争：只有一个订阅者收到

# 负载均衡的竞争调度
class LoadAwareDispatcher:
    """负载感知的竞争调度"""

    def select_handler(self, handlers: List[Callable]) -> Callable:
        """选择pending数量最少的handler"""
        return min(handlers, key=lambda h: self.pending_counts.get(h, 0))
```

**SQLite持久化实现**:
```python
class SQLiteMessageQueue:
    """基于SQLite的持久化消息队列（轻量级）"""

    def __init__(self, db_path: str = "magi_events.db"):
        self.db_path = db_path

    async def init(self):
        """初始化数据库表"""
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                event_data TEXT NOT NULL,
                priority INTEGER NOT NULL,
                created_at REAL NOT NULL,
                processed BOOLEAN DEFAULT FALSE
            )
        """)

    async def push(self, event: Event) -> bool:
        """持久化事件到SQLite"""
        await db.execute(
            "INSERT INTO events (event_type, event_data, priority, created_at) VALUES (?, ?, ?, ?)",
            (event.type, json.dumps(event.to_dict()), event.level.value, time.time())
        )

    async def pop(self, event_type: Optional[str]) -> Optional[Event]:
        """取出队列（FIFO + 优先级）"""
        # 按优先级降序、时间升序查询
        cursor = await db.execute("""
            SELECT event_data FROM events
            WHERE processed = FALSE
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
        """)
        # 标记为已处理并返回
```

**事件过滤**:
```python
# 支持过滤函数的订阅
bus.subscribe(
    "Perception",
    handler=urgent_handler,
    filter_func=lambda e: e.data.get("priority", 0) >= 2  # 只处理高优先级
)

bus.subscribe(
    "TaskFailed",
    handler=timeout_handler,
    filter_func=lambda e: e.data.get("error_type") == "TimeoutError"
)
```

**配置化切换**:
```yaml
# config/magi.yaml
message_bus:
  # backend类型: memory | sqlite | redis
  backend: sqlite  # 本地部署推荐

  # SQLite配置
  sqlite:
    db_path: "./data/magi_events.db"
    memory_cache_size: 100
    retention_days: 7  # 事件保留天数

  # Redis配置（backend=redis时）
  redis:
    url: "redis://localhost:6379"
    stream_maxlen: 10000

  # 通用配置
  max_queue_size: 1000      # 从配置读取
  drop_policy: lowest_priority
  num_workers: 4
```

**依赖项**:
```python
# pyproject.toml
[dependencies]
python = "^3.10"
aiosqlite = "^0.19.0"  # SQLite异步支持（轻量级，50KB）

[extras]
redis = ["redis"]  # 可选
```

**核心事件类型**:
- **生命周期**: AgentStarted, AgentStopped, StateChanged
- **感知事件**: PerceptionReceived, PerceptionProcessed
- **处理事件**: ActionExecuted, CapabilityCreated
- **学习事件**: ExperienceStored, CapabilityUpdated
- **错误事件**: ErrorOccurred, HandlerFailed

#### 2.8 Memory Store (记忆存储)

**决策**: 采用**三层记忆 + 事件五层架构**，实现Agent的自我认知、他人认知和事件记忆

**核心架构**:
```
Memory Store
    │
    ├── 自我记忆 (Self Memory)
    │   ├── Agent静态设定
    │   └── 用户习惯/偏好（动态更新）
    │
    ├── 他人记忆 (Other Memory)
    │   ├── 用户画像（优先实现）
    │   └── 其他人（未来扩展）
    │
    └── 事件记忆 (Event Memory) - 5层架构
        ├── L1: 原始事件（非结构化）
        ├── L2: 事件关系（图数据库）
        ├── L3: 事件语义（向量嵌入）
        ├── L4: 摘要总结（多时间粒度）
        └── L5: 能力记忆（自处理经验）
```

**为什么这样设计**：
- **分层清晰**：自我/他人/事件三个维度覆盖Agent的所有记忆需求
- **事件过滤**：只记录"现实事件"，内部流转事件不记录，避免存储爆炸
- **渐进式总结**：多时间粒度总结，防止信息过载
- **能力沉淀**：L5专门存储自处理层的经验，支持Agent持续学习

---

### 2.8.1 自我记忆 (Self Memory)

```python
class SelfMemory:
    """自我记忆 - Agent设定和用户习惯"""

    def __init__(self, db_path: str):
        self.db = SQLiteDB(db_path)

    async def get_agent_profile(self) -> AgentProfile:
        """获取Agent静态设定"""
        return await self.db.get("agent_profile")

    async def update_user_preferences(self, updates: Dict):
        """更新用户偏好（动态）"""
        current = await self.get_user_preferences()
        merged = {**current, **updates}
        await self.db.set("user_preferences", merged)
```

**存储内容**：
- Agent设定（名称、角色、性格）
- 用户偏好（交互方式、响应风格）
- 用户习惯（作息时间、常用功能）

---

### 2.8.2 他人记忆 (Other Memory)

```python
class OtherMemory:
    """他人记忆 - 用户画像和其他人"""

    def __init__(self):
        self.profiles = UserProfileStore()
        self.updater = AdaptiveProfileUpdater()

    async def update_profile(self, user_id: str, new_events: List[Event]):
        """更新用户画像（自适应频率）"""
        if self.updater.should_update(len(new_events)):
            await self.updater.update_profile(user_id, new_events)

    async def get_profile(self, user_id: str) -> UserProfile:
        """获取用户画像"""
        return await self.profiles.get(user_id)
```

**自适应更新策略（退避算法）**:
```python
class AdaptiveProfileUpdater:
    """自适应更新器 - 类似退避算法"""

    def __init__(self):
        self.event_count = 0
        self.last_update_at = time.time()

    def should_update(self, new_events: int) -> bool:
        """判断是否需要更新"""
        self.event_count += new_events

        # 前期（事件<10）：每3个事件更新一次
        if self.event_count < 10:
            return self.event_count >= 3

        # 中期（事件<100）：每天更新
        elif self.event_count < 100:
            days = (time.time() - self.last_update_at) / 86400
            return days >= 1

        # 后期（事件>=100）：每周更新
        else:
            weeks = (time.time() - self.last_update_at) / (7 * 86400)
            return weeks >= 1
```

**用户画像内容**：
```python
@dataclass
class UserProfile:
    user_id: str
    interests: List[str]        # 兴趣爱好
    habits: List[str]           # 习惯偏好
    personality: List[str]      # 性格特征
    relationships: Dict[str, str]  # 重要关系
    communication_style: str    # 沟通风格偏好
    last_updated: float
```

---

### 2.8.3 事件记忆 - 5层架构

#### L1: 原始事件层（非结构化）

```python
class RawEventStore:
    """原始事件存储 - 完整事件信息"""

    def __init__(self, db_path: str, media_dir: str):
        self.db = SQLiteDB(f"{db_path}/events.db")
        self.media_dir = media_dir  # ./data/events/

    async def store(self, event: Event) -> str:
        """存储事件"""
        # 1. 保存媒体文件（图片/音频）
        media_path = None
        if event.media:
            media_path = await self._save_media(event.media)

        # 2. 写入SQLite
        event_id = await self.db.insert(
            "INSERT INTO events (type, data, media_path, timestamp) VALUES (?, ?, ?, ?)",
            (event.type, json.dumps(event.data), media_path, event.timestamp)
        )

        return event_id

    async def _save_media(self, media: Media) -> str:
        """保存媒体文件（按日期组织）"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{uuid4()}.{media.extension}"
        path = f"{self.media_dir}/{date_str}/{filename}"

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(media.data)

        return path
```

**存储内容**：
- 事件类型、时间戳
- 非结构化数据（文本/图片/音频路径）
- 完整元数据

**事件过滤原则**：
- ✅ 记录：现实世界的变化（用户输入、传感器、邮件、日程）
- ❌ 不记录：内部流转（Agent内部事件循环、模块间通信）

---

#### L2: 事件关系层（图数据库）

```python
class EventGraph:
    """事件关系图 - SQLite + NetworkX"""

    def __init__(self, db_path: str):
        self.db = SQLiteDB(f"{db_path}/relations.db")
        self._graph = None  # 延迟加载

    async def add_relation(self, relation: Relation):
        """添加关系（持久化）"""
        await self.db.execute(
            "INSERT INTO relations (from_event, to_event, type, entities) VALUES (?, ?, ?, ?)",
            (relation.from_event, relation.to_event, relation.type, json.dumps(relation.entities))
        )

        # 清除缓存
        self._graph = None

    def get_graph(self) -> nx.DiGraph:
        """获取事件图（内存构建）"""
        if self._graph is None:
            self._graph = self._build_graph()
        return self._graph

    async def find_related_events(self, event_id: str, relation_type: str) -> List[str]:
        """查找相关事件"""
        return await self.db.fetch_all(
            "SELECT to_event FROM relations WHERE from_event = ? AND type = ?",
            (event_id, relation_type)
        )
```

**混合关系抽取（规则 + LLM）**:
```python
class EventRelationExtractor:
    """事件关系提取器"""

    async def extract(self, event: Event) -> List[Relation]:
        """提取事件关系"""

        # 结构化事件 → 规则提取
        if event.type in ["email_received", "meeting_scheduled", "task_created"]:
            return await self._extract_by_rules(event)

        # 非结构化事件 → LLM提取
        else:
            return await self._extract_by_llm(event)

    async def _extract_by_rules(self, event: Event) -> List[Relation]:
        """规则提取（结构化事件）"""
        relations = []

        if event.type == "email_received":
            relations.append(Relation(
                from_entity=event.data["from"],
                to_entity=event.data["to"],
                relation_type="sent_email",
                event_id=event.id,
                metadata={"subject": event.data["subject"]}
            ))

        elif event.type == "meeting_scheduled":
            for participant in event.data["participants"]:
                relations.append(Relation(
                    from_entity="user",
                    to_entity=participant,
                    relation_type="has_meeting_with",
                    event_id=event.id
                ))

        return relations

    async def _extract_by_llm(self, event: Event) -> List[Relation]:
        """LLM提取（非结构化事件）"""
        prompt = f"""
        事件描述：{event.data}

        请提取事件中的关系（实体1, 关系类型, 实体2）：
        格式：[用户] -- 和...吃饭 --> [A]
        """
        response = await self.llm.generate(prompt)
        return self._parse_relations(response)
```

**关系类型**：
- `involves`: 涉及（用户和A吃饭）
- `caused`: 导致（事件A导致事件B）
- `follows`: 跟随（事件B跟随事件A）
- `sent_email`: 发送邮件
- `has_meeting_with`: 会面

---

#### L3: 事件语义层（向量嵌入）

```python
class EventSemanticStore:
    """事件语义存储 - ChromaDB"""

    def __init__(self, persist_dir: str):
        self.chroma = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.chroma.get_or_create_collection("events")
        self.embedder = OpenAIEmbeddings()  # 或本地模型

    async def store(self, event: Event, semantic_data: Dict):
        """语义化 + 向量化存储"""

        # 1. LLM语义化
        semantic = await self._semanticize(event)

        # 2. 向量嵌入
        embedding = await self.embedder.embed(semantic)

        # 3. 存储到ChromaDB
        self.collection.add(
            embeddings=[embedding],
            documents=[semantic],
            metadatas=[{
                "event_id": event.id,
                "type": event.type,
                "timestamp": event.timestamp,
                **semantic_data
            }],
            ids=[event.id]
        )

    async def search(self, query: str, top_k: int = 5) -> List[Event]:
        """语义搜索"""
        query_embedding = await self.embedder.embed(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k
        )
        return results
```

**语义化内容**：
```python
{
    "action": "eating_together",
    "participants": ["user", "a"],
    "time": "today",
    "location": "restaurant",
    "intent": "socializing"
}
```

---

#### L4: 摘要总结层（多时间粒度）

```python
class EventSummaryStore:
    """事件摘要总结 - SQLite + 定时任务"""

    def __init__(self, db_path: str):
        self.db = SQLiteDB(f"{db_path}/summaries.db")
        self.scheduler = ScheduledSummarizer()

    async def start_scheduler(self):
        """启动定时任务（每天凌晨3点）"""
        await self.scheduler.start()

    async def summarize_daily(self, date: str):
        """日总结"""
        # 1. 获取当天所有事件
        events = await self.get_events_by_date(date)

        # 2. LLM总结
        prompt = f"""
        今天发生了这些事件：{events}

        请总结：
        1. 主要活动（3-5条）
        2. 接触的人
        3. 重要变化/决策
        4. 情绪/状态趋势
        """

        summary = await self.llm.generate(prompt)

        # 3. 存储
        await self.db.insert(
            "INSERT INTO daily_summaries (date, summary) VALUES (?, ?)",
            (date, summary)
        )
```

**定时任务配置**:
```python
class ScheduledSummarizer:
    """定时总结器"""

    SCHEDULE = [
        {"time": "03:00", "task": "daily_summary"},                    # 每天
        {"time": "03:00", "weekday": 0, "task": "weekly_summary"},   # 周一
        {"time": "03:00", "day": 1, "task": "monthly_summary"},      # 每月1号
    ]
```

**总结粒度**：
- 日总结：每天凌晨3点
- 周总结：每周一凌晨3点
- 月总结：每月1号凌晨3点
- 年总结：每年1月1号凌晨3点

---

#### L5: 能力记忆层（自处理经验）

```python
class CapabilityStore:
    """能力记忆 - 自处理层经验沉淀"""

    def __init__(self, db_path: str, vector_db_dir: str):
        # SQLite：结构化数据
        self.db = SQLiteDB(f"{db_path}/capabilities.db")

        # ChromaDB：向量检索（语义匹配）
        self.chroma = chromadb.PersistentClient(path=vector_db_dir)
        self.collection = self.chroma.get_or_create_collection("capabilities")

    async def save(self, capability: CapabilityMemory):
        """沉淀能力"""
        # 1. SQLite存储结构化数据
        await self.db.execute(
            "INSERT INTO capabilities (id, trigger, action, success_rate, usage_count) VALUES (?, ?, ?, ?, ?)",
            (capability.id, capability.trigger, capability.action, capability.success_rate, capability.usage_count)
        )

        # 2. ChromaDB存储向量（语义检索）
        embedding = await self.embed(capability.trigger_pattern)
        self.collection.add(
            embeddings=[embedding],
            ids=[capability.id],
            metadatas=[{
                "action": capability.action,
                "success_rate": capability.success_rate
            }]
        )

    async def find(self, perception: Perception) -> Optional[CapabilityMemory]:
        """查找已有能力（语义匹配）"""
        query_embedding = await self.embed(perception)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=1,
            where={"success_rate": {"$gte": 0.7}}  # 只返回成功率高的
        )

        if results["ids"][0]:
            capability_id = results["ids"][0][0]
            return await self.db.get_capability(capability_id)
        return None

    async def update_success_rate(self, capability_id: str, success: bool):
        """更新成功率（持续学习）"""
        capability = await self.db.get_capability(capability_id)

        # 指数移动平均
        alpha = 0.3
        new_rate = (1 - alpha) * capability.success_rate + alpha * (1.0 if success else 0.0)

        await self.db.execute(
            "UPDATE capabilities SET success_rate = ?, usage_count = usage_count + 1 WHERE id = ?",
            (new_rate, capability_id)
        )
```

**能力记忆结构**:
```python
@dataclass
class CapabilityMemory:
    capability_id: str
    trigger_pattern: Perception     # 触发模式
    action: Action                  # 处理动作
    success_rate: float             # 成功率
    usage_count: int                # 使用次数
    created_at: float               # 首次学习时间
    last_used_at: float             # 最后使用时间
    source: str                     # 来源（human/llm/experience）
```

---

### 技术栈总结

| 层级 | 存储方案 | 依赖 |
|------|----------|------|
| 自我记忆 | SQLite | Python内置 |
| 他人记忆 | SQLite | Python内置 |
| L1 原始事件 | SQLite + 文件系统 | Python内置 |
| L2 事件关系 | SQLite + NetworkX | pip install networkx |
| L3 事件语义 | ChromaDB | pip install chromadb |
| L4 摘要总结 | SQLite | Python内置 |
| L5 能力记忆 | SQLite + ChromaDB | pip install chromadb |

**全部轻量级，符合本地部署！**

### 3. 技术栈选择：混合架构

#### 3.1 后端技术栈（Python）

**编程语言**: Python 3.10+

**理由**:
- **AI生态无敌**: LangChain、LlamaIndex等主流Agent框架均为Python优先
- **LLM SDK支持最好**: OpenAI、Anthropic的Python SDK最完善
- **向量数据库兼容**: ChromaDB、FAISS、Weaviate等都优先支持Python
- **数据处理强**: pandas、numpy对记忆/日志分析很有用
- **开发速度快**: 语法简洁，适合快速原型

**Web框架**: FastAPI

**理由**:
- **异步原生**: 基于Starlette，完美支持asyncio
- **自动文档**: 自动生成OpenAPI/Swagger文档
- **类型校验**: Pydantic提供请求/响应自动验证
- **性能优秀**: 性能接近Go和Node.js
- **WebSocket支持**: 原生支持WebSocket，适合实时推送

**关键依赖**:
```python
# 核心框架
asyncio (异步)
FastAPI (Web框架)
Uvicorn (ASGI服务器)
Pydantic (数据校验)

# AI相关
OpenAI Python SDK
Anthropic Python SDK
LangChain / LlamaIndex (可选参考)

# 向量数据库
ChromaDB (默认，易用)
FAISS (高性能选项)

# 其他
structlog (结构化日志)
PyJWT (认证)
python-multipart (文件上传)
```

#### 3.2 前端技术栈（TypeScript）

**框架**: React 18 + TypeScript

**理由**:
- **类型安全**: TypeScript提供强类型，减少运行时错误
- **生态成熟**: React生态最丰富，组件库和工具链完善
- **开发体验**: Hot reload、Redux DevTools等提升效率
- **性能优秀**: 虚拟DOM和Fiber架构保证流畅体验
- **社区活跃**: 大量开源组件和最佳实践

**构建工具**: Vite

**理由**:
- **极速启动**: 基于ESM，冷启动快
- **热更新**: HMR速度远超Webpack
- **配置简单**: 零配置开箱即用
- **原生支持**: 对TypeScript、JSX开箱即用

**UI组件库**: Ant Design / shadcn/ui

**理由**:
- **组件丰富**: Table、Form、Chart等开箱即用
- **设计一致**: 统一的设计语言
- **TypeScript友好**: 完整的类型定义
- **可定制**: 支持主题定制

**状态管理**: Zustand / Jotai

**理由**:
- **轻量级**: 相比Redux简单很多
- **TypeScript友好**: 类型推导完善
- **无样板代码**: 减少冗余代码
- **灵活**: 支持中间件和持久化

**数据可视化**: Recharts / ECharts

**理由**:
- **图表丰富**: 折线图、柱状图、饼图等
- **实时更新**: 适合展示Agent状态指标
- **交互友好**: 支持缩放、tooltip等

**实时通信**: Socket.IO Client

**理由**:
- **自动重连**: 断线自动重连
- **房间管理**: 支持多Agent隔离
- **兼容性好**: 浏览器和Node.js通用

**关键依赖**:
```json
{
  "react": "^18.2.0",
  "typescript": "^5.0.0",
  "vite": "^5.0.0",
  "antd": "^5.0.0",
  "zustand": "^4.4.0",
  "recharts": "^2.10.0",
  "socket.io-client": "^4.6.0",
  "axios": "^1.6.0",
  "react-router-dom": "^6.20.0",
  "tailwindcss": "^3.4.0",
  "@tanstack/react-query": "^5.0.0"
}
```

#### 3.3 配置管理
**决策**: YAML + Pydantic

**理由**:
- **可读性**: YAML格式清晰，易于编辑
- **验证**: Pydantic提供类型校验和默认值
- **IDE支持**: 可生成类型提示，提升开发体验

```yaml
# agent.yaml
agent:
  name: "my-agent"
  llm:
    provider: "openai"
    model: "gpt-4"
    api_key: "${OPENAI_API_KEY}"
  memory:
    short_term: "memory"
    long_term: "chromadb"
  tools:
    - "file_ops"
    - "web_search"
```

#### 3.4 向量数据库
**决策**: 支持多后端（ChromaDB / FAISS / Qdrant）

**理由**:
- **灵活性**: 用户可根据需求选择
- **轻量级**: ChromaDB和FAISS均可本地运行
- **性能**: FAISS为纯内存，性能最佳；ChromaDB支持持久化

**接口统一**:
```python
class VectorDB(ABC):
    @abstractmethod
    async def add(self, embeddings: np.ndarray, metadata: dict):
        """添加向量"""

    @abstractmethod
    async def search(self, query: np.ndarray, top_k: int) -> List[Result]:
        """向量搜索"""
```

#### 3.5 日志系统
**决策**: structlog + 日志轮转

**理由**:
- **结构化日志**: JSON格式，便于解析和分析
- **上下文追踪**: 支持绑定请求ID、任务ID等
- **可观测性**: 易于接入ELK、Loki等日志平台

#### 3.6 依赖注入
**决策**: 轻量级DI容器（dependency-injector）

**理由**:
- **解耦**: 降低组件间依赖
- **测试**: 便于Mock和单元测试
- **灵活性**: 支持配置化组件替换

### 4. 项目结构：前后端分离

```
magi/
├── backend/                     # Python后端
│   ├── src/
│   │   ├── magi/              # 框架核心包
│   │   │   ├── __init__.py
│   │   │   ├── core/          # 核心层
│   │   │   │   ├── agent.py  # Agent核心
│   │   │   │   ├── loop.py   # 循环引擎
│   │   │   │   └── state.py  # 状态管理
│   │   │   ├── awareness/     # 自感知模块
│   │   │   │   ├── perception.py    # 感知模块
│   │   │   │   ├── sensors/          # 内置感知器
│   │   │   │   │   ├── user_message.py
│   │   │   │   │   ├── sensor_data.py
│   │   │   │   │   ├── camera.py
│   │   │   │   │   └── microphone.py
│   │   │   │   └── base.py           # 感知器基类
│   │   │   ├── processing/    # 自处理模块
│   │   │   │   ├── processor.py      # 处理模块
│   │   │   │   ├── capability_store.py  # 能力仓库
│   │   │   │   └── human_interface.py   # 人工交互
│   │   │   ├── plugins/       # 插件系统
│   │   │   │   ├── base.py
│   │   │   │   ├── loader.py
│   │   │   │   └── manager.py
│   │   │   ├── tools/         # 工具系统
│   │   │   │   ├── registry.py
│   │   │   │   └── builtin/
│   │   │   │       ├── file_ops.py
│   │   │   │       ├── http.py
│   │   │   │       └── code_interpreter.py
│   │   │   ├── memory/        # 记忆系统
│   │   │   │   ├── store.py
│   │   │   │   └── backends/
│   │   │   │       ├── memory.py
│   │   │   │       ├── chromadb.py
│   │   │   │       └── faiss.py
│   │   │   ├── llm/           # LLM适配器
│   │   │   │   ├── base.py
│   │   │   │   ├── openai.py
│   │   │   │   ├── anthropic.py
│   │   │   │   └── local.py
│   │   │   ├── events/        # 事件系统
│   │   │   │   ├── bus.py
│   │   │   │   └── events.py
│   │   │   └── config/        # 配置管理
│   │   │       ├── loader.py
│   │   │       └── models.py
│   │   │
│   │   ├── api/              # API层
│   │   │   ├── main.py       # FastAPI应用入口
│   │   │   ├── routes/       # REST API路由
│   │   │   │   ├── agents.py     # Agent管理API
│   │   │   │   ├── tasks.py      # 任务API
│   │   │   │   ├── tools.py      # 工具API
│   │   │   │   ├── memory.py     # 记忆API
│   │   │   │   └── metrics.py    # 指标API
│   │   │   ├── websocket/     # WebSocket处理
│   │   │   │   ├── manager.py    # WebSocket连接管理
│   │   │   │   └── handlers.py   # 事件推送处理器
│   │   │   ├── models/        # API数据模型
│   │   │   │   ├── requests.py   # 请求模型
│   │   │   │   └── responses.py  # 响应模型
│   │   │   └── middleware/    # 中间件
│   │   │       ├── auth.py       # 认证中间件
│   │   │       └── cors.py       # CORS中间件
│   │   │
│   │   ├── examples/         # 示例代码
│   │   │   ├── basic_agent.py
│   │   │   ├── custom_tool.py
│   │   │   └── web_agent.py
│   │   │
│   │   └── tests/            # 测试代码
│   │       ├── unit/
│   │       ├── integration/
│   │       └── fixtures/
│   │
│   ├── pyproject.toml        # Python项目配置
│   └── requirements.txt      # 依赖列表
│
├── frontend/                   # TypeScript前端
│   ├── src/
│   │   ├── components/       # React组件
│   │   │   ├── layout/       # 布局组件
│   │   │   │   ├── Header.tsx
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   └── MainLayout.tsx
│   │   │   │
│   │   │   ├── agents/       # Agent相关组件
│   │   │   │   ├── AgentList.tsx       # Agent列表
│   │   │   │   ├── AgentCard.tsx       # Agent卡片
│   │   │   │   ├── AgentMonitor.tsx    # Agent监控面板
│   │   │   │   └── AgentConfig.tsx     # Agent配置编辑器
│   │   │   │
│   │   │   ├── tasks/        # 任务相关组件
│   │   │   │   ├── TaskList.tsx        # 任务列表
│   │   │   │   ├── TaskDetail.tsx      # 任务详情
│   │   │   │   └── TaskTimeline.tsx    # 任务时间线
│   │   │   │
│   │   │   ├── memory/       # 记忆相关组件
│   │   │   │   ├── MemoryView.tsx      # 记忆查看器
│   │   │   │   ├── MemorySearch.tsx    # 记忆搜索
│   │   │   │   └── MemoryVisualize.tsx # 记忆可视化
│   │   │   │
│   │   │   ├── tools/        # 工具相关组件
│   │   │   │   ├── ToolRegistry.tsx    # 工具注册中心
│   │   │   │   └── ToolTest.tsx        # 工具测试
│   │   │   │
│   │   │   ├── logs/         # 日志相关组件
│   │   │   │   ├── LogStream.tsx       # 实时日志流
│   │   │   │   └── LogViewer.tsx       # 日志查看器
│   │   │   │
│   │   │   └── charts/       # 图表组件
│   │   │       ├── MetricsChart.tsx    # 指标图表
│   │   │       ├── PerformanceChart.tsx # 性能图表
│   │   │       └── TaskStats.tsx       # 任务统计
│   │   │
│   │   ├── pages/            # 页面组件
│   │   │   ├── Dashboard.tsx      # 仪表盘首页
│   │   │   ├── Agents.tsx         # Agent管理页
│   │   │   ├── Tasks.tsx          # 任务管理页
│   │   │   ├── Memory.tsx         # 记忆管理页
│   │   │   ├── Tools.tsx          # 工具管理页
│   │   │   ├── Settings.tsx       # 设置页
│   │   │   └── NotFound.tsx       # 404页
│   │   │
│   │   ├── api/              # API客户端
│   │   │   ├── client.ts           # Axios实例配置
│   │   │   ├── agents.ts           # Agent API
│   │   │   ├── tasks.ts            # Task API
│   │   │   ├── tools.ts            # Tool API
│   │   │   ├── memory.ts           # Memory API
│   │   │   └── websocket.ts        # WebSocket客户端
│   │   │
│   │   ├── hooks/            # React Hooks
│   │   │   ├── useAgents.ts        # Agent数据钩子
│   │   │   ├── useTasks.ts         # Task数据钩子
│   │   │   ├── useMetrics.ts       # 指标数据钩子
│   │   │   ├── useWebSocket.ts     # WebSocket钩子
│   │   │   └── useLogStream.ts     # 日志流钩子
│   │   │
│   │   ├── stores/           # 状态管理（Zustand）
│   │   │   ├── agentStore.ts       # Agent状态
│   │   │   ├── taskStore.ts        # Task状态
│   │   │   ├── uiStore.ts          # UI状态
│   │   │   └── userStore.ts        # 用户状态
│   │   │
│   │   ├── types/            # TypeScript类型定义
│   │   │   ├── agent.ts
│   │   │   ├── task.ts
│   │   │   ├── tool.ts
│   │   │   └── memory.ts
│   │   │
│   │   ├── utils/            # 工具函数
│   │   │   ├── formatters.ts       # 格式化函数
│   │   │   ├── validators.ts       # 验证函数
│   │   │   └── constants.ts        # 常量定义
│   │   │
│   │   ├── App.tsx          # 应用根组件
│   │   ├── main.tsx         # 应用入口
│   │   └── vite-env.d.ts    # Vite类型声明
│   │
│   ├── public/              # 静态资源
│   │   └── favicon.ico
│   │
│   ├── index.html           # HTML模板
│   ├── package.json         # 项目配置
│   ├── tsconfig.json        # TypeScript配置
│   ├── vite.config.ts       # Vite配置
│   ├── tailwind.config.js   # TailwindCSS配置
│   └── README.md            # 前端说明
│
├── configs/                  # 配置文件目录
│   ├── agent.yaml          # Agent示例配置
│   └── plugins/            # 插件配置
│
├── docs/                     # 文档
│   ├── api.md              # API文档
│   ├── architecture.md     # 架构文档
│   ├── plugins.md          # 插件开发指南
│   ├── ui.md               # UI使用指南
│   └── tutorials.md        # 教程
│
├── scripts/                  # 脚本工具
│   ├── dev.sh              # 开发环境启动脚本
│   ├── build.sh            # 构建脚本
│   └── deploy.sh           # 部署脚本
│
├── docker-compose.yml        # Docker编排文件
├── Dockerfile.backend        # 后端Dockerfile
├── Dockerfile.frontend       # 前端Dockerfile
├── .gitignore
├── README.md                 # 项目说明
└── LICENSE                   # 许可证
```

### 5. 前后端通信架构

#### 5.1 通信协议选择

**REST API**:
- 用于CRUD操作（创建、读取、更新、删除Agent、Task等）
- 请求-响应模式，适合数据查询和配置管理
- 自动生成OpenAPI文档

**WebSocket**:
- 用于实时数据推送（Agent状态更新、日志流、任务进度）
- 双向通信，支持服务器主动推送
- 基于Socket.IO，兼容性好

#### 5.2 API设计原则

**RESTful API规范**:
```python
# 资源命名（复数名词）
GET    /api/agents          # 获取Agent列表
POST   /api/agents          # 创建Agent
GET    /api/agents/{id}     # 获取Agent详情
PUT    /api/agents/{id}     # 更新Agent
DELETE /api/agents/{id}     # 删除Agent

# 嵌套资源
GET    /api/agents/{id}/tasks        # 获取Agent的任务列表
POST   /api/agents/{id}/tasks        # 创建任务
GET    /api/agents/{id}/metrics      # 获取Agent指标

# 动作资源
POST   /api/agents/{id}/start        # 启动Agent
POST   /api/agents/{id}/stop         # 停止Agent
POST   /api/tasks/{id}/retry         # 重试任务
```

**统一响应格式**:
```python
# 成功响应
{
  "success": true,
  "data": { ... },      # 实际数据
  "message": "操作成功"
}

# 错误响应
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "参数验证失败",
    "details": { ... }
  }
}
```

#### 5.3 核心API端点设计

**Agent管理API**:
```python
# 1. 获取Agent列表
GET /api/agents
Query Params: ?status=running&page=1&page_size=20
Response: {
  "items": [AgentSchema],
  "total": 100,
  "page": 1,
  "page_size": 20
}

# 2. 创建Agent
POST /api/agents
Body: {
  "name": "my-agent",
  "config": { ... },
  "description": "My first agent"
}
Response: AgentSchema

# 3. 获取Agent详情
GET /api/agents/{agent_id}
Response: AgentSchema（包含状态、任务统计等）

# 4. 启动Agent
POST /api/agents/{agent_id}/start
Response: { "agent_id": "...", "status": "running" }

# 5. 停止Agent
POST /api/agents/{agent_id}/stop
Response: { "agent_id": "...", "status": "stopped" }

# 6. 删除Agent
DELETE /api/agents/{agent_id}
Response: { "message": "Agent已删除" }
```

**任务管理API**:
```python
# 1. 获取任务列表
GET /api/agents/{agent_id}/tasks
Query Params: ?status=pending&sort=-created_at
Response: {
  "items": [TaskSchema],
  "total": 50
}

# 2. 创建任务
POST /api/agents/{agent_id}/tasks
Body: {
  "type": "user_query",
  "input": "帮我搜索最新AI新闻",
  "priority": "high"
}
Response: TaskSchema

# 3. 获取任务详情
GET /api/tasks/{task_id}
Response: TaskSchema（包含执行历史、结果等）

# 4. 重试失败任务
POST /api/tasks/{task_id}/retry
Response: TaskSchema
```

**工具管理API**:
```python
# 1. 获取可用工具列表
GET /api/tools
Response: [ToolSchema]

# 2. 获取工具详情
GET /api/tools/{tool_name}
Response: ToolSchema（包含参数schema、示例等）

# 3. 测试工具
POST /api/tools/{tool_name}/test
Body: { "params": { ... } }
Response: { "result": ..., "duration": 123 }
```

**记忆管理API**:
```python
# 1. 搜索记忆
GET /api/agents/{agent_id}/memories
Query Params: ?query=用户偏好&limit=10
Response: [MemorySchema]

# 2. 获取记忆详情
GET /api/memories/{memory_id}
Response: MemorySchema

# 3. 删除记忆
DELETE /api/memories/{memory_id}
Response: { "message": "记忆已删除" }
```

**指标监控API**:
```python
# 1. 获取Agent指标
GET /api/agents/{agent_id}/metrics
Query Params: ?from=2024-01-01&to=2024-01-31&interval=1h
Response: {
  "cpu_usage": [...],
  "memory_usage": [...],
  "task_count": [...],
  "error_rate": [...]
}

# 2. 获取实时状态
GET /api/agents/{agent_id}/status
Response: {
  "state": "RUNNING",
  "current_task": {...},
  "queue_size": 5,
  "uptime": 12345
}
```

#### 5.4 WebSocket事件设计

**客户端→服务器**:
```typescript
// 订阅Agent事件
socket.emit('subscribe', { agent_id: 'xxx' })

// 取消订阅
socket.emit('unsubscribe', { agent_id: 'xxx' })

// 发送命令
socket.emit('command', {
  agent_id: 'xxx',
  action: 'pause',  // pause/resume/restart
  params: {}
})
```

**服务器→客户端**:
```typescript
// Agent状态变化
socket.emit('agent:state_changed', {
  agent_id: 'xxx',
  old_state: 'IDLE',
  new_state: 'RUNNING',
  timestamp: 1234567890
})

// 任务状态更新
socket.emit('task:updated', {
  task_id: 'xxx',
  status: 'completed',
  result: {...}
})

// 新任务创建
socket.emit('task:created', {
  task: {...}
})

// 日志流
socket.emit('log:new', {
  level: 'INFO',
  message: '开始执行任务...',
  timestamp: 1234567890,
  context: { task_id: 'xxx' }
})

// 指标更新（实时）
socket.emit('metrics:updated', {
  cpu_usage: 45.2,
  memory_usage: 512,
  task_queue_size: 3
})

// 错误发生
socket.emit('error:occurred', {
  error_type: 'ToolExecutionError',
  message: '工具调用失败',
  context: { task_id: 'xxx', tool_name: 'search' }
})
```

#### 5.5 前端数据流设计

**数据获取策略**:
- **初始数据**: 页面加载时通过REST API获取
- **增量更新**: 通过WebSocket推送实时更新
- **定期同步**: WebSocket断线时降级为轮询（5秒间隔）

**状态管理模式**（Zustand）:
```typescript
// agentStore.ts
interface AgentStore {
  agents: Agent[]
  currentAgent: Agent | null
  metrics: Metric[]

  // Actions
  fetchAgents: () => Promise<void>
  createAgent: (config: AgentConfig) => Promise<Agent>
  startAgent: (id: string) => Promise<void>
  stopAgent: (id: string) => Promise<void>

  // WebSocket订阅
  subscribeToAgent: (id: string) => void
  unsubscribeFromAgent: (id: string) => void

  // 实时更新
  updateAgentState: (update: StateUpdate) => void
  appendLog: (log: LogEntry) => void
}
```

**React Query集成**:
```typescript
// 自动缓存、重试、刷新
const { data: agents, isLoading, error } = useQuery({
  queryKey: ['agents'],
  queryFn: api.agents.list,
  refetchInterval: 5000  // 轮询间隔（WebSocket断线时）
})
```

### 6. 前端核心页面设计

#### 6.1 Dashboard（仪表盘）
**布局**:
```
┌──────────────────────────────────────────────┐
│  Header: Logo | Agent切换 | 设置              │
├──────────────────────────────────────────────┤
│  ┌─────────────┐ ┌─────────────┐             │
│  │ 运行中Agent │ │ 总任务数    │             │
│  │    12       │ │   1,234     │             │
│  └─────────────┘ └─────────────┘             │
│                                              │
│  ┌──────────────────────────────────────┐   │
│  │     CPU/内存使用率趋势图（24小时）    │   │
│  └──────────────────────────────────────┘   │
│                                              │
│  ┌──────────────────┐  ┌─────────────────┐  │
│  │  最近任务列表     │  │  实时日志流     │  │
│  └──────────────────┘  └─────────────────┘  │
└──────────────────────────────────────────────┘
```

**功能**:
- 展示所有Agent的整体状态
- 关键指标卡片（运行中/总数/成功率）
- 资源使用趋势图
- 最近任务列表
- 实时日志流（最新10条）

#### 6.2 Agent监控页面
**布局**:
```
┌──────────────────────────────────────────────┐
│  ← 返回 | Agent: my-agent | [启动] [停止]    │
├──────────────────────────────────────────────┤
│  状态: 🟢 RUNNING | 运行时间: 2h 30m         │
│                                              │
│  ┌────────────────────────────────────────┐ │
│  │  任务队列 (5)                          │ │
│  │  ├─ [pending] 搜索AI新闻               │ │
│  │  ├─ [running] 分析文章内容             │ │
│  │  └─ [pending] 生成总结报告             │ │
│  └────────────────────────────────────────┘ │
│                                              │
│  ┌────────────────────────────────────────┐ │
│  │  循环状态可视化（Sense-Plan-Act-Reflect）│ │
│  │  ┌────┐   ┌────┐   ┌────┐   ┌────┐    │ │
│  │  │Sense│ → │Plan│ → │ Act│ → │Refl│    │ │
│  │  └────┘   └────┘   └────┘   └────┘    │ │
│  │    ✓        ✓        ✓        ✓       │ │
│  └────────────────────────────────────────┘ │
│                                              │
│  ┌────────────────────────────────────────┐ │
│  │  性能指标（实时图表）                   │ │
│  │  CPU: 45% | 内存: 512MB | 任务/分钟: 12│ │
│  └────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```

**功能**:
- 实时展示Agent运行状态
- 任务队列可视化
- Sense-Plan-Act-Reflect循环状态动画
- 实时性能指标图表
- 启动/停止/重启控制

#### 6.3 任务管理页面
**功能**:
- 任务列表（分页、筛选、排序）
- 任务详情（输入、输出、执行历史）
- 任务时间线（可视化执行流程）
- 批量操作（重试、取消、删除）

#### 6.4 记忆可视化页面
**功能**:
- 记忆搜索（语义搜索）
- 记忆详情查看
- 记忆关系图（向量相似度可视化）
- 记忆管理（删除、导出）

#### 6.5 工具管理页面
**功能**:
- 工具注册中心（查看所有可用工具）
- 工具测试界面（手动调用工具）
- 工具权限管理
- 自定义工具上传（未来）

### 7. 开发和部署

#### 7.1 开发环境

**后端开发**:
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn src.api.main:app --reload --port 8000
```

**前端开发**:
```bash
cd frontend
npm install
npm run dev  # http://localhost:5173
```

**一键启动**（docker-compose）:
```bash
docker-compose up
```

#### 7.2 生产部署

**Docker部署**:
```yaml
# docker-compose.yml
version: '3.8'
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile.backend
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://...
      - REDIS_URL=redis://redis:6379
    volumes:
      - ./data:/app/data

  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports:
      - "80:80"
    depends_on:
      - backend

  chromadb:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
    volumes:
      - chromadb_data:/chroma/chroma

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

**单机部署**:
```bash
# 构建前端
cd frontend && npm run build

# 启动后端（Nginx服务静态文件）
cd backend && gunicorn src.api.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

### 8. 核心流程设计

#### 5.1 Agent启动流程
```
1. 加载配置文件
2. 初始化日志系统
3. 创建依赖注入容器
4. 初始化各组件（记忆、工具、LLM适配器）
5. 注册工具到注册中心
6. 启动消息总线
7. 启动自感知模块
8. 启动自处理模块
9. 启动循环引擎
10. 发布AgentStarted事件
```

#### 5.2 任务执行流程
```
LoopEngine.sense():
  → 收集当前状态（自感知模块）
  → 获取待处理任务队列
  → 检查资源可用性

LoopEngine.plan():
  → LLM决策下一步行动
  → 选择合适的工具
  → 生成工具调用参数

LoopEngine.act():
  → 从ToolRegistry获取工具
  → 执行工具调用
  → 捕获执行结果

LoopEngine.reflect():
  → 更新记忆（存储结果）
  → 评估任务完成度
  → 触发后续任务或结束循环
```

#### 5.3 能力沉淀流程
```
1. 感知输入到达
2. 查找已有处理能力（CapabilityStore.find）
3. 找到匹配能力?
   - Yes → 自动执行 → 更新成功率
   - No  → 决策处理方式（人类/LLM）
4. 执行处理动作
5. 评估执行结果
6. 沉淀为新的能力（CapabilityStore.save）
7. 存储经验到记忆
```

### 6. 扩展点设计

框架提供以下扩展点：

1. **自定义Tool**: 继承`Tool`基类，实现业务逻辑
2. **自定义Sensor**: 继承`Sensor`基类，实现新的感知器（如GPS、加速度计等）
3. **自定义MemoryBackend**: 实现自定义存储后端（如Redis、MongoDB）
4. **自定义LLMAdapter**: 接入新的LLM提供商
5. **自定义LoopStrategy**: 实现特殊的循环策略
6. **自定义能力匹配算法**: 实现更智能的能力检索策略
7. **自定义Human Interface**: 实现新的人工交互方式（如CLI、邮件等）
8. **事件处理器**: 订阅消息总线事件，实现自定义逻辑

### 7. 安全性考虑

#### 7.1 工具权限控制
- 每个工具声明所需权限（如`file.read`、`network.request`）
- Agent启动时检查工具权限，超出范围则拒绝加载
- 支持权限白名单/黑名单配置

#### 7.2 敏感信息保护
- API密钥通过环境变量注入，不硬编码
- 支持密钥加密存储（可选）
- 日志中自动脱敏敏感信息

#### 7.3 代码执行沙箱
- 代码解释器工具运行在受限环境（Docker容器或subprocess）
- 限制文件系统访问路径
- 设置执行超时和资源限制

## Risks / Trade-offs

### 风险1: LLM响应延迟影响自循环性能
**影响**: 如果LLM API调用缓慢，整个循环会阻塞
**缓解措施**:
- 支持流式响应，提前开始处理
- 本地缓存常见决策，减少LLM调用
- 提供本地LLM适配器（如Llama.cpp）

### 风险2: 插件质量参差不齐
**影响**: 第三方插件可能不稳定或有安全漏洞
**缓解措施**:
- 提供插件开发规范和最佳实践文档
- 实现插件评分和反馈机制
- 支持插件沙箱隔离
- 提供官方插件认证（未来）

### 风险3: 记忆存储占用过高
**影响**: 长期运行后记忆数据可能占用大量存储空间
**缓解措施**:
- 实现记忆过期策略（TTL）
- 支持记忆压缩和归档
- 提供记忆清理工具

### 风险4: 自循环陷入无限循环
**影响**: Agent可能陷入重复执行相同任务的死循环
**缓解措施**:
- 实现最大循环次数限制
- 检测重复任务模式
- 自感知模块监控循环健康度
- 支持手动干预和停止

### 权衡1: 灵活性 vs 简单性
**决策**: 优先保证灵活性，提供清晰的默认配置
**理由**: Agent应用场景多样，框架需要支持定制化
**代价**: 学习曲线略陡，但提供详细文档和示例

### 权衡2: 性能 vs 可观测性
**决策**: 适度的监控开销，生产环境可调节日志级别
**理由**: 可观测性对调试和维护至关重要
**代价**: 约5-10%性能开销，可接受

### 权衡3: 功能完整性 vs 快速交付
**决策**: MVP包含核心功能，高级特性分阶段实现
**理由**:
- MVP: 自循环、基础工具、记忆存储
- v0.2: 高级恢复策略、分布式支持
- v0.3: Web UI、多Agent协作

## Migration Plan

### 阶段1: 框架基础设施（Week 1-2）
**后端**:
- [ ] 搭建项目结构（backend/frontend分离）
- [ ] 实现配置管理系统
- [ ] 实现消息总线
- [ ] 实现结构化日志系统
- [ ] 编写单元测试框架

**前端**:
- [ ] 初始化Vite + React + TypeScript项目
- [ ] 配置TailwindCSS和Ant Design
- [ ] 搭建基础布局（Header、Sidebar、路由）
- [ ] 配置Zustand状态管理
- [ ] 配置Axios和API客户端

### 阶段2: 核心组件开发（Week 3-4）
**后端**:
- [ ] 实现Agent核心类
- [ ] 实现LoopEngine（Sense-Plan-Act-Reflect）
- [ ] 实现Tool Registry和基础工具
- [ ] 实现Memory Store（内存后端）
- [ ] 实现LLM适配器（OpenAI）

**前端**:
- [ ] 实现Agent列表和详情页面
- [ ] 实现Agent监控面板（实时状态展示）
- [ ] 集成Recharts图表组件
- [ ] 实现WebSocket客户端和实时更新

### 阶段3: API和通信（Week 5）
**后端**:
- [ ] 实现FastAPI应用和路由
- [ ] 实现RESTful API（Agents、Tasks、Tools、Memory）
- [ ] 实现WebSocket服务器
- [ ] 实现事件推送机制
- [ ] 编写API文档（自动生成OpenAPI）

**前端**:
- [ ] 实现所有API调用函数
- [ ] 实现WebSocket订阅和数据同步
- [ ] 实现任务管理页面
- [ ] 实现工具管理页面

### 阶段4: 扩展性和智能化（Week 6-7）
**后端**:
- [ ] 实现插件系统
- [ ] 实现自感知模块（指标收集）
- [ ] 实现自处理模块（恢复策略）
- [ ] 添加向量数据库后端（ChromaDB）
- [ ] 实现记忆管理API

**前端**:
- [ ] 实现记忆可视化页面
- [ ] 实现记忆搜索功能
- [ ] 实现性能指标图表（CPU、内存、任务）
- [ ] 实现实时日志流组件
- [ ] 实现配置编辑器（Monaco Editor）

### 阶段5: 测试和文档（Week 8-9）
**后端**:
- [ ] 完善单元测试和集成测试
- [ ] API测试和性能测试
- [ ] 编写API使用文档
- [ ] 编写插件开发指南

**前端**:
- [ ] 组件测试（React Testing Library）
- [ ] E2E测试（Playwright）
- [ ] UI优化和响应式适配
- [ ] 编写UI使用手册

### 阶段6: 部署和发布（Week 10）
**DevOps**:
- [ ] 编写Dockerfile（backend/frontend）
- [ ] 配置docker-compose编排
- [ ] 准备生产环境配置
- [ ] 编写部署文档
- [ ] 准备v0.1.0发布

### 回滚策略
- 使用Git分支管理，每个阶段独立分支
- 发现重大问题可回退到上一稳定版本
- 保持向后兼容的API设计

## Open Questions

1. **LLM调用策略**: Agent是否支持多LLM并行调用（如同时使用GPT-4和本地模型）？
   - **倾向**: MVP支持单LLM配置，v0.2支持多LLM路由

2. **任务调度粒度**: LoopEngine每次循环处理一个任务还是一批任务？
   - **倾向**: 由LoopStrategy配置决定，STEP模式单任务，WAVE模式批量

3. **记忆检索策略**: 如何平衡召回率和精度？
   - **倾向**: 默认混合检索（向量+关键词），支持自定义检索器

4. **插件隔离**: 是否需要Docker级别的插件隔离？
   - **倾向**: MVP使用进程隔离，v0.2考虑容器隔离（可选）

5. **配置热更新**: Agent运行时是否支持配置动态更新？
   - **倾向**: 不支持，需重启Agent（简化设计）

6. **分布式部署**: 未来是否支持多机器分布式运行？
   - **倾向**: MVP仅单机，设计时保留扩展接口

7. **WebSocket认证**: WebSocket连接是否需要认证？
   - **倾向**: MVP不需要（本地使用），v0.2添加JWT token认证

8. **前端多语言**: 是否需要支持国际化（i18n）？
   - **倾向**: MVP仅中文，v0.2添加英文支持

9. **数据持久化**: Agent配置和记忆是否需要持久化到数据库？
   - **倾向**: MVP使用文件存储（YAML + JSON），v0.2支持SQLite/PostgreSQL

10. **实时性能**: WebSocket推送频率如何控制？
    - **倾向**: 指标更新1秒间隔，日志流实时推送，前端可配置节流
