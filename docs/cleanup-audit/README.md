# 发布前兼容逻辑清理审计

三份独立报告，覆盖开发期遗留下来的兼容逻辑：

- [01-db-schema-compat.md](./01-db-schema-compat.md) — 数据库表结构 / ALTER / 索引
- [02-dto-compat.md](./02-dto-compat.md) — Pydantic / dataclass / 合约 DTO
- [03-frontend-compat.md](./03-frontend-compat.md) — 前端 API 适配 / 反序列化分支

## 高层结论

### 数据库（最干净的清理收益）

- 仓库没有正式 migration 框架；110 处 `ALTER TABLE ADD COLUMN` 用 `PRAGMA table_info` 守卫，绝大多数列在 baseline DDL 里已经声明 — 在新装库上是死代码。
- **直接删除**：`chat/migration.py`（L1→ChatStore 回填）、`memory/l2/storage/migrations.py`（含 `tom_trait_assertions_legacy` 重建）、L1 `_ensure_event_identity_schema` + `_backfill_external_owner_user_ids`、`_ensure_trace_spans_turn_id_nullable`、persona description 回填、3 处裸 `try/except ADD COLUMN persona_id`、`core/database_initializer.py` 里重复且过时的 `_init_llm_usage_db`。
- **合并**：11 处 `ensure_*_columns` 助手（chat 读写、runtime_trace、l0/l3/l4、l2 投影队列、l2 entity facets、l1 chat_sessions、llm usage、persona），baseline 已含列。
- **删前先补 baseline**：`runtime_trace/schema.py` 的 `thinking_content`/`result_json`、`l4/storage/schema.py` 的 `turn_id`/`deleted_at` —— 当前只在迁移里加，需要先补到 CREATE TABLE。
- **保留**：`crates/magi-gateway/src/db.rs::ensure_indexes`（幂等性能索引）。

### DTO

- `contracts/`、`crates/`、后端 Pydantic 主干都很干净（无 `serde(rename/alias)`、无 `Field(alias=)` 主体）。
- **删除候选**：`config/models.py` 的 `Config = AppConfig` 别名、`llm/provider_bridge/options.py::_disabled_thinking_extra_body`、`llm/openai.py::_apply_glm_thinking_control`、保留"for compatibility"的 `DEFAULT_EMBEDDING_MODEL`。
- **合并候选**：`PluginIngressEventRecord` re-export shim、`tool_invocation_service` 的 `_event_bus` + 合成 `ToolError`、`deep_thinking` ↔ `thinking_depth` 双名（contracts 与 context_routing/models）、`memory/event_translation._from_sensor_legacy`、`store_ingestion` 的 `event_id`/`id` 回退、`hybrid_retrieval._LEGACY_MODE_MAP` + `recall_intent`、`bootstrap_service.needs_bootstrap_init` 别名（**注意**这个别名也出现在 JSON 响应里，需联动前端）、`provider_bridge._coerce_thinking_depth(disable_thinking)` 链、`llm/{openai,anthropic}` 的 `base_url`/`api_base` 双构造、`api/routers/messages_common.legacy_messages_module()` 转发、`postprocess/utils.resolve_event_bus`、`l2/pipeline/validation/graph_candidates` 的 legacy/unified 合并。
- **保留**（在线/磁盘旧数据耦合）：runtime_trace turn_id NULL 重建、chat legacy_messages 桶、`message_kind`/`history_version` 默认、tom_trait_assertions_legacy 表、YAML 用户文件归一、`PluginManifest.plugin_id = Field(alias="id")`（公开合约）、XML 工具调用解析回退。

### 前端

- **删除**：`auth_token` localStorage + `/login` 跳转（路由已不存在）；`store-projection` 中 `persona_id || personaId` camelCase 回退（后端只发 snake_case）；`personas.ts:380` / `memory.ts:373` 误导性"legacy"注释。
- **合并**：`normalizeTurnUxPlan` 双键、`toExecutionTraceSummary` 来回换型助手、两个主题键 `magi-theme-mode` vs `magi_theme`、`magi_onboarding_state` 两处重复定义。
- **保留**：`unwrapGatewayPayload`（测试证明后端仍双形）、`message.kind || message.role` 防御、秒/毫秒时间戳归一、节奏段 canonical 兼容分支（有专门测试）、`content_delta`/`is_final` legacy 流回退（phase-5 完成后再看）。

## 建议执行顺序

1. **前端 DELETE 清单**最先动 —— 风险最低、无外部依赖。
2. **DB DELETE 清单**第二 —— 一次性发布前重置，注意先把 baseline DDL 补齐 `runtime_trace` 与 `l4` 的两组列。
3. **DTO DELETE/CONSOLIDATE** —— 中间需要扫调用方，特别是 `needs_bootstrap_init` 这种跨前后端的别名要前后端一起改。
4. **DB/DTO/前端 CONSOLIDATE** —— 收尾，按报告里的逐项 file:line 推进。
