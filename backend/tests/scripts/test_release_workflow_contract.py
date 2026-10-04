"""Release policy checks with local command doubles and real script execution."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
RELEASE_WORKFLOW = REPO_ROOT / ".github/workflows/release.yml"


def _workflow_jobs():
    return yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _command_double(directory, name, source):
    path = directory / name
    path.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.mark.parametrize(
    "run_case,accepted",
    [
        ("success", True),
        ("wrong_commit", False),
        ("failed", False),
        ("different_workflow", False),
        ("missing", False),
    ],
)
def test_release_ci_verifier_executes_exact_commit_policy(tmp_path, run_case, accepted):
    jq = shutil.which("jq")
    bash = shutil.which("bash")
    if not jq or not bash:
        pytest.skip("Release verifier requires bash and jq")
    jobs = _workflow_jobs()
    assert jobs["publish-tauri"]["needs"] == "verify-ci"
    rows = (
        []
        if run_case == "missing"
        else [
            {
                "databaseId": 123,
                "headSha": "another-commit" if run_case == "wrong_commit" else "release-commit",
                "conclusion": "failure" if run_case == "failed" else "success",
                "workflow": "unrelated.yml" if run_case == "different_workflow" else "ci.yml",
            }
        ]
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _command_double(
        bin_dir,
        "gh",
        """
import json, os, subprocess, sys
args = sys.argv[1:]
assert args[:2] == ["run", "list"], args
assert args[args.index("--repo") + 1] == "owner/repo"
rows = json.loads(os.environ["FAKE_RUNS"])
for flag, key in [("--workflow", "workflow"), ("--commit", "headSha"), ("--status", "conclusion")]:
    if flag in args:
        rows = [row for row in rows if row[key] == args[args.index(flag) + 1]]
if "--jq" in args:
    result = subprocess.run([os.environ["REAL_JQ"], "-r", args[args.index("--jq") + 1]],
        input=json.dumps(rows), text=True, capture_output=True, check=True)
    value = result.stdout.strip()
    print("" if value == "null" else value)
else:
    print(json.dumps(rows))
""",
    )
    result = subprocess.run(
        [bash, "-euo", "pipefail", "-c", jobs["verify-ci"]["steps"][0]["run"]],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=10,
        env={
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_SHA": "release-commit",
            "FAKE_RUNS": json.dumps(rows),
            "REAL_JQ": jq,
        },
    )
    assert (result.returncode == 0) is accepted, result.stdout + result.stderr
    if accepted:
        assert "123" in result.stdout
    else:
        assert "No successful ci.yml run" in result.stderr


_RELEASE_DOUBLE = """
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
state = os.environ["FAKE_GIT_STATE"]
if name == "git":
    if args == ["status", "--porcelain"]:
        print(" M VERSION" if state == "dirty" else "")
    elif args == ["branch", "--show-current"]:
        print("" if state == "detached" else "topic" if state == "feature" else "main")
    elif args[:1] == ["fetch"]:
        pass
    elif args == ["rev-parse", "HEAD"]:
        print("local-commit")
    elif args == ["rev-parse", "refs/remotes/origin/main"]:
        print("remote-commit" if state in {"ahead", "behind", "diverged"} else "local-commit")
    elif args[:3] == ["rev-parse", "-q", "--verify"]:
        sys.exit(1)
    elif args[:2] == ["merge-base", "--is-ancestor"]:
        sys.exit(1 if state in {"behind", "diverged"} else 0)
    elif args[:1] not in (["add"], ["commit"], ["push"], ["tag"]):
        raise AssertionError(args)
elif name == "gh":
    if args[:2] == ["run", "list"]:
        assert args[args.index("--workflow") + 1] == "ci.yml"
        assert "local-commit" in args[args.index("-q") + 1]
        print("" if os.environ["FAKE_CI"] == "missing" else "123")
    elif args[:2] == ["run", "watch"]:
        assert args == ["run", "watch", "123", "--exit-status"]
        sys.exit(1 if os.environ["FAKE_CI"] == "failure" else 0)
    else:
        raise AssertionError(args)
elif name not in {"python", "sleep"}:
    raise AssertionError(name)
"""


def _run_release_script(tmp_path, *, state, mode="patch", ci="success"):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("Release script requires bash")
    root = tmp_path / "release-fixture"
    (root / "scripts").mkdir(parents=True)
    (root / "backend").mkdir()
    (root / "VERSION").write_text("1.2.3\n")
    script = root / "scripts/bump-release.sh"
    shutil.copyfile(REPO_ROOT / "scripts/bump-release.sh", script)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("git", "gh", "python", "sleep"):
        _command_double(bin_dir, command, _RELEASE_DOUBLE)
    log = tmp_path / "commands.jsonl"
    result = subprocess.run(
        [bash, str(script), mode],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=10,
        env={
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "COMMAND_LOG": str(log),
            "FAKE_GIT_STATE": state,
            "FAKE_CI": ci,
        },
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result, calls


@pytest.mark.parametrize(
    "state,mode,accepted",
    [
        ("dirty", "patch", False),
        ("detached", "patch", False),
        ("feature", "patch", False),
        ("ahead", "patch", False),
        ("behind", "patch", False),
        ("diverged", "patch", False),
        ("aligned", "patch", True),
        ("aligned", "resume", True),
        ("ahead", "resume", True),
        ("behind", "resume", False),
        ("diverged", "resume", False),
    ],
)
def test_release_preflight_blocks_mutations_until_branch_policy_passes(
    tmp_path, state, mode, accepted
):
    result, calls = _run_release_script(tmp_path, state=state, mode=mode)
    assert (result.returncode == 0) is accepted, result.stdout + result.stderr
    mutations = [
        call
        for call in calls
        if call[0] == "python"
        or call[:2]
        in (
            ["git", "add"],
            ["git", "commit"],
            ["git", "push"],
            ["git", "tag"],
        )
    ]
    if not accepted:
        assert mutations == []
    else:
        version = "1.2.3" if mode == "resume" else "1.2.4"
        assert ["python", "scripts/release-version.py", "validate", "--version", version] in calls
        assert ["git", "tag", "-a", f"v{version}", "-m", f"Release v{version}"] in calls
        assert ["git", "push", "origin", f"v{version}"] in calls
        sync_calls = [
            call for call in calls if call[:3] == ["python", "scripts/release-version.py", "sync"]
        ]
        assert sync_calls == (
            [] if mode == "resume" else [["python", "scripts/release-version.py", "sync", version]]
        )


@pytest.mark.parametrize("ci", ["success", "failure", "missing"])
def test_release_creates_tag_only_after_successful_remote_ci(tmp_path, ci):
    result, calls = _run_release_script(tmp_path, state="aligned", ci=ci)
    assert ["git", "push", "origin", "main"] in calls
    tag_calls = [call for call in calls if call[:2] == ["git", "tag"]]
    if ci == "success":
        assert result.returncode == 0
        assert len(tag_calls) == 1
        assert calls.index(["gh", "run", "watch", "123", "--exit-status"]) < calls.index(
            tag_calls[0]
        )
    else:
        assert result.returncode != 0
        assert tag_calls == []
        assert [call for call in calls if call[:2] == ["git", "push"]] == [
            ["git", "push", "origin", "main"]
        ]


@pytest.mark.parametrize("entry", ["desktop", "standalone"])
@pytest.mark.parametrize(
    "platform,target,binary",
    [
        ("darwin", "aarch64-apple-darwin", "magi-server"),
        ("win32", "x86_64-pc-windows-msvc", "magi-server.exe"),
    ],
)
def test_build_entries_invoke_one_service_and_sidecar_build(
    tmp_path, entry, platform, target, binary
):
    node = shutil.which("node")
    if not node:
        pytest.skip("Build entry tests require Node.js")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("prepare-service-bundle.mjs", "prepare-tauri-build.mjs"):
        shutil.copyfile(REPO_ROOT / "scripts" / name, scripts / name)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "server").mkdir()
    (tmp_path / "VERSION").write_text("1.2.3\n")
    (tmp_path / "server/README.md").write_text("Bundled service\n")
    output = tmp_path / "target" / target / "release"
    output.mkdir(parents=True)
    (output / binary).write_bytes(b"fixture service executable")
    script_name = "prepare-tauri-build.mjs" if entry == "desktop" else "prepare-service-bundle.mjs"
    harness = (
        """
import childProcess from 'node:child_process';
import { syncBuiltinESMExports } from 'node:module';
const calls = [];
childProcess.spawnSync = (command, args, options) => {
  calls.push([command, args]);
  return { status: 0, stdout: 'host: ignored-host\\n' };
};
syncBuiltinESMExports();
Object.defineProperty(process, 'platform', { value: PLATFORM });
process.env.MAGI_BUILD_TARGET = BUILD_TARGET_VALUE;
process.env.ComSpec = 'cmd.exe';
const entry = await import(ENTRY);
if (STANDALONE) entry.prepareServiceBundle();
console.log(JSON.stringify(calls));
""".replace("PLATFORM", json.dumps(platform))
        .replace("BUILD_TARGET_VALUE", json.dumps(target))
        .replace("ENTRY", json.dumps((scripts / script_name).as_uri()))
        .replace("STANDALONE", json.dumps(entry == "standalone"))
    )
    result = subprocess.run(
        [node, "--input-type=module", "-e", harness],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    calls = json.loads(result.stdout)
    frontend = (
        [["cmd.exe", ["/d", "/s", "/c", "npm run build"]]]
        if platform == "win32"
        else [["npm", ["run", "build"]]]
    )
    sidecar = (
        [
            "powershell.exe",
            ["-ExecutionPolicy", "Bypass", "-File", str(scripts / "build-sidecar.ps1")],
        ]
        if platform == "win32"
        else ["bash", [str(scripts / "build-sidecar.sh")]]
    )
    assert calls == (frontend if entry == "desktop" else []) + [
        ["rustc", ["-vV"]],
        ["cargo", ["build", "--locked", "--release", "-p", "magi-server", "--target", target]],
        sidecar,
    ]
    destination = tmp_path / (
        "frontend/src-tauri/server-dist" if entry == "desktop" else "build/service"
    )
    assert {path.name: path.read_bytes() for path in destination.iterdir()} == {
        binary: b"fixture service executable",
        "VERSION": b"1.2.3\n",
        "README.md": b"Bundled service\n",
    }


def test_workflow_wires_draft_desktop_and_signed_standalone_candidates():
    """Check declared release ownership; platform acceptance remains manual."""
    jobs = _workflow_jobs()
    steps = jobs["publish-tauri"]["steps"]
    builds = [step for step in steps if step.get("uses", "").startswith("tauri-apps/tauri-action@")]
    assert len(builds) == 1
    assert builds[0]["with"]["releaseDraft"] is True
    tauri_config = json.loads((REPO_ROOT / "frontend/src-tauri/tauri.conf.json").read_text())
    assert tauri_config["build"]["beforeBuildCommand"] == "node ../scripts/prepare-tauri-build.mjs"
    packages = [
        step for step in steps if "node scripts/package-service-macos.mjs" in step.get("run", "")
    ]
    assert len(packages) == 1
    assert "Magi.app/Contents/Resources/server-dist" in packages[0]["run"]
    assert "--signed-source" in packages[0]["run"]
    assert packages[0]["env"]["MAGI_REQUIRE_SERVICE_NOTARIZATION"] == "1"
