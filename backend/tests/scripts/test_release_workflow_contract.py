"""Release workflow safety and build-efficiency contracts."""

import json
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release.yml"
TAURI_CONFIG = REPO_ROOT / "frontend" / "src-tauri" / "tauri.conf.json"
PREPARE_TAURI_BUILD = REPO_ROOT / "scripts" / "prepare-tauri-build.mjs"
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "bump-release.sh"


def _workflow_jobs() -> dict[str, object]:
    workflow = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]


def test_release_requires_successful_ci_for_exact_commit() -> None:
    jobs = _workflow_jobs()
    verify_job = jobs["verify-ci"]
    publish_job = jobs["publish-tauri"]

    assert publish_job["needs"] == "verify-ci"
    verify_script = verify_job["steps"][0]["run"]
    assert "--workflow ci.yml" in verify_script
    assert '--commit "${GITHUB_SHA}"' in verify_script
    assert "--status success" in verify_script
    assert "select(.headSha == env.GITHUB_SHA)" in verify_script


def test_release_matrix_only_runs_packaging_work() -> None:
    publish_job = _workflow_jobs()["publish-tauri"]
    steps = publish_job["steps"]
    step_names = {step["name"] for step in steps}

    ci_owned_steps = {
        "Run frontend validation",
        "Run backend smoke validation",
        "Run backend type gate",
        "Check gateway API contract",
        "Check SQLite ownership contract",
        "Export Python OpenAPI contract",
        "Run gateway validation",
        "Run headless evaluation client tests",
    }
    duplicate_sidecar_steps = {
        "Build Python sidecar (Unix)",
        "Build Python sidecar (Windows)",
    }

    assert step_names.isdisjoint(ci_owned_steps)
    assert step_names.isdisjoint(duplicate_sidecar_steps)
    assert "Build and publish Tauri bundle" in step_names

    install_script = next(
        step["run"] for step in steps if step["name"] == "Install backend dependencies"
    )
    assert 'pip install -e . pyinstaller' in install_script
    assert '.[dev]' not in install_script


def test_tauri_hook_remains_the_single_sidecar_build_owner() -> None:
    tauri_config = json.loads(TAURI_CONFIG.read_text(encoding="utf-8"))
    prepare_script = PREPARE_TAURI_BUILD.read_text(encoding="utf-8")

    assert tauri_config["build"]["beforeBuildCommand"] == "node ../scripts/prepare-tauri-build.mjs"
    assert prepare_script.count("build-sidecar.sh") == 1
    assert prepare_script.count("build-sidecar.ps1") == 1


def test_release_script_requires_up_to_date_main_branch() -> None:
    release_script = RELEASE_SCRIPT.read_text(encoding="utf-8")

    assert 'RELEASE_BRANCH="main"' in release_script
    assert '[[ "$BRANCH" != "$RELEASE_BRANCH" ]]' in release_script
    assert 'git fetch origin "$RELEASE_BRANCH"' in release_script
    assert '[[ "$HEAD_SHA" != "$REMOTE_MAIN_SHA" ]]' in release_script
    assert 'git merge-base --is-ancestor "$REMOTE_MAIN_SHA" "$HEAD_SHA"' in release_script
