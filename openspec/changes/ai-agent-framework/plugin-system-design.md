# Plugin System & Tool Registry 完整设计

## 1. 插件系统 (Plugin System)

### 核心概念

- **插件 = 统一的扩展机制**
- **工具 = 插件提供的一种能力**
- **对外工具 = Skills**（用户可见，可调用）
- **对内工具 = Internal Tools**（用户不可见，Agent内部使用）

### 插件分类

```
插件系统
    ├── ToolPlugin（工具插件）
    │   ├── 对外工具 - Skills
    │   │   ├── 网页搜索
    │   │   ├── 发送邮件
    │   │   ├── 文件操作
    │   │   └── API调用
    │   │
    │   └── 对内工具 - Internal Tools
    │       ├── 记忆检索
    │       ├── 日志记录
    │       ├── 状态查询
    │       └── 能力匹配
    │
    ├── StoragePlugin（存储插件）
    │   ├── SQLite后端
    │   ├── ChromaDB后端
    │   └── Redis后端
    │
    ├── LLMPlugin（LLM适配器）
    │   ├── OpenAI
    │   ├── Anthropic
    │   └── 本地模型
    │
    └── SensorPlugin（感知器）
        ├── 摄像头
        ├── 麦克风
        └── 传感器数据
```

---

### 1.1 插件基类设计

```python
from abc import ABC, abstractmethod
from typing import List, Optional, Callable, Dict, Any
from enum import Enum

class Plugin(ABC):
    """插件基类 - 生命周期钩子 + 事件订阅"""

    # ========== 插件元数据 ==========
    @property
    @abstractmethod
    def name(self) -> str:
        """插件名称"""
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """插件版本"""
        pass

    @property
    def description(self) -> str:
        """插件描述"""
        return ""

    # 优先级（用于排序）
    priority: int = 0

    # 依赖关系
    dependencies: List[str] = []   # 依赖的插件列表
    run_after: List[str] = []      # 在这些插件之后运行
    run_before: List[str] = []     # 在这些插件之前运行

    # ========== 生命周期钩子 ==========

    # Agent级别
    async def on_agent_start(self):
        """Agent启动时"""
        pass

    async def on_agent_stop(self):
        """Agent停止时"""
        pass

    # Sense阶段钩子（Chain模式）
    async def before_sense(self, context: SenseContext):
        """感知前钩子
        用途：
        - 过滤/增强感知输入
        - 添加自定义感知器
        """
        pass

    async def after_sense(self, perceptions: List[Perception]):
        """感知后钩子
        用途：
        - 聚合/过滤感知结果
        - 触发感知响应
        """
        pass

    # Plan阶段钩子（Chain模式）
    async def before_plan(self, perception: Perception):
        """决策前钩子
        用途：
        - 提供决策建议
        - 检查是否有历史经验
        """
        pass

    async def after_plan(self, action: Action):
        """决策后钩子
        用途：
        - 验证/修改决策
        - 记录决策日志
        """
        pass

    # Act阶段钩子（Chain模式）
    async def before_act(self, action: Action):
        """执行前钩子
        用途：
        - 权限检查
        - 参数验证/增强
        - 审计日志
        """
        pass

    async def after_act(self, result: ActionResult):
        """执行后钩子（Parallel模式）
        用途：
        - 结果后处理
        - 通知/告警
        - 触发后续动作
        """
        pass

    # Reflect阶段钩子
    async def before_reflect(self, perception, action, result):
        """反思前钩子"""
        pass

    async def after_reflect(self, experience: Experience):
        """反思后钩子
        用途：
        - 经验总结
        - 能力沉淀
        """
        pass

    # 错误钩子
    async def on_error(self, error: Exception, context: dict):
        """错误发生时"""
        pass

    # ========== 插件提供的扩展 ==========

    def get_tools(self) -> List['Tool']:
        """获取插件提供的工具（默认空）"""
        return []

    def get_storage_backend(self) -> Optional['StorageBackend']:
        """获取存储后端（默认空）"""
        return None

    def get_llm_adapter(self) -> Optional['LLMAdapter']:
        """获取LLM适配器（默认空）"""
        return None

    def get_sensors(self) -> List['Sensor']:
        """获取感知器（默认空）"""
        return []

    # ========== 加载/卸载 ==========

    async def load(self):
        """加载插件"""
        pass

    async def unload(self):
        """卸载插件"""
        pass
```

---

### 1.2 钩子执行策略

#### Chain模式（链式执行）

```python
class HookExecutor:
    """钩子执行器"""

    async def execute_chain(
        self,
        hook_name: str,
        data: Any,
        plugins: List[Plugin],
        stop_on_error: bool = False
    ) -> Any:
        """链式执行 - 每个插件的输出作为下一个的输入"""

        result = data
        for plugin in plugins:
            if hasattr(plugin, hook_name):
                try:
                    result = await getattr(plugin, hook_name)(result)
                    # 返回None则中断链
                    if result is None:
                        logger.debug(f"插件 {plugin.name} 中断了钩子链")
                        break
                except Exception as e:
                    logger.error(f"插件 {plugin.name} 执行失败: {e}")
                    if stop_on_error:
                        raise

        return result
```

**适用场景**：
- `before_sense`: 过滤/增强感知输入
- `before_plan`: 提供决策建议
- `before_act`: 权限检查、参数验证

#### Parallel模式（并行执行）

```python
async def execute_parallel(
    self,
    hook_name: str,
    data: Any,
    plugins: List[Plugin],
    stop_on_error: bool = False
) -> List[Any]:
    """并行执行 - 所有插件并行执行，互不影响"""

    tasks = []
    for plugin in plugins:
        if hasattr(plugin, hook_name):
            tasks.append(getattr(plugin, hook_name)(data))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 处理异常
    processed_results = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            plugin_name = plugins[i].name
            logger.error(f"插件 {plugin_name} 执行失败: {result}")
            if stop_on_error:
                raise result
        else:
            processed_results.append(result)

    return processed_results
```

**适用场景**：
- `after_act`: 结果后处理、通知、日志
- `after_reflect`: 经验总结、能力沉淀
- `after_sense`: 聚合感知结果

#### 钩子配置

```python
HOOK_CONFIGS = {
    # Chain模式 - 需要顺序执行
    "before_sense": {"mode": "chain", "stop_on_error": False},
    "before_plan": {"mode": "chain", "stop_on_error": False},
    "before_act": {"mode": "chain", "stop_on_error": True},   # 权限检查失败要停止
    "before_reflect": {"mode": "chain", "stop_on_error": False},

    # Parallel模式 - 可并行执行
    "after_sense": {"mode": "parallel", "stop_on_error": False},
    "after_act": {"mode": "parallel", "stop_on_error": False},
    "after_reflect": {"mode": "parallel", "stop_on_error": False},
    "on_error": {"mode": "parallel", "stop_on_error": False},
}
```

---

### 1.3 多插件依赖处理

```python
async def _sort_plugins_by_priority(self, plugins: List[Plugin]) -> List[Plugin]:
    """按依赖关系和优先级排序插件"""

    # 1. 拓扑排序（处理依赖）
    sorted_plugins = self._topological_sort(plugins)

    # 2. 按run_after/run_before调整
    sorted_plugins = self._adjust_by_order_constraints(sorted_plugins)

    # 3. 按priority排序（同优先级保持依赖顺序）
    sorted_plugins.sort(key=lambda p: p.priority, reverse=True)

    return sorted_plugins


def _topological_sort(self, plugins: List[Plugin]) -> List[Plugin]:
    """拓扑排序处理依赖关系"""

    plugin_map = {p.name: p for p in plugins}
    in_degree = {p.name: 0 for p in plugins}
    graph = {p.name: [] for p in plugins}

    # 构建依赖图
    for plugin in plugins:
        for dep in plugin.dependencies:
            if dep in plugin_map:
                graph[dep].append(plugin.name)
                in_degree[plugin.name] += 1

    # Kahn算法
    queue = [name for name, degree in in_degree.items() if degree == 0]
    result = []

    while queue:
        name = queue.pop(0)
        result.append(plugin_map[name])

        for neighbor in graph[name]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) != len(plugins):
        raise ValueError("插件依赖关系存在循环")

    return result


def _adjust_by_order_constraints(self, plugins: List[Plugin]) -> List[Plugin]:
    """按run_after/run_before调整顺序"""

    # 简化实现：多次迭代调整
    max_iterations = len(plugins) * len(plugins)
    for _ in range(max_iterations):
        changed = False

        for i, plugin in enumerate(plugins):
            for after_name in plugin.run_after:
                if after_name in [p.name for p in plugins[:i]]:
                    # 需要移到后面
                    plugins.insert(i+1, plugins.pop(i))
                    changed = True
                    break

            for before_name in plugin.run_before:
                if before_name in [p.name for p in plugins[i+1:]]:
                    # 需要移到前面
                    plugins.insert(max(0, i-1), plugins.pop(i))
                    changed = True
                    break

        if not changed:
            break

    return plugins
```

---

### 1.4 工具定义

```python
from dataclasses import dataclass
from typing import Dict, List, Any

class Tool(ABC):
    """工具基类"""

    name: str
    description: str
    is_internal: bool = False  # True=对内工具，False=对外工具（Skill）

    @abstractmethod
    async def execute(self, params: dict) -> 'ToolResult':
        """执行工具逻辑"""
        pass

    @property
    def schema(self) -> dict:
        """返回工具的参数schema（JSON Schema）"""
        return {
            "type": "object",
            "properties": {},
            "required": []
        }

    @property
    def permissions(self) -> List[str]:
        """所需权限列表"""
        return []

    @property
    def scenario_tags(self) -> List[str]:
        """场景标签（用于工具匹配）"""
        return []  # 如["information_retrieval", "communication"]


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict = None


# 对外工具示例（Skill）
class WebSearchSkill(Tool):
    """网页搜索技能 - 对外"""

    name = "web_search"
    description = "搜索网页获取最新信息"
    is_internal = False

    def __init__(self, search_engine):
        self.search_engine = search_engine

    async def execute(self, params: dict) -> ToolResult:
        try:
            results = await self.search_engine.search(
                params["query"],
                num_results=params.get("num_results", 5)
            )
            return ToolResult(success=True, data=results)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    @property
    def schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词"
                },
                "num_results": {
                    "type": "integer",
                    "default": 5,
                    "description": "返回结果数量"
                }
            },
            "required": ["query"]
        }

    @property
    def permissions(self) -> List[str]:
        return ["network.request"]

    @property
    def scenario_tags(self) -> List[str]:
        return ["information_retrieval"]


# 对内工具示例
class MemoryRetrieveTool(Tool):
    """记忆检索工具 - 对内"""

    name = "memory_retrieve"
    description = "从记忆中检索相关信息"
    is_internal = True  # 对外不可见

    def __init__(self, memory_store):
        self.memory_store = memory_store

    async def execute(self, params: dict) -> ToolResult:
        try:
            memories = await self.memory_store.recall(
                query=params["query"],
                top_k=params.get("top_k", 5)
            )
            return ToolResult(success=True, data=memories)
        except Exception as e:
            return ToolResult(success=False, error=str(e))


# 邮件插件示例（提供多个工具）
class EmailToolPlugin(ToolPlugin):
    """邮件工具插件"""

    name = "email_tools"
    version = "1.0.0"
    description = "提供邮件收发功能"
    priority = 10

    def get_tools(self) -> List[Tool]:
        return [
            # 对外工具（Skills）
            SendEmailSkill(),      # 用户可见
            ReadEmailSkill(),      # 用户可见
            SearchEmailSkill(),    # 用户可见

            # 对内工具
            EmailSyncTool(),       # 后台同步邮件（内部）
        ]
```

---

## 2. 工具注册与决策系统

### 2.1 决策系统架构

```
感知输入
    ↓
【决策引擎】5步流程
    1. 场景分类（什么场景？）
    2. 意图理解（想做什么？）
    3. 能力匹配（有哪些工具可用？）
    4. 工具评估（哪个工具最合适？）
    5. 参数生成（生成工具调用参数）
    ↓
执行计划（单工具/多工具组合）
```

---

### 2.2 场景分类器

```python
from typing import Dict

class ScenarioClassifier:
    """场景分类器"""

    SCENARIOS = {
        "information_retrieval": "信息检索",
        "communication": "沟通交互",
        "task_execution": "任务执行",
        "data_analysis": "数据分析",
        "creative_work": "创作工作",
        "file_management": "文件管理",
    }

    def __init__(self, llm: LLMAdapter):
        self.llm = llm

    async def classify(self, perception: Perception) -> str:
        """分类感知输入属于哪个场景"""

        prompt = f"""
        感知输入：{perception.data}

        请分类属于以下哪个场景：
        {self.SCENARIOS}

        只返回场景名称（如information_retrieval）。
        """

        scenario = await self.llm.generate(prompt)
        return scenario.strip()
```

---

### 2.3 意图提取器

```python
@dataclass
class Intent:
    """意图"""
    action: str        # 主要动作（动词）
    object: str        # 目标对象（名词）
    constraints: Dict  # 约束条件
    text: str          # 原始文本

    @classmethod
    def parse(cls, data: str) -> 'Intent':
        """从LLM输出解析"""
        import json
        parsed = json.loads(data)
        return cls(**parsed)


class IntentExtractor:
    """意图提取器"""

    def __init__(self, llm: LLMAdapter):
        self.llm = llm

    async def extract(self, perception: Perception) -> Intent:
        """提取用户意图"""

        prompt = f"""
        用户输入：{perception.data}

        请提取：
        1. 主要意图（动词）
        2. 目标对象（名词）
        3. 约束条件

        格式：JSON
        {{
            "action": "搜索",
            "object": "网页",
            "constraints": {{"num_results": 5}},
            "text": "搜索最新AI新闻"
        }}
        """

        intent_data = await self.llm.generate(prompt)
        return Intent.parse(intent_data)
```

---

### 2.4 能力匹配器

```python
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

class CapabilityMatcher:
    """能力匹配器"""

    def __init__(
        self,
        tool_registry: 'ToolRegistry',
        embedder: 'EmbeddingModel'
    ):
        self.tool_registry = tool_registry
        self.embedder = embedder

    async def match_tools(
        self,
        intent: Intent,
        scenario: str
    ) -> List[Tool]:
        """匹配可用工具"""

        # 1. 基于场景过滤
        scenario_tools = self.tool_registry.get_by_scenario(scenario)

        if not scenario_tools:
            # 如果没有匹配场景的工具，返回所有工具
            scenario_tools = self.tool_registry.list_public()

        # 2. 基于意图匹配（语义相似度）
        matches = []
        for tool in scenario_tools:
            similarity = self.compute_similarity(intent, tool)
            if similarity > 0.7:  # 阈值
                matches.append((tool, similarity))

        # 3. 按相似度排序
        matches.sort(key=lambda x: x[1], reverse=True)

        return [tool for tool, _ in matches[:5]]  # 返回Top5

    def compute_similarity(self, intent: Intent, tool: Tool) -> float:
        """计算意图和工具的语义相似度"""

        # 意图文本
        intent_text = f"{intent.action} {intent.object}"

        # 工具描述
        tool_desc = tool.description

        # 向量嵌入
        intent_embedding = self.embedder.embed(intent_text)
        tool_embedding = self.embedder.embed(tool_desc)

        # 余弦相似度
        similarity = cosine_similarity(
            [intent_embedding],
            [tool_embedding]
        )[0][0]

        return float(similarity)
```

---

### 2.5 工具评估器

```python
class ToolEvaluator:
    """工具评估器"""

    def __init__(
        self,
        capability_matcher: CapabilityMatcher,
        tool_history: 'ToolHistory',
        permission_checker: 'PermissionChecker',
        context_relevancy: 'ContextRelevancy'
    ):
        self.capability_matcher = capability_matcher
        self.tool_history = tool_history
        self.permission_checker = permission_checker
        self.context_relevancy = context_relevancy

    async def evaluate(
        self,
        tool: Tool,
        perception: Perception,
        intent: Intent,
        scenario: str
    ) -> float:
        """评估工具适配度（0-1）"""

        score = 0.0

        # 因素1: 语义匹配度（40%）
        semantic_score = self.capability_matcher.compute_similarity(
            intent, tool
        )
        score += semantic_score * 0.4

        # 因素2: 历史成功率（30%）
        history = await self.tool_history.get_stats(tool.name)
        success_rate = history.get("success_rate", 0.5)
        score += success_rate * 0.3

        # 因素3: 权限检查（20%）
        if await self.permission_checker.check(tool, perception):
            score += 0.2

        # 因素4: 上下文相关性（10%）
        context_score = await self.context_relevancy.check(tool, perception)
        score += context_score * 0.1

        return min(score, 1.0)
```

---

### 2.6 参数生成器

```python
class ToolParameterGenerator:
    """工具参数生成器"""

    def __init__(self, llm: LLMAdapter):
        self.llm = llm

    async def generate(
        self,
        tool: Tool,
        perception: Perception,
        intent: Intent
    ) -> dict:
        """生成工具调用参数"""

        # 1. 从perception中提取参数
        extracted_params = await self.extract_from_perception(
            tool.schema, perception
        )

        # 2. 用LLM补全缺失参数
        prompt = f"""
        工具：{tool.name}
        工具描述：{tool.description}

        参数schema：{tool.schema}

        已提取参数：{extracted_params}

        感知输入：{perception.data}
        意图：{intent.action} {intent.object}

        请生成完整的工具调用参数（JSON格式）。
        只返回JSON，不要其他内容。
        """

        params_str = await self.llm.generate(prompt)
        params = json.loads(params_str)

        # 3. 参数验证
        validated = self.validate_params(tool.schema, params)

        return validated

    async def extract_from_perception(
        self,
        schema: dict,
        perception: Perception
    ) -> dict:
        """从感知输入中提取参数"""
        # 简化实现：正则/规则提取
        # 实际可以用LLM提取
        return {}

    def validate_params(self, schema: dict, params: dict) -> dict:
        """验证参数"""
        # JSON Schema验证
        from jsonschema import validate, ValidationError

        try:
            validate(instance=params, schema=schema)
            return params
        except ValidationError as e:
            logger.warning(f"参数验证失败: {e}")
            # 返回默认值或修正后的参数
            return self.fix_params(schema, params)

    def fix_params(self, schema: dict, params: dict) -> dict:
        """修正参数（使用默认值）"""
        fixed = {}
        for prop_name, prop_schema in schema.get("properties", {}).items():
            if prop_name in params:
                fixed[prop_name] = params[prop_name]
            elif "default" in prop_schema:
                fixed[prop_name] = prop_schema["default"]
        return fixed
```

---

### 2.7 决策引擎

```python
@dataclass
class ToolSelection:
    """工具选择结果"""
    tool: Tool                    # 选中的工具
    params: dict                  # 工具参数
    confidence: float             # 置信度（0-1）
    alternatives: List[Tool]      # 备选工具
    scenario: str                 # 场景
    intent: Intent                # 意图


class ToolDecisionEngine:
    """工具决策引擎"""

    def __init__(self, llm: LLMAdapter, tool_registry: 'ToolRegistry'):
        # 初始化各个组件
        self.scenario_classifier = ScenarioClassifier(llm)
        self.intent_extractor = IntentExtractor(llm)
        self.capability_matcher = CapabilityMatcher(
            tool_registry, EmbeddingModel()
        )
        self.tool_evaluator = ToolEvaluator(
            self.capability_matcher,
            ToolHistory(),
            PermissionChecker(),
            ContextRelevancy()
        )
        self.param_generator = ToolParameterGenerator(llm)

    async def decide(self, perception: Perception) -> ToolSelection:
        """决策选择工具（5步流程）"""

        # 1. 场景分类
        scenario = await self.scenario_classifier.classify(perception)
        logger.info(f"场景分类: {scenario}")

        # 2. 意图理解
        intent = await self.intent_extractor.extract(perception)
        logger.info(f"意图提取: {intent}")

        # 3. 匹配可用工具
        candidate_tools = await self.capability_matcher.match_tools(
            intent, scenario
        )
        logger.info(f"候选工具: {[t.name for t in candidate_tools]}")

        if not candidate_tools:
            # 没有可用工具，返回None
            return ToolSelection(
                tool=None,
                params={},
                confidence=0.0,
                alternatives=[],
                scenario=scenario,
                intent=intent
            )

        # 4. 评估工具
        scored_tools = []
        for tool in candidate_tools:
            score = await self.tool_evaluator.evaluate(
                tool, perception, intent, scenario
            )
            scored_tools.append((tool, score))
            logger.debug(f"工具 {tool.name} 评分: {score:.2f}")

        # 5. 选择最佳工具
        scored_tools.sort(key=lambda x: x[1], reverse=True)
        best_tool, best_score = scored_tools[0]

        # 6. 生成工具参数
        params = await self.param_generator.generate(
            best_tool, perception, intent
        )

        logger.info(f"选择工具: {best_tool.name}, 置信度: {best_score:.2f}")

        return ToolSelection(
            tool=best_tool,
            params=params,
            confidence=best_score,
            alternatives=[t for t, _ in scored_tools[1:]],
            scenario=scenario,
            intent=intent
        )
```

---

### 2.8 执行计划器（多工具组合）

```python
from dataclasses import dataclass, field
from typing import List

@dataclass
class ExecutionStep:
    """执行步骤"""
    id: str                         # 步骤ID
    tool: Tool                       # 工具
    params: dict                     # 参数
    depends_on: List[int] = field(default_factory=list)  # 依赖的步骤ID列表


@dataclass
class ExecutionPlan:
    """执行计划"""
    steps: List[ExecutionStep]       # 执行步骤列表

    def topological_sort(self) -> List[ExecutionStep]:
        """拓扑排序执行步骤"""
        # 简化实现
        sorted_steps = []
        completed = set()

        max_iterations = len(self.steps) * len(self.steps)
        for _ in range(max_iterations):
            progress = False

            for step in self.steps:
                if step.id in completed:
                    continue

                # 检查依赖是否完成
                if all(dep in completed for dep in step.depends_on):
                    sorted_steps.append(step)
                    completed.add(step.id)
                    progress = True

            if not progress:
                break

        if len(sorted_steps) != len(self.steps):
            raise ValueError("执行计划存在循环依赖")

        return sorted_steps

    @classmethod
    def parse(cls, plan_data: List[dict], tool_registry: 'ToolRegistry') -> 'ExecutionPlan':
        """从LLM输出解析"""
        steps = []

        for i, step_data in enumerate(plan_data):
            tool = tool_registry.get(step_data["tool"])
            steps.append(ExecutionStep(
                id=str(i),
                tool=tool,
                params=step_data["params"],
                depends_on=step_data.get("depends_on", [])
            ))

        return cls(steps=steps)


class ExecutionPlanner:
    """执行计划器 - 支持多工具组合"""

    def __init__(self, llm: LLMAdapter, tool_registry: 'ToolRegistry'):
        self.llm = llm
        self.tool_registry = tool_registry

    async def plan(self, tool_selection: ToolSelection) -> ExecutionPlan:
        """生成执行计划"""

        # 判断是否需要多工具组合
        if await self.is_complex_task(tool_selection):
            return await self.plan_multi_tool(tool_selection)
        else:
            # 单工具执行
            return ExecutionPlan(
                steps=[
                    ExecutionStep(
                        id="0",
                        tool=tool_selection.tool,
                        params=tool_selection.params,
                        depends_on=[]
                    )
                ]
            )

    async def is_complex_task(self, tool_selection: ToolSelection) -> bool:
        """判断是否为复杂任务"""

        # 简化判断：
        # - 置信度低（< 0.8）→ 可能需要多工具
        # - 意图包含多个动词 → 可能需要多工具
        # - 场景为task_execution → 可能需要多工具

        if tool_selection.confidence < 0.8:
            return True

        # 可以用LLM判断
        prompt = f"""
        任务：{tool_selection.perception.data}

        这个任务是需要多个工具协作完成，还是单个工具足够？

        只回答：single 或 multi
        """

        answer = await self.llm.generate(prompt)
        return "multi" in answer.lower()

    async def plan_multi_tool(self, tool_selection: ToolSelection) -> ExecutionPlan:
        """多工具执行计划"""

        # 格式化可用工具
        tools_desc = []
        for tool in tool_selection.alternatives[:5]:  # Top5
            tools_desc.append(f"""
            - {tool.name}: {tool.description}
              参数: {tool.schema}
            """)

        prompt = f"""
        任务：{tool_selection.perception.data}

        可用工具：
        {''.join(tools_desc)}

        请生成工具执行计划（JSON格式）：
        [
            {{"tool": "tool_name", "params": {{...}}, "depends_on": []}},
            {{"tool": "tool_name2", "params": {{...}}, "depends_on": [0]}}
        ]

        depends_on表示依赖的前置步骤索引（从0开始）。
        只返回JSON，不要其他内容。
        """

        plan_str = await self.llm.generate(prompt)
        plan_data = json.loads(plan_str)

        return ExecutionPlan.parse(plan_data, self.tool_registry)

    async def execute_plan(self, plan: ExecutionPlan) -> List[ToolResult]:
        """执行计划（处理依赖关系）"""

        results = {}
        completed_steps = set()

        # 拓扑排序执行
        for step in plan.topological_sort():
            # 检查依赖是否完成
            if all(dep in completed_steps for dep in step.depends_on):
                logger.info(f"执行步骤 {step.id}: {step.tool.name}")

                result = await self.tool_registry.execute(
                    step.tool.name, step.params
                )
                results[step.id] = result
                completed_steps.add(step.id)

                # 如果某步失败，停止后续依赖它的步骤
                if not result.success:
                    logger.error(f"步骤 {step.id} 执行失败: {result.error}")

        return list(results.values())
```

---

### 2.9 工具注册中心

```python
class ToolRegistry:
    """工具注册中心"""

    def __init__(self):
        self.public_tools: Dict[str, Tool] = {}   # 对外工具（Skills）
        self.internal_tools: Dict[str, Tool] = {} # 对内工具
        self.tool_history: Dict[str, Dict] = {}   # 工具历史统计

    def register(self, tool: Tool):
        """注册工具"""
        if tool.is_internal:
            self.internal_tools[tool.name] = tool
            logger.debug(f"对内工具已注册: {tool.name}")
        else:
            self.public_tools[tool.name] = tool
            logger.info(f"对外工具（Skill）已注册: {tool.name}")

        # 初始化历史统计
        self.tool_history[tool.name] = {
            "usage_count": 0,
            "success_count": 0,
            "success_rate": 1.0
        }

    async def execute(self, tool_name: str, params: dict) -> ToolResult:
        """执行工具"""
        tool = self.public_tools.get(tool_name) or self.internal_tools.get(tool_name)

        if not tool:
            raise ValueError(f"工具不存在: {tool_name}")

        # 更新统计
        history = self.tool_history[tool_name]
        history["usage_count"] += 1

        # 执行
        result = await tool.execute(params)

        # 更新成功率
        if result.success:
            history["success_count"] += 1

        history["success_rate"] = (
            history["success_count"] / history["usage_count"]
        )

        return result

    def get(self, name: str) -> Optional[Tool]:
        """获取工具"""
        return self.public_tools.get(name) or self.internal_tools.get(name)

    def get_by_scenario(self, scenario: str) -> List[Tool]:
        """按场景获取工具"""
        return [
            tool for tool in self.public_tools.values()
            if scenario in tool.scenario_tags
        ]

    def list_public(self) -> List[Tool]:
        """列出所有对外工具（供UI展示）"""
        return list(self.public_tools.values())

    def list_internal(self) -> List[Tool]:
        """列出所有对内工具（供Agent使用）"""
        return list(self.internal_tools.values())

    async def get_stats(self, tool_name: str) -> Dict:
        """获取工具统计"""
        return self.tool_history.get(tool_name, {})
```

---

### 2.10 插件管理器

```python
class PluginManager:
    """插件管理器"""

    def __init__(self):
        self.plugins: Dict[str, Plugin] = {}
        self.tool_registry = ToolRegistry()
        self.hook_executor = HookExecutor()
        self.storage_backends: Dict[str, StorageBackend] = {}
        self.llm_adapters: Dict[str, LLMAdapter] = {}
        self.sensors: Dict[str, Sensor] = {}

    async def load_plugin(self, plugin: Plugin):
        """加载插件"""

        logger.info(f"正在加载插件: {plugin.name} v{plugin.version}")

        # 1. 调用插件load方法
        await plugin.load()

        # 2. 注册工具
        for tool in plugin.get_tools():
            self.tool_registry.register(tool)

        # 3. 注册存储后端
        storage = plugin.get_storage_backend()
        if storage:
            self.storage_backends[plugin.name] = storage
            logger.info(f"注册存储后端: {plugin.name}")

        # 4. 注册LLM适配器
        llm = plugin.get_llm_adapter()
        if llm:
            self.llm_adapters[plugin.name] = llm
            logger.info(f"注册LLM适配器: {plugin.name}")

        # 5. 注册感知器
        for sensor in plugin.get_sensors():
            self.sensors[sensor.name] = sensor
            logger.info(f"注册感知器: {sensor.name}")

        # 6. 记录插件
        self.plugins[plugin.name] = plugin

        logger.info(f"插件已加载: {plugin.name}")

    async def unload_plugin(self, plugin_name: str):
        """卸载插件"""

        plugin = self.plugins.get(plugin_name)
        if not plugin:
            logger.warning(f"插件不存在: {plugin_name}")
            return

        logger.info(f"正在卸载插件: {plugin_name}")

        # 1. 调用插件unload方法
        await plugin.unload()

        # 2. 注销工具
        for tool in plugin.get_tools():
            if tool.name in self.tool_registry.public_tools:
                del self.tool_registry.public_tools[tool.name]
            if tool.name in self.tool_registry.internal_tools:
                del self.tool_registry.internal_tools[tool.name]

        # 3. 移除其他注册
        self.storage_backends.pop(plugin_name, None)
        self.llm_adapters.pop(plugin_name, None)

        for sensor in plugin.get_sensors():
            self.sensors.pop(sensor.name, None)

        # 4. 移除插件
        del self.plugins[plugin_name]

        logger.info(f"插件已卸载: {plugin_name}")

    async def execute_hook(self, hook_name: str, data):
        """执行插件钩子"""

        config = HOOK_CONFIGS.get(hook_name,
                                  {"mode": "parallel", "stop_on_error": False})

        # 排序插件
        plugins = await self._sort_plugins(list(self.plugins.values()))

        if config["mode"] == "chain":
            return await self.hook_executor.execute_chain(
                hook_name, data, plugins, config["stop_on_error"]
            )
        else:
            return await self.hook_executor.execute_parallel(
                hook_name, data, plugins, config["stop_on_error"]
            )

    def list_public_tools(self) -> List[Tool]:
        """列出所有对外工具（供UI展示）"""
        return self.tool_registry.list_public()

    def list_internal_tools(self) -> List[Tool]:
        """列出所有对内工具（供Agent使用）"""
        return self.tool_registry.list_internal()

    async def _sort_plugins(self, plugins: List[Plugin]) -> List[Plugin]:
        """按优先级和依赖关系排序"""
        return _sort_plugins_by_priority(plugins)
```

---

## 3. 目录结构

```
magi/
├── backend/src/magi/plugins/
│   ├── __init__.py
│   ├── base.py              # 插件基类
│   ├── manager.py           # 插件管理器
│   ├── hooks.py             # 钩子执行器
│   │
│   ├── builtin/             # 内置插件
│   │   ├── __init__.py
│   │   ├── tools/           # 工具插件
│   │   │   ├── email.py     # 邮件工具插件
│   │   │   ├── web.py       # 网页工具插件
│   │   │   ├── file.py      # 文件工具插件
│   │   │   └── internal.py  # 内部工具插件
│   │   │
│   │   ├── storage/         # 存储插件
│   │   │   ├── sqlite.py
│   │   │   ├── chromadb.py
│   │   │   └── redis.py
│   │   │
│   │   ├── llm/             # LLM插件
│   │   │   ├── openai.py
│   │   │   ├── anthropic.py
│   │   │   └── local.py
│   │   │
│   │   └── sensors/         # 感知器插件
│   │       ├── camera.py
│   │       ├── microphone.py
│   │       └── sensor_data.py
│   │
│   └── custom/              # 用户自定义插件
│       └── README.md        # 插件开发指南
```

---

## 4. 使用示例

```python
# ========== 创建Agent ==========

# 1. 创建插件管理器
plugin_manager = PluginManager()

# 2. 加载内置插件
await plugin_manager.load_plugin(EmailToolPlugin())
await plugin_manager.load_plugin(WebSearchToolPlugin())
await plugin_manager.load_plugin(SQLiteStoragePlugin())

# 3. 加载自定义插件
from my_plugins import CustomToolPlugin
await plugin_manager.load_plugin(CustomToolPlugin())

# ========== Agent执行 ==========

async def agent_loop():
    while True:
        # 1. Sense（执行before_sense钩子）
        context = SenseContext()
        context = await plugin_manager.execute_hook("before_sense", context)

        perceptions = await perception_module.perceive()

        # 执行after_sense钩子
        await plugin_manager.execute_hook("after_sense", perceptions)

        for perception in perceptions:
            # 2. Plan（执行钩子）
            await plugin_manager.execute_hook("before_plan", perception)

            # 决策选择工具
            tool_selection = await decision_engine.decide(perception)

            await plugin_manager.execute_hook("after_plan", tool_selection.action)

            # 3. Act（执行钩子）
            await plugin_manager.execute_hook("before_act", tool_selection.action)

            # 生成执行计划（单工具/多工具）
            plan = await execution_planner.plan(tool_selection)

            # 执行计划
            results = await execution_planner.execute_plan(plan)

            await plugin_manager.execute_hook("after_act", results)

            # 4. Reflect（执行钩子）
            await plugin_manager.execute_hook("before_reflect", (perception, action, results))

            await reflect_and_learn(perception, action, results)

            await plugin_manager.execute_hook("after_reflect", experience)
```

---

## 5. 关键特性总结

### 插件系统
- ✅ 生命周期钩子（before/after）
- ✅ Chain/Parallel执行模式
- ✅ 依赖关系处理
- ✅ 插件类型：Tool/Storage/LLM/Sensor

### 工具系统
- ✅ 对外工具 vs 对内工具
- ✅ 5步决策流程（场景→意图→匹配→评估→参数）
- ✅ 多工具组合执行
- ✅ 工具历史统计和成功率追踪

### 技术栈
- Python 3.10+
- asyncio（异步）
- SQLite（存储）
- ChromaDB（向量检索）
- LLM（决策支持）
