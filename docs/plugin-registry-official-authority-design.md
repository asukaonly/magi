# Plugin Registry `official` Authority Design

Status: Implemented — registry allowlist is authoritative and app persistence is wired
Author: brainstorming session 2026-05-31
Last verified: 2026-07-14
Scope: Second of three plugin-security sub-projects (#2). #1 (supply-chain
locking) and #3 (capability declaration + consent UI) are also done.
Sandbox/process-isolation remains parked.

## 1. 背景

Magi 的可选插件住在 `magi-plugins` 仓,通过 `registry.json` 被 App 拉取。本设计提出时，每个
插件在 `plugin.toml` 里**自报** `official` 字段;`magi-plugins/scripts/build-
registry.py:42` 直接把它抄进 `registry.json`:

```python
entry["official"] = meta.get("official", False)
```

App 端 marketplace 用这个字段显示"官方认证 ✓"徽章
(`frontend/src/components/settings/PluginMarketplace.tsx:297`)。

**威胁**:一旦开放第三方提交插件,任何人 fork magi-plugins、在自己插件的
`plugin.toml` 里写 `official = true`,`build-registry.py` 就会把它当真抄进
registry,marketplace 给它盖官方徽章 → 社会工程,用户被骗装恶意插件。

这不是技术越权问题(沙箱管那个),而是**信任来源伪造**问题:`official` 现在
由"插件自己说"决定,而不是"维护者说"。

### 现状中已经安全的部分(不要动)

- `manager.py:687`:自动启用只在 `manifest.official AND source == "builtin"`。
  builtin = 打进 app 二进制的插件,其 manifest 可信。非 builtin 这行恒 False,
  **不存在自动启用伪造**。
- `manager.py:239`:非 builtin 插件加载前必须 `trusted`(用户显式操作),已有
  trust gate。
- marketplace 徽章读的是 registry entry 的 `official`
  (`plugins_common.py:413`、`plugins_registry_routes.py:77` →
  `entry.official`)。registry curation 修好后,这条即安全。

### 现状中可伪造的部分(本设计要修)

- `plugins_common.py:115` 和 `:565`:已安装插件的 `official` 来自
  `manifest.official` —— 即本地 `plugin.toml`,对非 builtin 插件是作者控制的,
  可伪造。任何消费这个字段的 UI/逻辑(现在或将来)都会被骗。

## 2. 目标 / 非目标

### 目标

- `official` 的真相来源从"插件自报"变为"维护者控制的 allowlist"。第三方 PR
  无法给自己盖 `official`。
- App 端对非 builtin 插件的 `official`,只信 registry 来源,不信本地 manifest。
- sideload(不在 registry 里)的插件 `official` 恒 `False`。

### 非目标 (YAGNI)

- ❌ **不做插件内容 hash 锁定**(用户在 brainstorming 选了仅 (a))。
- ❌ **不做 registry.json 加密签名**(同上)。registry 完整性仍依赖 GitHub
  HTTPS + branch protection。
- ❌ **不治 `author` 字段**。当前徽章只认 `official`;`author` 纯展示、非信任
  信号。若将来 `author` 进入信任判定,另开工作。
- ❌ **不改 builtin 插件的 official 来源**。builtin 打进二进制,manifest 可信。
- ❌ **不改 trust gate / 自动启用逻辑**(`manager.py:239`、`:687`)——本就安全。

## 3. 架构(跨两个 repo)

```
┌─────────────────────────── magi-plugins repo ───────────────────────────┐
│ official-plugins.json   (新增, maintainer-only allowlist of plugin_ids)   │
│        │                                                                  │
│        ▼  scripts/build-registry.py  (改: official 从 allowlist 派生)     │
│        │     忽略 plugin.toml 自报的 official; 自报时 warn                 │
│        ▼                                                                  │
│ registry.json           (official 字段现在权威)                           │
│                                                                           │
│ .github/CODEOWNERS      (新增/改: official-plugins.json 需 maintainer)     │
└──────────────────────────────────────────────────────────────────────────┘
                                   │ fetch over HTTPS
                                   ▼
┌─────────────────────────────── magi repo ────────────────────────────────┐
│ install (registry_client + manager):                                      │
│   persist registry entry.official → plugins.packages.<id>.official        │
│   sideload install → official = False                                     │
│                                                                           │
│ projection (plugins_common.py:115/:565):                                  │
│   builtin     → manifest.official  (unchanged, trusted)                   │
│   non-builtin → persisted/registry official  (NOT manifest.official)      │
└──────────────────────────────────────────────────────────────────────────┘
```

**职责边界**:
- **magi-plugins**:决定谁是 official(allowlist),生成权威 registry。
- **magi**:安装时记录 registry 的 official,展示时对非 builtin 不信本地 manifest。

## 4. 组件

### 4.1 `magi-plugins/official-plugins.json`(新增)

维护者控制的 allowlist。最简形态:

```json
{
  "official_plugin_ids": [
    "browser_history_core",
    "calendar",
    "git-activity",
    "chrome-history",
    "firefox-history",
    "edge-history",
    "photo-library",
    "screen_time",
    "steam_play_history",
    "system_media",
    "terminal_history",
    "netease_music",
    "telegram",
    "weixin",
    "screenshot_timeline"
  ]
}
```

(初始内容 = 当前 registry 里 `official: true` 的全部 plugin_id,使迁移零行为
变化。实际列表以迁移时 `registry.json` 现状为准。)

### 4.2 `magi-plugins/scripts/build-registry.py`(改 official 来源)

第 42 行 `entry["official"] = meta.get("official", False)` 改为:

```python
entry["official"] = plugin_dir.name in official_ids  # or by plugin_id
```

其中 `official_ids` 是启动时从 `official-plugins.json` 读入的 set。注意 allowlist
用 **plugin_id**(manifest 的 `id`),不是目录名(两者可能不同,如 `calendar_plugin/`
目录 → `calendar` id)。所以匹配用 `meta.get("id", plugin_dir.name)`。

额外:若某插件 `plugin.toml` 仍自报了 `official = true`,打印一条 warning
("plugin X self-declares official=true; ignored — authority is official-plugins.json"),
帮助维护者发现混淆 / 可疑提交。

### 4.3 `magi-plugins/.github/CODEOWNERS`(新增或改)

```
/official-plugins.json   @asukaonly
```

使任何改 allowlist 的 PR 必须维护者审批。配合 GitHub branch protection 的
"require review from code owners"。(若仓库已有全局 CODEOWNERS 覆盖,确认
allowlist 被包含。)

### 4.4 magi: 安装时持久化 registry official

`plugins.packages.<id>` 已持久化 `enabled/trusted/source/manifest_path` 等
(`manager.py:688-691`)。新增持久化 `official`:

- **registry 安装**(`install_plugin_from_registry` 或等价路径,经
  `registry_client` + `PluginRegistryEntry`):写
  `plugins.packages.<id>.official = entry.official`。
- **sideload 安装**(`install_plugin_from_archive` / `install_plugin_from_
  directory`,无 registry entry):写 `plugins.packages.<id>.official = False`。
- **builtin**:不持久化 official(展示时直接读 manifest)。

### 4.5 magi: 展示时对非 builtin 不信本地 manifest

`plugins_common.py:115` 和 `:565` 当前 `official=manifest.official`。改为一个
小 helper:

```python
def _authoritative_official(state) -> bool:
    if state.manifest.source == "builtin":
        return bool(state.manifest.official)        # builtin self-trusted
    return bool(getattr(state, "official", False))  # persisted registry value
```

两处投影改为调用它。registry 来源的两处(`:413`、registry_routes `:77`)已经是
`entry.official`,不动。

## 5. 数据流

### 5.1 维护者把某插件标为 official(magi-plugins)

1. 维护者编辑 `official-plugins.json` 加入 plugin_id(需 CODEOWNERS 审批的 PR)。
2. 跑 `python scripts/build-registry.py`(+ `gen_registry.py`,见 #1 的 CI 备注),
   registry.json 的该插件 `official` 变 true。
3. 提交 registry.json。CI 的 `registry-in-sync` 守护一致性。

### 5.2 第三方提交插件(magi-plugins)

1. 第三方 PR 只动 `plugins/their-plugin/`,可能在 plugin.toml 自报
   `official=true`。
2. `build-registry.py` 忽略自报、打 warning,registry 里该插件 `official=false`。
3. 维护者不改 allowlist → 永远 false。

### 5.3 用户安装 + 查看(magi)

1. 从 marketplace 装 registry 插件:持久化 `entry.official`。
2. sideload 装:持久化 `official=false`。
3. 任何已安装插件视图的 official:非 builtin 读持久化值,与本地 plugin.toml
   自报无关。

## 6. 迁移

- magi-plugins:`official-plugins.json` 初始内容 = 当前 registry 中 `official:true`
  的 plugin_id 全集 → 跑 build-registry → registry.json 应**零变化**(证明迁移
  无行为漂移)。
- magi:现有已安装插件的 package state 没有 `official` 字段。helper 用
  `getattr(state, "official", False)` 兜底 → 老数据非 builtin 默认 false,直到
  下次安装/刷新写入。可接受(保守:宁可少给徽章,不可错给)。若需要,提供一个
  一次性 reconcile:scan 时对已知 registry 插件回填 official。

## 7. 测试 / 验证

### magi-plugins

- `build-registry.py`:allowlist 内插件 → `official:true`;allowlist 外但自报
  `official=true` 的插件 → `official:false`(+ warning)。
- 迁移后 `registry.json` 与迁移前字节一致(allowlist = 现有 official 集)。
- CI `registry-in-sync` 仍 exit 0。

### magi

- 单元:`_authoritative_official` —— builtin+manifest official=true → true;
  non-builtin+persisted official=true → true;non-builtin+manifest official=true
  但 persisted false → **false**;sideload(persisted false)→ false。
- 安装路径:registry 安装持久化 entry.official;sideload 持久化 false。
- 投影:`plugins_common.py` 两处用 helper,API 对伪造 manifest 的非 builtin 插件
  返回 official=false。
- 现有 plugins 测试不回归。

## 8. 已知风险与缓解

### 8.1 allowlist 与 registry 可能漂移

维护者改了 allowlist 但忘了重生成 registry.json。**缓解**:#1 已建的
`registry-in-sync` CI job(build-registry + gen_registry + git diff)会拦住——
registry.json 落后于 allowlist 即红。

### 8.2 已安装老插件 official 字段缺失

见 §6:`getattr(..., False)` 保守兜底。非 builtin 老插件在下次刷新/安装前
显示为非 official。安全方向正确(少给徽章)。

### 8.3 plugin_id vs 目录名不一致

`calendar_plugin/` 目录 → `calendar` id。allowlist 必须用 **plugin_id**,
build-registry 匹配也用 id。§4.2 已指明。测试需覆盖一个目录名≠id 的插件
(calendar)。

### 8.4 CODEOWNERS 仅在开启 branch protection "require code owner review" 时生效

CODEOWNERS 文件本身不强制,需仓库设置配合。**缓解**:文档说明;这是仓库
配置项,不在代码内。本 spec 提供文件,启用由维护者在 GitHub 设置完成。

## 9. 开放问题

无。allowlist 机制、magi 侧持久化+helper 隔离均已收敛。

## 10. 与兄弟子项目的关系

- **#1 供应链锁定**(已完成):防依赖投毒。其 `registry-in-sync` CI job 是本
  项目 allowlist↔registry 一致性的现成守护。
- **本项目 #2**:防 official 徽章伪造(信任来源)。
- **#3 capability 声明 + consent UI**(待做):防"看不出插件行为 + 知情同意"。
  本项目把 registry 确立为权威信任源,#3 的 capability 申报可沿用同样的
  "registry/manifest 谁说了算"边界。
- **沙箱**(挂起):防运行时越权。
