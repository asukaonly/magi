# Frontend API Types Codegen (Lv2 boundary tightening)

Status: Active architecture — Phase 0 complete; module migration ongoing
Author: brainstorming session 2026-05-29
Last verified: 2026-07-14
Context: follows up on the Lv1 boundary refactor (commit `7e7b2ed4`) where
the `api.*` helper generics in `frontend/src/api/client.ts` were tightened
from `<T = any>` to `<T = unknown>`. Lv2 is the next architectural step:
make the FastAPI / pydantic backend the single source of truth for the
shape of every payload that crosses the IPC boundary.

Implementation note: the generator, committed `generated.ts`, and CI/release
drift gates shipped in Phase 0. The migration of handwritten API-module types
is still in progress; `sensors.ts` currently consumes a generated schema while
the remaining modules retain handwritten request/response types.

## 1. 背景

本设计提出时，Magi 前端在 `frontend/src/api/modules/*.ts` 里有 27 个手写的 API 模块，
合计 400+ 个 `interface`/`type` 声明。这些类型描述的是后端
`backend/src/magi/transport/http_app.py` 那一组 FastAPI 路由的请求 /
响应形状，但当时**没有任何机制保证手写类型与后端 pydantic 模型一致**。

后端已经具备生成 OpenAPI 的能力：

- `scripts/export-python-openapi.py` 调用 `create_transport_app().openapi()`，
  把 FastAPI 的运行时 schema 序列化为 JSON。
- `release.yml` 第 184-186 行已经在 release 流程里跑这个脚本，但只是
  导出后让 `scripts/check-api-contract.py` 做"路径 + 方法存在性"校验。
- Phase 0 之前没有步骤把 schema 信息回灌到前端类型；现在生成和漂移检查已落地。

Phase 0 之前的结果是：

1. 后端改 pydantic 字段（rename、变 optional、加 enum），前端类型
   不会自动跟进。
2. drift 只能靠人肉 code review 抓，常常等到运行时 `undefined.foo` 才发现。
3. 同一个 entity（如 `Persona`、`Plugin`、`MemoryEvent`）的形状在
   前后端各写一遍，duplicate 维护负担永久存在。

Lv1 的 boundary 收紧只解决"调用方必须显式声明类型"，**没解决"显式声明的
类型本身是不是对的"**。Lv2 要解决后者。

## 2. 目标 / 非目标

### 目标

- 后端 pydantic / FastAPI route schema 成为前端 API 类型的 **single source
  of truth**。
- 任何后端 schema 变化都通过 CI 强制反映到前端 generated 文件，drift 在
  PR 阶段就被工具抓出来，不依赖 reviewer 人肉对比。
- 最终把 `frontend/src/api/modules/*.ts` 中的手写 interface 全部替换为
  对 generated 文件的 re-export，27 个 module 文件只剩"函数 wrapper + 类型
  re-export"两类内容。

### 非目标 (YAGNI)

- ❌ **不引入运行时校验**（Zod 之类）。这是用户在 brainstorming Q1
  明确选择的范围——只要编译期类型安全。
- ❌ **不生成 fetch client / SWR hook / RTK Query slice**。保留现有
  `apiClient.get/post/...` 函数 wrapper 风格。
- ❌ **不改 backend pydantic 任何字段**。codegen 是只读消费者。
- ❌ **不覆盖 Tauri IPC 命令的类型**。Lv2 范围限于 HTTP API；Tauri
  `invoke()` 调用的类型化是独立工作。
- ❌ **不生成 frontend-only 的"视图模型"类型**（计算字段、跨 endpoint
  组合）。这类类型继续手写，放 `src/types/view/` 或就近的组件目录。

## 3. 架构

```
backend/src/magi/transport/http_app.py        (pydantic models, 真相)
                │
                ▼  scripts/export-python-openapi.py
                │
                ▼  openapi.json (临时产物，不入 git)
                │
                ▼  npx openapi-typescript openapi.json -o ...
                │
                ▼
       frontend/src/types/api/generated.ts    (入 git, codegen 产物)
                │
   ┌────────────┼────────────┬─────────────────────────┐
   ▼            ▼            ▼                         ▼
api/modules/  api/modules/  api/modules/  ...        api/modules/
personas.ts   memory.ts     plugins.ts               (其它 24 个)
   │            │            │
   │ 仅做 re-export + 函数 wrapper
   │
   ▼
import type { ... } from '@/types/api/generated'
```

### 3.1 工具选择

`openapi-typescript`。理由：

- 只产出 TypeScript 类型，**0 运行时代码**，0 bundle 影响（tsc 把整个
  文件 erase 掉）。
- 社区最大、文档最全、维护最活跃。
- 兼容 OpenAPI 3.0 和 3.1，FastAPI 当前默认产 3.1 schema。

否决的替代方案：

- `openapi-zod-client`：产 Zod 运行时 schema，跟目标 #1（无 runtime
  开销）矛盾。
- `orval`：偏向"全自动生成 fetch client + React Query hook"，要么全套
  接管要么不用，跟"保留现有 axios 风格"矛盾。
- `openapi-typescript-codegen`：能用，但生成的是 class-based fetch
  client，比 `openapi-typescript` 更重、更 opinionated。

### 3.2 Generated 文件入 git

`frontend/src/types/api/generated.ts` **提交到 git**。理由：

- PR review 能直接看到 schema 变化，reviewer 不用本地跑生成器才能
  理解一个 PR 改了什么 API。
- 新 contributor `git clone` 后能直接 `npm run build`，不需要先装
  Python venv 跑 backend。
- CI 比对很简单：重跑生成器 + `git diff --exit-code`。
- 文件大小不是问题——纯 TS 类型，gzip 后几十 KB 量级，且根本不会
  打进 runtime bundle。

### 3.3 CI 反 drift 闸门

在 `ci.yml` 和 `release.yml` 都加一步：

```yaml
- name: Verify generated API types are up to date
  shell: bash
  run: |
    ./scripts/gen-api-types.sh
    if ! git diff --exit-code frontend/src/types/api/generated.ts; then
      echo "::error::frontend/src/types/api/generated.ts is stale."
      echo "Run scripts/gen-api-types.sh locally and commit the result."
      exit 1
    fi
```

效果：

- 后端 schema 改了但 contributor 漏跑生成器 → CI 红、PR 不让合。
- 后端 schema 没改、前端 generated 也没改 → 无 diff，pass。
- 前端 generated 被手改 → 下次 contributor 重跑会撞回去；CI 抓到。

## 4. 组件

### 4.1 `scripts/gen-api-types.sh`

新增脚本，两步：

```bash
#!/usr/bin/env bash
set -euo pipefail

# 该脚本要从仓库根目录跑（npm script 在 frontend/ 里调用时已经 cd 上来）
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

OPENAPI_TMP="$(mktemp -t magi-openapi.XXXXXX.json)"
trap 'rm -f "${OPENAPI_TMP}"' EXIT

python scripts/export-python-openapi.py --output "${OPENAPI_TMP}"

(
  cd frontend
  npx --yes openapi-typescript "${OPENAPI_TMP}" \
      --output src/types/api/generated.ts \
      --immutable
)
```

注：

- `--immutable` 让 generated 类型字段是 `readonly`，强调"这是后端的形状，
  前端不要原地改"。
- 进 `frontend/` 子目录跑 `npx` 是为了让 `openapi-typescript` 用
  `frontend/node_modules/` 下的依赖，而不是回退到全局。
- 不用全局装 `openapi-typescript`；版本固定在
  `frontend/package.json` devDependencies 里。

### 4.2 `frontend/package.json`

添加：

- `devDependencies`: `openapi-typescript@^7`（截至本 spec 撰写时最新
  是 7.13.0，跟 Vite 8 / TS 5.3 兼容）
- `scripts`:
  - `"gen:api-types": "bash ../scripts/gen-api-types.sh"` —— 本地开发跑

### 4.3 `frontend/src/types/api/generated.ts`

由 `openapi-typescript` 写入。文件头部会有自动加的：

```typescript
/**
 * This file was auto-generated by openapi-typescript.
 * Do not make direct changes to the file.
 */
```

我们额外在 `frontend/src/types/api/README.md` 里说明：

- 这个文件不要手改；
- 改后端 pydantic 后请跑 `npm run gen:api-types` 重新生成；
- frontend-only 的 view 类型放 `src/types/view/`，不要往 generated 里塞。

### 4.4 模块迁移示例

迁移前 `frontend/src/api/modules/personas.ts`：

```typescript
export interface IdentityCore {
  identity_statement: string;
  values_loved: string[];
  ...
}

export interface PersonaSummary {
  persona_id: string;
  display_name: string;
  ...
}

export async function listPersonas(): Promise<PersonaSummary[]> {
  const response = await api.get<{ personas: PersonaSummary[] }>('/personas');
  return response.data?.personas ?? [];
}
```

迁移后：

```typescript
import type { components } from '@/types/api/generated';

export type IdentityCore = components['schemas']['IdentityCore'];
export type PersonaSummary = components['schemas']['PersonaSummary'];

export async function listPersonas(): Promise<PersonaSummary[]> {
  const response = await api.get<{ personas: PersonaSummary[] }>('/personas');
  return response.data?.personas ?? [];
}
```

调用方的 `import { PersonaSummary } from '@/api/modules/personas'` 不变。

### 4.5 CI 集成位置

Drift check 需要同时具备 Python 3.13（跑 `export-python-openapi.py`）
和 Node 20（跑 `openapi-typescript`）两套运行时，而现有的 ci.yml `frontend`
job 只装了 Node。所以选其中之一：

- **方案 a**（推荐）：在 `ci.yml` 加一个新 job `api-types-drift`，独立
  setup-python + setup-node + 装 backend 依赖（与现有 backend job 共享
  缓存），跑 `bash scripts/gen-api-types.sh` + `git diff --exit-code`。
  独立 job 失败不阻塞其它 job，但 PR 整体仍然红。
- **方案 b**：在 `ci.yml` 现有的 `frontend` job 里加上 `setup-python` +
  backend deps 安装。结构上 frontend job 职责变重，但只有一个 job 在
  跑前端相关检查。

`release.yml` 已经把所有 setup 都做了，直接在 `Run frontend validation`
之前加一步即可。

Phase 0 实施时再二选一；不影响本 spec 的整体设计。

## 5. 数据流

### 5.1 开发者改后端

1. 改 `backend/src/magi/api/routers/<x>.py` 的 pydantic model。
2. 跑 `npm run gen:api-types`（或本地 git pre-commit hook，可选）。
3. `generated.ts` diff 出现；如果有依赖该 schema 的前端代码报错，跟着改。
4. 提交 PR，包含 backend 改动 + `generated.ts` + 受影响的前端代码。

### 5.2 开发者只改前端

1. `generated.ts` 不变。
2. 正常改 `api/modules/*.ts` 的函数 wrapper 或调用方代码。
3. 提交 PR。

### 5.3 CI 校验

1. CI 拉代码、跑 `gen-api-types.sh`、`git diff --exit-code generated.ts`。
2. 无 diff → 继续跑 type-check / vitest / build。
3. 有 diff → fail，提示 contributor 重跑命令。

## 6. 迁移策略（分阶段）

### Phase 0 — 铺管道（已完成）

- 装 `openapi-typescript`。
- 写 `scripts/gen-api-types.sh`。
- 跑一次，提交首版 `generated.ts`。
- 写 `frontend/src/types/api/README.md`。
- `ci.yml` + `release.yml` 加 drift check 步骤。
- **此阶段不动任何 `api/modules/*.ts`**——管道空跑，仅证明 CI 能抓 drift。

验证标准：

- 故意改一个后端字段 → CI 在 phase 0 部署后能拦住。
- `npm run build` 仍然过。
- `npm run test:ci` 仍然 547/547。

### Phase 1+N — 逐 module 迁移（进行中；每个 PR 1-3 个模块）

每个 PR：

1. 选一个 `api/modules/<name>.ts`。
2. 把里面所有手写的 request/response interface 换成
   `export type Foo = components['schemas']['Foo']`。
3. 跑 tsc + vitest 验证调用方仍然编译通过、测试通过。
4. 提交。

优先顺序建议（按耦合大小）：

1. `availability.ts`、`hooks.ts`、`local-reranker.ts`（小、独立）
2. `personas.ts`、`memoryPortrait.ts`、`memoryPortraitSelf.ts`（中、相关）
3. `memory.ts`、`messages.ts`、`plugins.ts`（大、核心）
4. 其余 ~15 个

每个 PR 独立可发布。

### 完成态

- 所有 27 个 `api/modules/*.ts` 只剩"函数 wrapper + 类型 re-export"
- 手写 request/response interface 数量从 400+ 降到 0
- 前端独有的视图类型迁到 `src/types/view/`，generated.ts 不污染

## 7. 测试 / 验证

### Phase 0 acceptance

- `npm run gen:api-types` 在 macOS / Linux 都跑得通（Windows 暂不要求，
  本地开发以 Mac 为主，CI 的 windows-latest matrix 在 release.yml 跑）。
- CI 故意改后端字段后能 fail。
- `npm run build` / `type-check` / `test:ci` 全绿。

### 每个 Phase 1+ PR acceptance

- 该 module 所有 export 的 interface 已替换为 re-export 或被删除。
- 调用方代码不变（import 路径稳定）。
- tsc 0 错误。
- vitest 全绿。

## 8. 已知风险与缓解

### 8.1 OpenAPI export 可能不全

`scripts/export-python-openapi.py` 现在只验"路径存在"，不验 schema 完整性。
可能有 endpoint 用了 `Any` 返回或者用了 OpenAPI 表达不了的 union——这些
会被生成为 `Record<string, unknown>` 或 `unknown`。

**缓解**: Phase 0 跑出第一版 `generated.ts` 后，grep 一下 `unknown` 和
`Record<string, unknown>` 出现的次数，对高频字段做一份"需要回去给 backend
加 typed model"的待办清单，**不阻塞 Phase 0**，作为后续 backend 工作。

### 8.2 pydantic alias / serialization_alias 导致字段名不匹配

如果 backend 用 `Field(alias='foo_bar')`，OpenAPI 里出现的可能是
`foo_bar` 而不是 Python 字段名 `fooBar`。生成出来的 TS 字段会跟运行时
JSON 一致，但跟现有手写 interface 可能不一致。

**缓解**: Phase 1 迁移时遇到不一致 → 选择信任生成的（因为它来自运行时
真实 schema）+ 在 PR 里说明改动。

### 8.3 部分 endpoint 不在 transport_app 里

后端有些 endpoint 可能挂在不同的 FastAPI app 上（如 dev-only debug 路由）。
`export-python-openapi.py` 只导 `create_transport_app()` 那个 app。

**缓解**: 这些 endpoint 本来就不在生产前端调用范围内，不需要 codegen
覆盖。Phase 1 迁移时如果发现某个 module 的 endpoint 不在 generated 里，
保留手写并加注释说明原因。

### 8.4 generated.ts 文件较大可能影响 IDE 体验

OpenAPI 3.1 schema 可能展开成几千行 TS 类型，VS Code 加载稍慢。

**缓解**: `openapi-typescript` 已经对大 schema 做了优化（v7 性能数倍
v6）。如果实测有问题，可以在 `tsconfig.json` 的 `exclude` 里限制
language server 的扫描范围；但通常 generated.ts 在 ~50KB 量级，没问题。

### 8.5 generator 版本升级带来的 diff

`openapi-typescript` 每个 major 版本可能调整输出格式。

**缓解**: 在 `frontend/package.json` 里**固定 minor 版本**（`^7.0.0`
而不是 `*`）。Major 升级走单独 PR，包含 generated.ts 的格式变化。

## 9. 开放问题

无。Phase 0 起步前的所有决策均已收敛：

- 工具：`openapi-typescript@^7`
- 生成路径：`frontend/src/types/api/generated.ts`
- 提交策略：入 git
- CI 闸门：drift check
- 迁移节奏：Phase 0 一个 PR + Phase 1 多个独立 PR

## 10. 与 Lv1 / 后续 Lv 的关系

- **Lv1**（已完成 `7e7b2ed4`）：边界默认类型从 `any` → `unknown`，强制调用方
  显式声明期望类型。
- **Lv2**（本设计）：让"显式声明的类型"本身从 backend 来，不再手写。
- **Lv3 (不做)**：枚消代码库中所有 `any`。本 spec 显式判定**不值得做**，
  Zone 3（plugin manifest / dynamic config 字段）的 `any` 是诚实标注，
  改成假类型反而虚伪。
- **可选未来 Lv2.5**（不在本 spec 范围）：如果后期发现 runtime drift 仍
  造成线上问题，可以在 Lv2 基础上加 Zod 校验。Zod schema 可以从 generated
  TS 类型 codegen，二次工程量不大。但目前没有信号支持这个投入。
