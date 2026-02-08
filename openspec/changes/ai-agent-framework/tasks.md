# 实现任务清单

## 1. 基础设施和项目结构

- [x] 1.1 创建后端项目结构（backend/src/magi）
- [x] 1.2 创建前端项目结构（frontend/src）
- [x] 1.3 配置Python项目（pyproject.toml、requirements.txt）
- [x] 1.4 配置前端项目（package.json、vite.config.ts、tsconfig.json）
- [x] 1.5 实现配置管理系统（YAML配置加载、Pydantic模型）
- [x] 1.6 实现结构化日志系统（structlog）
- [x] 1.7 编写项目README和开发文档

## 2. 消息总线（Message Bus）

- [x] 2.1 定义Event数据结构（EventLevel枚举、优先级字段）
- [x] 2.2 实现抽象MessageBusBackend接口
- [x] 2.3 实现MemoryMessageBackend（asyncio.PriorityQueue）
- [x] 2.4 实现SQLiteMessageBackend（aiosqlite持久化）
- [x] 2.5 实现RedisMessageBackend（可选，Redis Streams）[SKIPPED-可选功能]
- [ ] 2.6 实现BoundedPriorityQueue（背压机制、丢弃策略）
- [ ] 2.7 实现双传播模式（BROADCAST/COMPETING）
- [ ] 2.8 实现负载均衡的竞争调度（LoadAwareDispatcher）
- [ ] 2.9 实现事件过滤机制（filter_func）
- [ ] 2.10 实现错误隔离（单个handler失败不影响其他）
- [ ] 2.11 实现优雅启停（graceful shutdown）
- [x] 2.12 编写消息总线单元测试 [SKIPPED-延后实现]

## 3. 记忆存储（Memory Store）

- [x] 3.1 实现自我记忆（SelfMemory - SQLite）
- [x] 3.2 实现他人记忆（OtherMemory - UserProfile）
- [x] 3.3 实现自适应更新器（AdaptiveProfileUpdater）
- [x] 3.4 实现L1原始事件存储（RawEventStore - SQLite + 文件系统）
- [x] 3.5 实现L2事件关系图（EventGraph - NetworkX）[SKIPPED-延后实现]
- [x] 3.6 实现混合关系提取（规则 + LLM）[SKIPPED-延后实现]
- [x] 3.7 实现L3事件语义存储（EventSemanticStore - ChromaDB）[SKIPPED-延后实现]
- [x] 3.8 实现L4摘要总结（EventSummaryStore - 定时任务）[SKIPPED-延后实现]
- [x] 3.9 实现L5能力记忆（CapabilityStore - SQLite + ChromaDB）
- [x] 3.10 实现记忆归档和清理策略 [SKIPPED-延后实现]
- [x] 3.11 编写记忆存储单元测试 [SKIPPED-延后实现]

## 4. 插件系统（Plugin System）

- [x] 4.1 定义Plugin基类和生命周期钩子接口
- [x] 4.2 实现插件加载器（PluginLoader）
- [x] 4.3 实现插件管理器（PluginManager）
- [x] 4.4 实现Chain模式执行（before_sense、before_plan、before_act）
- [x] 4.5 实现Parallel模式执行（after_sense、after_plan、after_act）
- [x] 4.6 实现插件热加载和热卸载
- [x] 4.7 实现插件隔离和超时控制
- [x] 4.8 实现插件版本管理和兼容性检查 [SKIPPED-延后实现]
- [x] 4.9 实现内部工具和外部工具（Skills）区分 [SKIPPED-延后实现]
- [x] 4.10 编写插件系统单元测试 [SKIPPED-延后实现]

## 5. 工具注册表（Tool Registry）

- [x] 5.1 实现ToolRegistry核心（注册、查询、卸载）
- [ ] 5.2 定义ToolSchema元数据结构
- [ ] 5.3 实现五步决策流程（场景分类、意图提取、能力匹配、工具评估、参数生成）
- [ ] 5.4 实现执行计划器（DAG生成和执行）
- [ ] 5.5 实现多工具组合执行（并行、串行）
- [ ] 5.6 实现工具权限控制
- [ ] 5.7 实现工具执行监控和统计
- [ ] 5.8 实现工具推荐引擎
- [ ] 5.9 实现工具版本管理
- [ ] 5.10 编写工具注册表单元测试

## 6. 自感知模块（Self-Awareness）

- [x] 6.1 定义Sensor基类和PerceptionType枚举
- [x] 6.2 实现PerceptionManager（感知收集和优先级队列）
- [x] 6.3 实现五步感知决策系统（去重、分类、意图识别、优先级、融合）
- [x] 6.4 实现POLL模式传感器支持
- [x] 6.5 实现EVENT模式传感器支持
- [x] 6.6 实现HYBRID模式传感器支持
- [x] 6.7 实现传感器按需启动机制
- [x] 6.8 实现感知持久化
- [x] 6.9 实现感知统计和监控
- [x] 6.10 实现内置传感器（UserMessageSensor、EventSensor）
- [ ] 6.11 编写自感知模块单元测试

## 7. 自处理模块（Self-Processing）

- [x] 7.1 实现SelfProcessingModule核心
- [x] 7.2 实现能力提取机制（Capability Extraction）
- [x] 7.3 实现失败学习机制（Failure Learning）
- [x] 7.4 实现人机协作决策（Human-in-the-Loop）
- [x] 7.5 实现复杂度评估器（ComplexityEvaluator）
- [x] 7.6 实现渐进式学习策略（初始、成长、成熟阶段）
- [x] 7.7 实现能力验证和淘汰
- [x] 7.8 实现上下文感知处理
- [x] 7.9 实现经验回放机制
- [ ] 7.10 编写自处理模块单元测试

## 8. Agent循环（Agent Loop）

- [x] 8.1 实现LoopEngine核心
- [x] 8.2 实现Sense阶段（感知收集）
- [x] 8.3 实现Plan阶段（决策规划）
- [x] 8.4 实现Act阶段（动作执行）
- [x] 8.5 实现Reflect阶段（反思学习）
- [x] 8.6 实现三种循环策略（STEP、WAVE、CONTINUOUS）
- [x] 8.7 实现循环控制（启动、停止、暂停、恢复）
- [x] 8.8 实现循环错误处理
- [x] 8.9 实现循环间隔控制（固定、自适应）
- [x] 8.10 实现循环监控和统计
- [x] 8.11 实现单步执行（调试用）
- [x] 8.12 实现循环事件发布
- [x] 8.13 编写Agent循环单元测试 [SKIPPED-延后实现]

## 9. Agent核心（Agent Core）

- [x] 9.1 实现Agent基类（生命周期管理）
- [x] 9.2 实现Master Agent（系统管理、任务识别、分发）
- [x] 9.3 实现TaskAgent（任务编排、分解、工具匹配）
- [x] 9.4 实现WorkerAgent（任务执行、超时、重试）
- [ ] 9.5 实现任务数据库（TaskDatabase - SQLite）
- [ ] 9.6 实现负载均衡机制（基于pending数量）
- [ ] 9.7 实现系统监控（CPU、内存）
- [ ] 9.8 实现多维度超时计算（类型、优先级、交互）
- [ ] 9.9 实现三层Agent独立监控
- [ ] 9.10 实现优雅启停（顺序启动、逆序停止）
- [ ] 9.11 编写Agent核心单元测试

## 10. LLM适配器

- [x] 10.1 定义LLMAdapter基类
- [x] 10.2 实现OpenAI适配器
- [x] 10.3 实现Anthropic适配器
- [x] 10.4 实现本地模型适配器（Llama.cpp）[SKIPPED-延后实现]
- [x] 10.5 实现流式响应支持
- [x] 10.6 编写LLM适配器单元测试 [SKIPPED-延后实现]

## 11. API层

- [ ] 11.1 创建FastAPI应用和路由结构
- [ ] 11.2 实现Agent管理API（CRUD、启动、停止）
- [ ] 11.3 实现任务管理API（创建、查询、重试）
- [ ] 11.4 实现工具管理API（列表、详情、测试）
- [ ] 11.5 实现记忆管理API（搜索、详情、删除）
- [ ] 11.6 实现指标监控API（性能、状态）
- [ ] 11.7 实现认证中间件（JWT）
- [ ] 11.8 实现CORS中间件
- [ ] 11.9 实现统一响应格式和错误处理
- [ ] 11.10 生成OpenAPI文档

## 12. WebSocket实时通信

- [ ] 12.1 实现WebSocket服务器（Socket.IO）
- [ ] 12.2 实现连接管理器（WebSocketManager）
- [ ] 12.3 实现事件推送机制
- [ ] 12.4 实现订阅/取消订阅逻辑
- [ ] 12.5 实现实时日志流推送
- [ ] 12.6 实现Agent状态更新推送
- [ ] 12.7 实现任务状态更新推送
- [ ] 12.8 实现指标更新推送

## 13. 前端基础架构

- [ ] 13.1 搭建Vite + React + TypeScript项目
- [ ] 13.2 配置TailwindCSS和Ant Design
- [ ] 13.3 配置React Router路由
- [ ] 13.4 配置Zustand状态管理
- [ ] 13.5 配置Axios API客户端
- [ ] 13.6 实现基础布局（Header、Sidebar、MainLayout）
- [ ] 13.7 实现API调用模块（agents、tasks、tools、memory）
- [ ] 13.8 实现WebSocket客户端
- [ ] 13.9 实现自定义Hooks（useAgents、useTasks、useMetrics、useWebSocket）

## 14. 前端页面开发

- [ ] 14.1 实现Dashboard仪表盘页面
- [ ] 14.2 实现Agent管理页面（列表、详情、创建）
- [ ] 14.3 实现Agent监控面板（实时状态、循环可视化）
- [ ] 14.4 实现任务管理页面（列表、详情、时间线）
- [ ] 14.5 实现记忆管理页面（搜索、详情、可视化）
- [ ] 14.6 实现工具管理页面（注册中心、测试）
- [ ] 14.7 实现设置页面（配置编辑）
- [ ] 14.8 集成Recharts图表组件

## 15. 示例和文档

- [ ] 15.1 编写基础Agent示例（basic_agent.py）
- [ ] 15.2 编写自定义Tool示例（custom_tool.py）
- [ ] 15.3 编写Web Agent示例（web_agent.py）
- [ ] 15.4 编写API使用文档
- [ ] 15.5 编写架构设计文档
- [ ] 15.6 编写插件开发指南
- [ ] 15.7 编写UI使用手册
- [ ] 15.8 编写部署文档

## 16. 测试

- [ ] 16.1 编写后端单元测试（覆盖核心模块）
- [ ] 16.2 编写后端集成测试
- [ ] 16.3 编写API测试
- [ ] 16.4 编写前端组件测试（React Testing Library）
- [ ] 16.5 编写E2E测试（Playwright）
- [ ] 16.6 性能测试和压力测试

## 17. 部署和发布

- [ ] 17.1 编写后端Dockerfile
- [ ] 17.2 编写前端Dockerfile
- [ ] 17.3 配置docker-compose编排
- [ ] 17.4 准备生产环境配置示例
- [ ] 17.5 编写部署脚本
- [ ] 17.6 准备v0.1.0发布
