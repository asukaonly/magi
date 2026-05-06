"""External coding CLI delegation foundation (probe / settings / worktree / bundle / diff)."""
from .contracts import (
    AdapterName,
    CostInfo,
    DelegateConstraints,
    DelegateRequest,
    DelegateResult,
    DiffSnapshot,
    DiffStats,
    ProbeResult,
    RunEvent,
    RunEventKind,
)
from .errors import (
    AdapterNotInstalled,
    AdapterUnauthorized,
    CodeAgentError,
    DelegationTimeout,
    NotAGitRepoError,
    SensitivePathBlocked,
)
from .context_bundle import ContextBundle, WrittenBundle, is_sensitive_path
from .diff_collector import collect_diff
from .probe import (
    PROBE_CACHE_TTL_S,
    PROBE_TIMEOUT_S,
    load_probe_cache,
    probe_all,
    probe_one,
    save_probe_cache,
)
from .settings import (
    ClaudeCodeSettings,
    CodeAgentSettings,
    CodexSettings,
    ConstraintsSettings,
    load_settings,
)
from .workspace import assert_git_repo, create_worktree, remove_worktree
from ._user_paths import (
    code_agent_probe_cache_path,
    code_agent_settings_path,
    magi_user_root,
)


__all__ = [
    "AdapterName",
    "CostInfo",
    "DelegateConstraints",
    "DelegateRequest",
    "DelegateResult",
    "DiffSnapshot",
    "DiffStats",
    "ProbeResult",
    "RunEvent",
    "RunEventKind",
    "AdapterNotInstalled",
    "AdapterUnauthorized",
    "CodeAgentError",
    "DelegationTimeout",
    "NotAGitRepoError",
    "SensitivePathBlocked",
    "ContextBundle",
    "WrittenBundle",
    "is_sensitive_path",
    "collect_diff",
    "PROBE_CACHE_TTL_S",
    "PROBE_TIMEOUT_S",
    "load_probe_cache",
    "probe_all",
    "probe_one",
    "save_probe_cache",
    "ClaudeCodeSettings",
    "CodeAgentSettings",
    "CodexSettings",
    "ConstraintsSettings",
    "load_settings",
    "assert_git_repo",
    "create_worktree",
    "remove_worktree",
    "code_agent_probe_cache_path",
    "code_agent_settings_path",
    "magi_user_root",
]
