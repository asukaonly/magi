"""Errors raised across the code_agent foundation."""
from __future__ import annotations


class CodeAgentError(Exception):
    """Base error for the code_agent package."""


class AdapterNotInstalled(CodeAgentError):
    """The external CLI binary was not found on PATH or in fallback locations."""


class AdapterUnauthorized(CodeAgentError):
    """The external CLI is installed but the user is not logged in."""


class NotAGitRepoError(CodeAgentError):
    """The workspace is not a git repository, so worktree-based delegation cannot run."""


class SensitivePathBlocked(CodeAgentError):
    """A path that matches the sensitive-path filter was passed where it is not allowed."""


class DelegationTimeout(CodeAgentError):
    """A delegation hit its hard timeout before producing a result."""
