# Plugin Capability Declaration + Install Consent Design

Status: Implemented — declarations, install/update/sideload consent, and persistence shipped
Author: brainstorming session 2026-06-01
Last verified: 2026-07-14
Scope: Third and largest of three plugin-security sub-projects (#3). #1
(supply-chain locking) and #2 (registry-as-authority for `official`) are done.
本子项目做 **capability 声明 + 安装前知情同意 UI**;运行时沙箱/进程隔离仍
**挂起**(另开工作,目前无信号justify)。

## 1. 背景

Magi 的可选插件住在 `magi-plugins` 仓,通过 `registry.json` 被 App 拉取,装进
`~/.magi/plugins/<id>/`。本设计提出时的安装流程
(`frontend/src/components/settings/PluginMarketplace.tsx:97` `handleInstall`)
点了"安装"就直接调 `pluginsApi.installFromRegistryWithProgress(pluginId, ...)`
落地,**没有任何披露/同意步骤**。用户装一个第三方插件时,看不出它会读你的
日历、扫你的照片、还是把数据发到某个外部主机。

当时仓里已有一个**萌芽期的能力声明约定**——
`magi-plugins/plugins/screenshot_timeline/plugin.toml:22`:

```toml
[plugin.permissions]
declares = ["screen_recording", "accessibility_optional", "fs_write_resources"]
memory_access = ["write_l1"]
```

但它:
1. 只有 1 个插件用,其余 14 个插件零声明。
2. 是**扁平字符串标签**,混了 OS 权限(`screen_recording`)、可选标志
   (`accessibility_optional`)、资源意图(`fs_write_resources`),没有 schema。
3. **没流过 registry**:`build-registry.py` 不抄它,registry.json 里没有,App
   端拿不到,无法在安装前展示。
4. 装载时被丢弃:`manager.py:704` 的 `_load_manifest` 把 `[plugin]` 块整体
   `model_validate` 成 `PluginManifest`,而 `PluginManifest` 没有 `permissions`
   字段 → `permissions` 子表被静默忽略。

这是 **Chrome 扩展模型**要解决的问题:**声明 + 审查 + 同意**。本子项目把这套
萌芽约定**正式化并扩展**——定义能力分类 schema、像 `official` 那样流过 registry、
在安装/更新/sideload 前用同意弹窗展示给用户——而**不**发明平行机制,也**不**做
运行时强制。

### 三层价值(确立本设计范围的理由)

- **安装时**:用户知情同意("此插件将访问 ~/Library/Calendars 和网络。安装?")。
- **审查时**:第三方 PR 提交到 registry 时,声明的能力是审核者的对照清单(一个
  日历插件声明 `subprocess` 或 `network` 就是即时红旗)。
- **地基**:若将来真做运行时沙箱,manifest 里的声明已经在那,可直接用来强制。

## 2. 目标 / 非目标

### 目标

- 把 `[plugin.permissions]` 种子正式化成**结构化能力声明**:一套**已知枚举**的
  能力类别,访问类(文件系统/网络/子进程)可带**可选的人类可读 scope**。
- 能力声明像 `official`/`contribution_types` 一样**流过 registry**
  (plugin.toml → build-registry.py → registry.json → `PluginRegistryEntry`),
  让 marketplace 在**安装前**展示。
- 安装前弹**分组式同意弹窗**(系统权限 / 数据与网络),展示插件**声明**的能力 +
  scope + 理由,用户确认才安装。
- **更新时**若声明的能力相对用户已同意的集合**增加**(出现新类别**或** scope
  扩大)→ 拦下重新同意;否则静默更新。
- **sideload**(上传 archive)同样走同意:上传后先 inspect(解包读 manifest 拿
  能力但不激活)→ 弹同意 → 确认才落地。
- 现有 15 个插件**逐个手写**准确声明,行为中立(纯加声明,不改运行)。

### 非目标 (YAGNI)

- ❌ **不做运行时沙箱 / 进程隔离 / 能力强制**。capability 仅是**披露 + 同意 +
  审核清单**。声明是插件**自报的 claim**,运行时不拦截、不校验。沙箱挂起。
- ❌ **不做能力的维护者审定/验证**。与 #2 的 `official` 相反:`official` 是用户
  用来"放下戒心"的信任信号,往高伪造是攻击,所以 #2 用维护者 allowlist 控制;
  capability 是插件**自己声称**要访问什么,用户看了"提高戒心",真正的攻击是
  **少报**(实际比声明的多),而少报靠 curation 治不了(得做完整代码审计 + 运行
  时强制,本轮都不做),多报只是诚实。所以能力**自报**,UI 措辞为"声明",防
  少报靠第三方 PR 的审核清单。
- ❌ **不动 `[plugin.permissions].memory_access`**。那是 magi 内部内存层
  (L1/L2/L3)写权限概念,与"插件能碰我系统上的什么"正交,不并入本轮 consent。
- ❌ **不引入运行时 OS 权限状态检查**。前端已有 `PluginPermissionStatusItem`
  (`frontend/src/api/modules/plugins.ts:79`,granted/denied/"打开系统设置")——
  那是**已装插件设置页**里查 OS 授权状态的**运行时**概念,与本轮**安装前**的
  **声明**概念不同。本设计只做声明+同意,不碰那套运行时状态(但枚举命名会对齐,
  见 §8.4)。
- ❌ **不改 builtin 插件流程**。builtin 打进二进制,manifest 可信,且不经
  marketplace 安装,无同意步骤。
- ❌ **枚举不一次做满**。本轮固定 10 项(见 §4.1),location/microphone/camera
  等后续按需加。

## 3. 架构(跨两个 repo)

```
┌─────────────────────────── magi-plugins repo ───────────────────────────┐
│ plugins/<id>/plugin.toml                                                  │
│   [[plugin.permissions.capabilities]]  (结构化, 作者写)                   │
│        │                                                                  │
│        ▼  scripts/build-registry.py  (改: 抄 capabilities, 像 official)   │
│        │                                                                  │
│        ▼  scripts/gen_registry.py  (不动, 仅 suggestion_descriptor)       │
│ registry.json   entry["capabilities"]  (现在 App 能拉到)                  │
│                                                                           │
│ .github/workflows/ci.yml  registry-in-sync (既有, 守护一致性)             │
└──────────────────────────────────────────────────────────────────────────┘
                                   │ fetch over HTTPS
                                   ▼
┌─────────────────────────────── magi repo ────────────────────────────────┐
│ SDK contracts.py: PluginCapability / PluginManifest.permissions /         │
│                   PluginRegistryEntry.capabilities                        │
│                                                                           │
│ registry_client → PluginRegistryEntry.capabilities                        │
│ registry route  → PluginRegistryEntryResponse.capabilities (前端可见)     │
│                                                                           │
│ marketplace 安装前 → PluginConsentDialog 展示 capabilities → 确认才装      │
│ install_with_closure → 持久化 consented_capabilities (PluginSettings)     │
│ sideload: /install/upload/inspect 解包读 manifest → 同意 → 装             │
│ update: 前端 diff registry.capabilities ⊆ consented? 否→重新同意          │
└──────────────────────────────────────────────────────────────────────────┘
```

**职责边界**:
- **magi-plugins**:定义能力声明 schema,生成带 capabilities 的 registry。
- **magi**:解析 capabilities,安装/更新/sideload 前展示并征求同意,持久化
  用户已同意的集合,更新时 diff。

## 4. 组件

### 4.1 能力声明 schema(plugin.toml + SDK)

plugin.toml 用 array-of-tables 取代扁平 `declares`:

```toml
[[plugin.permissions.capabilities]]
capability = "filesystem_read"          # 必填, 取自已知枚举
scope = ["~/Library/Calendars"]         # 可选, 仅 fs/network/subprocess 有意义
reason_i18n = { en = "Parse the local calendar DB", "zh-CN" = "解析本地日历数据库" }
optional = false                        # 可选, 默认 false
```

**已知枚举(初版 10 项)**:

| 组 | capability | 含义 |
|---|---|---|
| 系统权限 | `screen_recording` | 截取屏幕画面 |
| 系统权限 | `accessibility` | 辅助功能(读活动窗口等) |
| 系统权限 | `calendar` | 日历与提醒事项 |
| 系统权限 | `photos` | 照片库 |
| 系统权限 | `contacts` | 通讯录 |
| 系统权限 | `system_media` | 系统媒体播放控制 |
| 数据与网络 | `filesystem_read` | 读文件(scope=路径前缀) |
| 数据与网络 | `filesystem_write` | 写文件(scope=路径前缀) |
| 数据与网络 | `network` | 联网(scope=主机/域名;空=任意主机) |
| 数据与网络 | `subprocess` | 子进程(scope=可执行名) |

**scope 语义**(用于 §5.4 的 diff):对 fs/network/subprocess,`scope` 为路径前缀
/ 主机 / 可执行名的列表;**空 scope 表示"未限定/任意"**(最宽)。系统权限类
忽略 scope。

**`capability` 用 `str` 而非 `Literal`(前向兼容)**:若新版 registry 声明了旧版
App 不认识的能力,`Literal` 会让整个 `PluginRegistryIndex.model_validate` 失败、
marketplace 直接 502。所以 wire 模型用 `str`;**已知枚举的权威校验放在
`magi-plugins/scripts/build-registry.py` 的 `KNOWN_CAPABILITIES`(CI 拦截未知能力,
非零退出)**,前端用"已知类别映射 + 未知优雅降级"渲染。新增能力 = 同时更新
build-registry 的 set、SDK 的已知列表注释、前端类别映射,是一次刻意动作。

**SDK `magi/sdk/src/magi_plugin_sdk/contracts.py`**(`PluginManifest:275`、
`PluginRegistryEntry:361` 所在文件):

```python
class PluginCapability(BaseModel):
    """A single declared capability. Self-declared by the plugin; shown to the
    user for informed consent. NOT enforced at runtime (no sandbox)."""
    capability: str   # 已知枚举见下表; 用 str 而非 Literal 以前向兼容
    scope: list[str] = Field(default_factory=list)
    optional: bool = False
    reason: str = ""
    reason_i18n: dict[str, str] = Field(default_factory=dict)


class PluginPermissions(BaseModel):
    """The [plugin.permissions] table. Tolerates legacy keys (declares,
    memory_access) via extra='allow' so existing manifests still parse."""
    capabilities: list[PluginCapability] = Field(default_factory=list)
    model_config = {"extra": "allow"}
```

- `PluginManifest` 新增 `permissions: PluginPermissions | None = None` + 便捷
  property `capabilities` → `self.permissions.capabilities if self.permissions
  else []`。`_load_manifest`(`manager.py:704`)对 `[plugin]` 块整体
  `model_validate`,加字段后 `permissions` 子表自动解析,无需改 loader。
- `PluginRegistryEntry` 新增 `capabilities: list[PluginCapability] =
  Field(default_factory=list)`(**顶层字段**,因为 build-registry 把它放在
  entry 顶层)。`registry_client.fetch_index` 走 `model_validate`,加字段后
  自动解析,无需改 client。

### 4.2 `magi-plugins/scripts/build-registry.py`(抄 capabilities)

`build_entry`(:46)在 `contribution_types`(:79)附近增加:

```python
permissions = meta.get("permissions", {}) or {}
capabilities = permissions.get("capabilities", [])
if capabilities:
    entry["capabilities"] = capabilities   # 原样拷贝, 像 contribution_types
```

非空才写(与 `name_i18n`/`depends_on` 的"条件包含"风格一致)。`gen_registry.py`
**不动**(只管 suggestion_descriptor)。⚠️ 仍是**两步管道**:改完跑
`build-registry.py` 再跑 `gen_registry.py` 才检查 registry.json。

> ⚠️ 与 #2 不同:#2 迁移后 registry.json **字节不变**;本轮 registry.json **会
> 变**(每个声明了能力的 entry 多一个 `capabilities` 字段)。"行为中立"指
> **运行时行为不变**(纯新增声明数据),不是字节不变。CI 的 `registry-in-sync`
> 只要求重新生成后已提交即可。

### 4.3 magi 后端:registry 入口暴露 capabilities

- `plugins_schemas.py` 的 `PluginRegistryEntryResponse` 新增
  `capabilities: list[PluginCapability]`(import 自 SDK contracts)。
- `plugins_registry_routes.py:68-87` 构造 `PluginRegistryEntryResponse` 时多传
  一行 `capabilities=entry.capabilities`。

### 4.4 magi 后端:持久化用户已同意的能力集

- `magi/backend/src/magi/config/plugin_models.py:10` 的 `PluginSettings` 新增:
  ```python
  consented_capabilities: Optional[list[PluginCapability]] = Field(
      default=None,
      description="Capabilities the user consented to at install/update; "
      "None means legacy install predating consent (treated as empty).",
  )
  ```
- **registry 安装/更新**:在 `plugins_common.py` 的 `install_with_closure`
  (#2 持久化 `official` 的同一处,~390 的 `package_config` / `save_config`)
  追加 `consented_capabilities = entry.capabilities`。不变式:registry 安装/更新
  成功后,`config.plugins.packages[id].consented_capabilities == entry.capabilities`
  (用户在弹窗里已看到并同意)。
- **sideload 安装**:**不**持久化 consented(YAGNI):sideload 插件不在 registry,
  没有 marketplace 更新路径(`update_plugin` 对非 registry 插件 404),persisted
  consented 永远不会被 diff 消费 → 死数据。inspect 弹窗已完成"安装前知情同意"的
  目的;持久化留待将来 sideload 真有更新路径时再加。
- **已装插件投影**:`PluginPackageResponse`(及前端 `PluginPackageState`)需同时
  暴露 manifest 的 `capabilities`(本地声明)和 `consented_capabilities`(已同意),
  供前端更新时 diff、设置页展示。

### 4.5 magi 后端:sideload inspect 端点

`installation.py:325` 的 `install_plugin_from_archive` 已有"解包→
`_find_manifest_in_tree`→`_load_manifest`"逻辑。抽出一个只读方法:

```python
def inspect_plugin_archive(self, archive_path: Path) -> PluginManifest:
    """Extract + read plugin.toml from an archive WITHOUT installing or
    persisting anything. Used to surface declared capabilities for consent
    before the user commits to a sideload install."""
    # 解包到临时目录, _find_manifest_in_tree + _load_manifest, 返回 manifest
```

新路由 `magi/backend/src/magi/api/routers/plugins_install_routes.py`:

```python
@plugins_install_router.post("/install/upload/inspect", response_model=PluginManifestResponse)
async def inspect_plugin_upload(file: UploadFile):
    """Return the declared capabilities + metadata of an uploaded archive
    without installing it (for the pre-install consent step)."""
```

返回 `{plugin_id, name, version, author, capabilities, ...}`。前端拿到后弹同意,
确认才走既有 `/install/upload/jobs`。

### 4.6 magi 前端:同意弹窗 + 接线

- 新组件 `frontend/src/components/plugins/PluginConsentDialog.tsx`:
  - 输入:plugin 名/版本/official、`capabilities`、模式(install / update / sideload)、
    可选的 `previouslyConsented`(更新模式下用于高亮新增项)。
  - **布局 B(按类别分组)**:标题「安装 X?」→「此插件**声明**将访问:」→ 两组
    **系统权限**(可能弹出系统授权)/ **数据与网络访问** → 每行(图标 + 类别标签 +
    scope + reason)→ 取消 / 安装。
  - **空声明**:无 capabilities → 显示「此插件未声明需要特殊系统权限或数据访问」
    并**仍需确认**(保持安装手势一致)。
  - **更新变体**:顶部高亮「本次更新新增了以下访问:」列出新增能力。
  - 每个 capability 类别的**图标 + 标签 + 组归属 + 通用描述**由 host 在前端常量
    映射 + i18n 定义(`category → {icon, group, descriptionKey}`);插件可选的
    `reason_i18n` 覆盖通用描述。
- 接线 `frontend/src/components/settings/PluginMarketplace.tsx`:
  - `handleInstall`(:97):调 install **前**先开弹窗;确认才
    `installFromRegistryWithProgress`。
  - `handleUpload`(:158):先调新 `pluginsApi.inspectUpload(file)` 拿能力 → 弹窗
    → 确认才 `installFromUploadWithProgress`。
  - `handleUpdate`(:137):先比较 registry entry 的 `capabilities` 与已装插件的
    `consented_capabilities`(§5.4 子集规则);非子集→弹更新变体→确认才
    `updatePluginWithProgress`;子集→沿用现状静默更新。
- API client `frontend/src/api/modules/plugins.ts`:`PluginRegistryEntry` 加
  `capabilities`;`PluginManifest`/`PluginPackageState` 加 `capabilities` +
  `consented_capabilities`;新增 `inspectUpload`。
- 前端类型 `frontend/src/types/api/generated.ts` 由后端 OpenAPI 生成,改完后端
  schema 跑 `npm run gen:api-types`(CI drift-check 守护)。
- i18n `frontend/src/i18n/locales/{en,zh-CN}/app.json`:弹窗标题/按钮/分组标题/
  空声明文案/更新文案 + **每个 capability 类别的标签与通用描述**,EN + zh-CN 各一份。

## 5. 数据流

### 5.1 插件作者声明能力(magi-plugins)

1. 在 `plugins/<id>/plugin.toml` 写 `[[plugin.permissions.capabilities]]`。
2. 跑 `python scripts/build-registry.py` 再 `python scripts/gen_registry.py`。
3. 连同 registry.json 提交 PR。CI `registry-in-sync` 守护一致性;审核者把声明的
   能力当对照清单(日历插件声明 `network`/`subprocess` = 红旗)。

### 5.2 用户从 marketplace 安装(magi)

1. marketplace 列表已带每个 entry 的 `capabilities`(来自 registry)。
2. 点"安装"→ `PluginConsentDialog` 展示能力 → 取消则中止。
3. 确认 → `installFromRegistryWithProgress` → 后端 `install_with_closure` 落地 +
   持久化 `consented_capabilities = entry.capabilities`。

### 5.3 用户 sideload(上传 archive)

1. 选文件 → 前端调 `/install/upload/inspect` → 后端解包读 manifest 返回能力(不
   激活)。
2. `PluginConsentDialog`(sideload 模式)展示 → 确认才 `/install/upload/jobs`。
3. 落地(不持久化 consented,见 §4.4 YAGNI)。

### 5.4 用户更新插件(magi)— diff 规则

更新时比较 registry entry 的新声明 `D_new` 与已同意集 `D_old`
(`consented_capabilities`):

- **覆盖判定**:`D_new` 中每个能力 `c` 都被 `D_old` 中某个**同类别** `c'`
  覆盖,才算"未增加"。`c` 被 `c'` 覆盖 iff:
  - `c` 无 scope(=任意):仅当 `c'` 也无 scope 时覆盖(新→任意 = 扩大,要重证)。
  - `c` 有 scope `S`:`c'` 无 scope(任意覆盖一切)**或** `S ⊆ c'.scope` 时覆盖。
- `D_new ⊆ D_old`(全部被覆盖)→ 静默更新;否则 → 弹更新变体重新同意。
- `optional` 标志**不参与** diff(仅展示提示),保持规则简单(见 §8.5)。
- 确认更新后,后端把 `consented_capabilities` 覆写为 `D_new`。

### 5.5 legacy 已装插件(无 consented_capabilities)

`consented_capabilities=None`(本设计前安装的)→ diff 时视为空集 → 下次更新只要
插件声明了任何能力就会触发一次重新同意(保守,方向正确:宁可多问一次)。

## 6. 迁移(逐个手写,运行时行为中立)

15 个插件逐个补声明(`browser_history_core` 是 library,隐藏,无声明):

| 插件 (dir → id) | 声明的 capabilities |
|---|---|
| calendar_plugin → calendar | `calendar`;`filesystem_read` scope `~/Library/Calendars` |
| chrome-history | `filesystem_read`(Chrome profile/History) |
| firefox-history | `filesystem_read`(Firefox profile) |
| edge-history | `filesystem_read`(Edge profile) |
| terminal_history → terminal-history | `filesystem_read`(shell 历史文件) |
| netease_music → netease-music | `filesystem_read`(NetEase 容器 sqlite) |
| steam_play_history → steam-play-history | `filesystem_read`(Steam 本地文件) |
| screen_time → screen-time | `filesystem_read` / 平台用量数据源 |
| git_activity → git-activity | `subprocess` scope `git`;`filesystem_read`(repo) |
| photo-library | `photos`;`filesystem_read`(照片库) |
| screenshot_timeline | `screen_recording`;`accessibility` (optional=true);`filesystem_write` scope `~/.magi` resources;`subprocess`(helper binary) |
| telegram | `network` scope `api.telegram.org` |
| weixin | `network`(iLink 网关主机) |
| system_media → system-media | `system_media` |
| browser_history_core | (library, 无) |

- 每个 capability 配 `reason_i18n`(EN + zh-CN 一行),复用插件现有
  `description_i18n` 的语气。
- screenshot_timeline 的旧 `declares` 改写成上面新形式;`memory_access` 保留不动。
- 实际 scope 路径以各插件代码/manifest 现状为准(迁移时核对)。
- 跑 build-registry + gen_registry,提交 registry.json(会变:多 capabilities 字段)。

## 7. 测试 / 验证

### magi-plugins

- `build-registry.py`:声明了 capabilities 的插件 → entry 含 `capabilities` 且与
  plugin.toml 一致;无声明的插件 entry 无该字段。
- 迁移后跑 build-registry + gen_registry,registry.json 的非-capabilities 字段
  与迁移前一致(只多 capabilities)。
- CI `registry-in-sync` 仍 exit 0(重新生成后已提交)。

### magi 后端

- 单元:`PluginCapability` / `PluginPermissions` 解析;`PluginManifest.capabilities`
  property 从 `[plugin.permissions].capabilities` 正确读出;带 legacy
  `declares`/`memory_access` 的 manifest 仍解析不报错。
- `PluginRegistryEntry` 从含 capabilities 的 registry.json `model_validate` 成功。
- registry route 返回的 `PluginRegistryEntryResponse` 带 capabilities。
- `PluginSettings.consented_capabilities` 字段存在(默认 None)。
- `install_with_closure` 持久化 `entry.capabilities` 到 `consented_capabilities`。
- `inspect_plugin_archive` 解包读 manifest 返回 capabilities 且**不**落地/持久化。
- diff 规则单元测试(§5.4):同类别 scope 子集 → 覆盖;新增类别 / scope 扩大 /
  specific→任意 → 不覆盖;legacy None → 视空集。
- 现有 plugins 测试不回归(注意 #2 提到的 7 个 chrome-history discovery 失败属
  既有、与本变更无关)。

### magi 前端

- `PluginConsentDialog`:install / update / sideload 三模式渲染;分组正确;空声明
  显示提示且仍需确认;更新变体高亮新增项。
- `handleInstall`/`handleUpload`/`handleUpdate` 在确认前不触发安装;取消则不安装。
- `npm run gen:api-types` 后 generated.ts 含 capabilities,CI drift-check 绿。
- EN / zh-CN 文案齐全。

### gateway

- `cargo test -p magi-gateway` 不回归(本变更不碰 gateway)。

## 8. 已知风险与缓解

### 8.1 插件少报(under-declaration)

恶意插件实际访问的比声明的多。**这是声明模型的固有局限**(无运行时强制就无法
根治)。**缓解**:(a) 第三方 PR 的审核清单——声明与代码不符是审核红旗;(b) 将来
做沙箱时声明已在,可强制。本轮明确接受此局限,UI 措辞用"声明"不用"已验证"。

### 8.2 registry.json 会变(非字节中立)

与 #2 不同,本轮 registry.json 多 capabilities 字段。**缓解**:迁移 PR 里明确这是
预期变化;CI `registry-in-sync` 只要求重新生成后已提交。

### 8.3 sideload inspect 导致文件上传两次

inspect 上传一次读 manifest,确认后 install 再上传一次。**缓解**:sideload 是
低频的高级动作,两次上传可接受;若将来成为痛点,可做"inspect 暂存解包目录 +
返回 token,install 凭 token"优化。本轮不做。

### 8.4 枚举命名与既有运行时权限状态不一致

前端已有 `PluginPermissionStatusItem`(运行时 OS 授权状态)。两者概念不同(声明 vs
运行时状态),但都叫"permission"。**缓解**:能力枚举命名尽量对齐(如
`screen_recording`、`accessibility`、`calendar`、`photos`),便于将来若把"声明的
OS 权限"链到"运行时状态检查"。本轮不连,仅命名对齐。

### 8.5 optional 标志不参与 diff

`optional: true → false`(可选变必需)严格说是一种"增加",但本轮 diff 忽略
`optional`。**缓解**:`optional` 仅作展示提示;类别/scope 级 diff 已覆盖主要的
能力扩大场景。若需要可后续把 optional→required 也纳入 diff。

### 8.6 scope 是自由文本,可能与实际不符或过期

scope 自报、不强制,可能写得不准或随版本过期。**缓解**:scope 是给用户和审核者的
**提示**,不是技术边界;审核时对照代码。与 8.1 同源,接受。

## 9. 开放问题

无。taxonomy(枚举+可选 scope)、authority(自报呈现为声明)、consent UI(布局 B)、
update 重证(scope 级 diff)、sideload(走 inspect+同意)、迁移(逐个手写)均已
在 brainstorming 收敛。

## 10. 与兄弟子项目的关系

- **#1 供应链锁定**(已完成):防依赖投毒。其 `registry-in-sync` CI job 也守护本轮
  capabilities↔registry 一致性;其 sideload 无锁拒装的最小提示,本轮并入更完整的
  sideload consent 流程。
- **#2 registry official 权威**(已完成):防 `official` 徽章伪造。本轮 capabilities
  沿用同样的"plugin.toml → build-registry → registry → App"传播路径,以及"安装时
  持久化进 PluginSettings"的模式(`official` → `consented_capabilities`)。**注意
  authority 边界相反**:official 必须维护者控制,capability 自报即可(§2 非目标已述)。
- **本项目 #3**:防"看不出插件行为 + 用户无知情同意"。
- **运行时沙箱/进程隔离**(挂起):防运行时越权。本轮的声明是其未来强制的地基。
