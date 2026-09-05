# magi-plugin-sdk

Magi's standalone Python SDK, version **0.2**, protocol **2**. External plugins
import only `magi_plugin_sdk`; the Magi backend is not a plugin dependency.
The SDK requires Python 3.10+ and Pydantic 2.5+.

## Package and connection

A package declares code and capabilities. A `PluginConnection` identifies one
configured account or source, with its own settings, credential references,
revision and enabled state. Installing a package does not execute it. Create a
connection, complete setup and explicitly enable it to publish its capabilities.
Libraries do not own connections.

```toml
[plugin]
id = "example"
name = "Example"
version = "0.1.0"
protocol_version = 2
min_sdk_version = "0.2.0"
execution_mode = "trusted_process"
entry_module = "plugin"
entry_class = "ExamplePlugin"
contribution_types = ["operation"]

[[plugin.settings_fields]]
key = "token"
label = "API token"
type = "secret"
required = true
```

`Plugin.configure(manifest=..., connection=..., context=...)` is host-owned.
Implementations use `self.connection_id`, `self.settings` and `self.context`.
`PluginContext` supplies private state/resources directories and scoped
credentials; it does not expose Magi's database paths or dependency container.
Secret fields are sent separately, never returned in settings, and read through
`context.credentials.get("token")` using the exact declared field key.

A `Source` contributes data under a connection. Its `source_id` identifies the
contribution; `source_type` describes the semantic category of its records.
`SourceChange.object_id` identifies a record within that source.

## Public capabilities

| Surface | Contract and purpose |
| --- | --- |
| Operations and tools | `OperationSpec`, `InvocationIdentity`, `OperationResult`; schemas, effects, cancellation, idempotency and bounded output. Existing `BaseTool` declarations normalize into the same operation execution path. |
| Sources | `Source`, `SourceSyncContext`, `SourceChangeBatch`, `SourceChange`, `SourceSpec`; stable connection-local object IDs, revisions, checkpoints and evidence. |
| Historical imports | `HistoryImporter`, `HistoryImporterSpec`; connection-scoped file or account history transformed through host ingestion. |
| Channels | `Channel`, host-injected session mapping, message dispatch and inbound admission contracts. |
| Providers | Web search, model generation/streaming and external agent contracts; host-owned provider selection. |
| Skills | `Plugin.get_skills()` returns named skill directories, indexed with connection ownership. |
| Hooks | `HookEventType`, `HookContext`, `HookDecision`; validated event payloads and bounded hook decisions. |
| Memory projections | Declared source selectors with extraction/summary profiles; advisory structured results governed and persisted by the host. |
| Settings | Manifest `settings_fields`, `activation_flow`, `settings_actions`, `settings_resources`, `settings_ui_blocks`; host-rendered connection setup and operation-backed actions. |
| Resources | `ResourceRef` and scoped host create/read calls; bounded opaque references instead of arbitrary host file access. |
| Lifecycle | Connection enable/disable, revision-checked updates, readiness, disconnect and `clear_user_content`. |

`get_sources()` returns `(source_id, source, SourceSpec)` tuples.
`get_operations()` returns `OperationSpec` declarations; implement
`invoke_operation(operation_id, arguments, identity)` for execution.
Read-only settings catalogs are declared in the manifest so setup can render
before code execution. Setup actions/resources that work while disabled must
explicitly set `requires_enabled = false`; they do not expose ordinary tools.

## Execution and authority

External code runs in an isolated Python worker importing only the SDK, that
package and its exact declared libraries. Framed, typed RPC uses no pickle.
Host callbacks validate the connection, capability grants and resource scope;
returned declarations are not grants. Source emission and resources are accessed
through `magi_plugin_sdk.worker.get_host().call(...)` and remain host-validated.

`trusted_process` requires explicit package trust and runs with the current
user's OS access. Process separation is not an OS sandbox. `restricted_process` uses
host-enforced confinement where supported and fails closed where unavailable;
current confinement is verified on macOS. Neither mode grants direct memory
writes. Ordinary operations still pass the host's invocation authorization and
existing effect ledger.

SDK contracts reject unknown fields and non-finite JSON numbers. Protocol 1,
package-global account configuration and old source result types are unsupported.

## Destructive-clear-safe channel ingress

Every registered channel must explicitly declare one inbound clear strategy:

- `INTERNAL` for host-owned channels that do not accept external inbound work
- `PROVIDER_TIME` when the platform supplies a trustworthy event occurrence time
- `DURABLE_CURSOR` for polling streams that can replay backlog without such a time

Before any session mapping, command, attachment, or chat dispatch, call
`capture_inbound_context` with the channel type, a stable upstream stream ID,
and exactly one evidence object. A provider timestamp must come from the
provider; local receipt or polling time is not valid evidence. Pass the returned
context unchanged through every host call for that event.

Every external channel must implement `inbound_clear_boundary`. Entering the
context is local-only: pause ingress, clear buffered events and transport
message maps, and durably record the requested host generation. It must never
wait for the provider network and must be idempotent because the host invokes it
during an active clear and may invoke it again before startup.

Provider-time channels can resume after context exit; events without a valid
provider time are terminally rejected. Cursor channels persist the generation
as pending and remain paused. They reconcile the remote cursor asynchronously,
then mark the generation applied and only then resume polling and use it in
`ChannelCursorClearProof`. `dispatcher.read_current_clear_generation()` lets a
plugin finish missed local preparation before it starts any ingress loop.

See `docs/plugin-development-guide.md` in the main repo for the full guide.
