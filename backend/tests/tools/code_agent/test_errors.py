"""Tests for code_agent error hierarchy."""
import pytest

from magi.tools.code_agent.errors import (
    CodeAgentError,
    AdapterNotInstalled,
    AdapterUnauthorized,
    NotAGitRepoError,
    SensitivePathBlocked,
    DelegationTimeout,
)


def test_subclasses_are_code_agent_error():
    for cls in (
        AdapterNotInstalled,
        AdapterUnauthorized,
        NotAGitRepoError,
        SensitivePathBlocked,
        DelegationTimeout,
    ):
        assert issubclass(cls, CodeAgentError), cls
