# Authoring a SuggestionDescriptor

Plugins that want to be **auto-suggested** by magi when a user's
conversation indicates a need for their capability should declare a
`suggestion_descriptor` block in their `plugin.toml`. Plugins without
this block are still fully usable, but they will not be proactively
recommended; users must discover and enable them through the Plugins
settings page.

## Minimum viable descriptor

```toml
[plugin.suggestion_descriptor]
category = "code_activity"           # group key; siblings share it
setup_time_estimate_seconds = 10
data_locality = "local_only"          # or "uploads"
platform_support = ["darwin", "linux", "win32"]

[plugin.suggestion_descriptor.triggers]
intents = ["user_asks_about_code_changes"]
entities = ["commit", "repository", "branch"]

[plugin.suggestion_descriptor.triggers.keywords]
zh = ["代码", "提交", "改了什么"]
en = ["code", "commit", "changed"]

[plugin.suggestion_descriptor.rationale]
zh = "magi 会读取你的 git 仓库回答这类问题"
en = "magi will read your git repositories to answer these questions"

[plugin.suggestion_descriptor.surfaces.empty_state]
order = 40

[plugin.suggestion_descriptor.surfaces.empty_state.rationale]
zh = "让 magi 看到你在做什么项目"
en = "Lets magi see what you've been building"

[plugin.suggestion_descriptor.surfaces.first_context]
order = 40

[plugin.suggestion_descriptor.surfaces.first_context.rationale]
zh = "从提交记录中了解正在推进的项目"
en = "Understand active projects from recent commits"

[plugin.suggestion_descriptor.surfaces.first_context.scope]
zh = "最近 30 天的提交和分支活动"
en = "Commits and branch activity from the last 30 days"

[[plugin.suggestion_descriptor.local_requirements]]
check_kind = "executable_in_path"
names = ["git"]
```

## Categories

Pick one of the documented categories — or propose a new one in a PR if
yours doesn't fit. Current categories: `browser_history`, `code_activity`,
`calendar`, `screen_context`, `music`, `photos`, `messaging`, `terminal`,
`notes`.

Sibling plugins under one category (e.g., `safari-history` and
`chrome-history` both `browser_history`) are bundled by the host's
suggestion UI; users see a single card with multiple options.

## Recommendation surfaces

The base descriptor enables contextual suggestions in chat. Plugins opt into
other host surfaces explicitly:

- `surfaces.empty_state` controls whether the plugin can appear on empty source
  pages.
- `surfaces.first_context` controls whether the plugin can be offered during
  first-context onboarding.

Each surface owns its display `order` and may provide surface-specific
`rationale`. First-context entries should also provide a concise `scope` that
states what the initial read includes. The host does not maintain a plugin
allowlist, display copy, or ordering for these surfaces. Sibling plugins with the
same category are grouped automatically.

## Local requirements

AND-combined. All must pass for the plugin to be `available`. Supported
check kinds:

### `file_exists`

```toml
[[plugin.suggestion_descriptor.local_requirements]]
check_kind = "file_exists"

[plugin.suggestion_descriptor.local_requirements.paths_per_platform]
darwin = "~/Library/Application Support/Foo/data.db"
win32 = "%LOCALAPPDATA%/Foo/data.db"
linux = "~/.config/foo/data.db"
```

Path supports `~` (expanded to `$HOME`) and `$VAR` / `%VAR%`
environment-variable expansion. The platform key is one of
`darwin`/`win32`/`linux` — if your platform isn't listed for the current
device, the check fails.

### `executable_in_path`

```toml
[[plugin.suggestion_descriptor.local_requirements]]
check_kind = "executable_in_path"
names = ["git", "git.exe"]  # any one match passes
```

### `app_installed`

```toml
[[plugin.suggestion_descriptor.local_requirements]]
check_kind = "app_installed"

[plugin.suggestion_descriptor.local_requirements.identifier_per_platform]
darwin = "com.google.Chrome"          # macOS bundle id
linux  = "google-chrome"               # .desktop file basename
win32  = "Google Chrome"               # Uninstall registry DisplayName fragment
```

Note: on macOS, this uses `mdfind`. On Linux, scans well-known
applications directories. On Windows, the check is stubbed in the
initial release and returns `(false, "not yet implemented")` until the
registry-scan implementation lands.

## Localization

`triggers.keywords` is keyed by locale. Magi currently matches against
`zh` and `en`. Other locales will be added when the host adds them.
The base and surface-specific `rationale` values are required for both `zh` and
`en` when declared. `surfaces.first_context.scope` follows the same rule. These
strings appear verbatim in the corresponding UI.

## Trigger signal weights

The matcher weights signal types when computing a suggestion's
confidence:

- `intents` — weight 0.6
- `entities` — weight 0.3
- `keywords` — weight 0.1

Lean on intents when you can — they survive paraphrasing better than
keyword matches.

## Validation during development

The host validates manifests on plugin install. To validate locally:

```python
from magi_plugin_sdk.contracts import PluginManifest
import tomllib

with open("plugin.toml", "rb") as f:
    raw = tomllib.load(f)
manifest = PluginManifest.model_validate(raw["plugin"])
print(manifest.suggestion_descriptor)  # None if not declared, or the parsed block
```
