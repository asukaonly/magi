from __future__ import annotations

from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

import magi_plugin_sdk
from magi_plugin_sdk import subprocess as sdk_subprocess
from magi.tools.builtin import bash_tool, powershell_tool

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[3]
SDK_DISTRIBUTION_NAME = "magi-plugin-sdk"
SDK_SUBPROCESS_CONTRACT_VERSION = Version("0.1.1")


def _project_metadata(project_dir: str) -> dict[str, object]:
    pyproject_path = REPO_ROOT / project_dir / "pyproject.toml"
    parsed = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    return parsed["project"]


def _backend_sdk_requirement() -> Requirement:
    dependencies = _project_metadata("backend")["dependencies"]
    assert isinstance(dependencies, list)
    matches = [
        Requirement(value)
        for value in dependencies
        if canonicalize_name(Requirement(value).name) == canonicalize_name(SDK_DISTRIBUTION_NAME)
    ]
    assert len(matches) == 1
    return matches[0]


def test_sdk_runtime_version_matches_distribution_metadata() -> None:
    sdk_project = _project_metadata("sdk")

    assert sdk_project["name"] == SDK_DISTRIBUTION_NAME
    assert magi_plugin_sdk.__version__ == sdk_project["version"]


def test_backend_requires_the_sdk_subprocess_contract() -> None:
    sdk_version = Version(str(_project_metadata("sdk")["version"]))
    requirement = _backend_sdk_requirement()

    assert requirement.url is None
    assert requirement.marker is None
    assert not requirement.extras
    assert str(requirement.specifier) == f">={SDK_SUBPROCESS_CONTRACT_VERSION}"
    assert requirement.specifier.contains(sdk_version)


def test_shell_tools_import_the_current_sdk_subprocess_contract() -> None:
    assert bash_tool.BoundedStreamOutput is sdk_subprocess.BoundedStreamOutput
    assert bash_tool.BoundedSubprocessResult is sdk_subprocess.BoundedSubprocessResult
    assert bash_tool.run_bounded_subprocess is sdk_subprocess.run_bounded_subprocess
    assert powershell_tool.run_bounded_subprocess is sdk_subprocess.run_bounded_subprocess
