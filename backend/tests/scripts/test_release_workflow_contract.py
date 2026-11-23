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


@pytest.mark.parametrize("result", ["success", "failure", "cancelled", "skipped"])
def test_ci_summary_requires_selected_jobs_to_succeed(tmp_path, result):
    jobs = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    aggregate = jobs["ci-result"]
    assert aggregate["if"] == "always()"
    plan = {"changes": {"result": "success", "outputs": {"backend": "true"}}}
    for name in aggregate["needs"]:
        if name != "changes":
            plan[name] = {"result": result if name == "backend" else "skipped"}
    command = aggregate["steps"][0]["run"]
    completed = subprocess.run(
        ["bash", "-euc", command], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "JOB_RESULTS": json.dumps(plan)}, timeout=10,
    )
    assert (completed.returncode == 0) == (result == "success"), completed.stderr
    marker = jobs["full-validation"]
    assert marker["needs"] == ["changes", "ci-result"]
    assert marker["if"] == "needs.changes.outputs.full == 'true'"


@pytest.mark.parametrize("event", ["push", "pull_request", "schedule", "workflow_dispatch"])
def test_backend_test_command_respects_scope_and_nightly_order(monkeypatch, event):
    jobs = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    backend = jobs["backend"]
    step = next(step for step in backend["steps"] if step["name"] == "Run backend test suite")
    assert backend["timeout-minutes"] == 105
    assert step["timeout-minutes"] == "${{ github.event_name == 'schedule' && 90 || 45 }}"
    commands = []
    monkeypatch.setenv("BACKEND_TEST_TARGETS", '["tests/speech", "tests/api"]')
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    monkeypatch.setattr(subprocess, "call", lambda command: commands.append(command) or 0)
    script = step["run"].split("\n", 1)[1].rsplit("PYTEST", 1)[0]
    with pytest.raises(SystemExit) as result:
        exec(script, {})
    assert result.value.code == 0
    assert commands[0][1:5] == ["-m", "pytest", "tests/speech", "tests/api"]
    assert ("-n" in commands[0]) == (event != "schedule")
    assert "faulthandler_timeout=120" in commands[0]


def _command_double(directory, name, source):
    path = directory / name
    path.write_text(f"#!{sys.executable}\n" + source, encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.mark.parametrize(
    "run_case,accepted",
    [
        ("success", True),
        ("partial", False),
        ("older_full", True),
        ("wrong_commit", False),
        ("failed", False),
        ("different_workflow", False),
        ("pull_request", False),
        ("different_branch", False),
        ("expired", False),
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
                "event": "pull_request" if run_case == "pull_request" else "push",
                "headBranch": "topic" if run_case == "different_branch" else "main",
                "headSha": "another-commit" if run_case == "wrong_commit" else "release-commit",
                "conclusion": "failure" if run_case == "failed" else "success",
                "workflow": "unrelated.yml" if run_case == "different_workflow" else "ci.yml",
            }
        ]
    )
    if run_case == "older_full":
        rows.insert(0, {**rows[0], "databaseId": 456})
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _command_double(
        bin_dir,
        "gh",
        """
import json, os, subprocess, sys
args = sys.argv[1:]
if args[0] == "api":
    assert "/actions/runs/123/artifacts?" in args[1], args
    assets = [{"name": "desktop-" + target, "expired": os.environ["RUN_CASE"] == "expired" and target.startswith("x86")}
             for target in ("aarch64-apple-darwin", "x86_64-pc-windows-msvc")]
    subprocess.run([os.environ["REAL_JQ"], "-r", args[args.index("--jq") + 1]],
                   input=json.dumps({"artifacts": assets}), text=True, check=True)
    sys.exit(0)
assert args[args.index("--repo") + 1] == "owner/repo"
if args[:2] == ["run", "view"]:
    assert '"Full validation"' in args[args.index("--jq") + 1]
    print("0" if os.environ["RUN_CASE"] == "partial" or args[2] == "456" else "1")
    sys.exit(0)
assert args[:2] == ["run", "list"], args
rows = json.loads(os.environ["FAKE_RUNS"])
for flag, key in [("--workflow", "workflow"), ("--commit", "headSha"), ("--status", "conclusion"), ("--branch", "headBranch")]:
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
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO_ROOT / "scripts/release-candidates.sh", tmp_path / "scripts")
    verify = next(step for step in jobs["verify-ci"]["steps"] if step.get("id") == "verify")
    result = subprocess.run(
        [bash, "-euo", "pipefail", "-c", verify["run"]],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=10,
        env={
            **os.environ,
            "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "GITHUB_REPOSITORY": "owner/repo",
            "GITHUB_SHA": "release-commit",
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "FAKE_RUNS": json.dumps(rows),
            "REAL_JQ": jq,
            "RUN_CASE": run_case,
        },
    )
    assert (result.returncode == 0) is accepted, result.stdout + result.stderr
    if accepted:
        assert (tmp_path / "output").read_text().strip() == "run_id=123"
    else:
        assert "No successful full ci.yml run" in result.stderr


_RELEASE_DOUBLE = """
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ["COMMAND_LOG"], "a") as log:
    log.write(json.dumps([name, *args]) + "\\n")
state = os.environ["FAKE_GIT_STATE"]
head_file = pathlib.Path(os.environ["FAKE_GIT_HEAD"])
if name == "git":
    if args == ["status", "--porcelain"]:
        print(" M VERSION" if state == "dirty" else "")
    elif args == ["branch", "--show-current"]:
        print("" if state == "detached" else "topic" if state == "feature" else "main")
    elif args[:1] == ["fetch"]:
        pass
    elif args == ["rev-parse", "HEAD"]:
        print(head_file.read_text())
    elif args == ["rev-parse", "refs/remotes/origin/main"]:
        print("remote-commit" if state in {"ahead", "behind", "diverged"} else "local-commit")
    elif args[:3] == ["rev-parse", "-q", "--verify"]:
        sys.exit(1)
    elif args[:2] == ["merge-base", "--is-ancestor"]:
        sys.exit(1 if state in {"behind", "diverged"} else 0)
    elif args[:1] == ["commit"]:
        head_file.write_text("release-commit")
    elif args[:1] not in (["add"], ["push"], ["tag"]):
        raise AssertionError(args)
elif name == "gh":
    if args[0] == "api":
        print("missing" if os.environ["FAKE_CI"] == "expired" and "/123/" in args[1] else "ready")
    elif args[:2] == ["run", "list"]:
        assert args[args.index("--workflow") + 1] == "ci.yml"
        expected_head = os.environ["EXPECTED_CI_HEAD"]
        assert args[args.index("--commit") + 1] == expected_head
        ci = os.environ["FAKE_CI"]
        if ci == "delayed" and not head_file.with_suffix(".registered").exists():
            head_file.with_suffix(".registered").touch()
        elif "--event" in args:
            assert args[args.index("--event") + 1] == "workflow_dispatch"
            if ci == "stale_manual" and not head_file.with_suffix(".stale").exists():
                head_file.with_suffix(".stale").touch()
                print("123")
            else:
                print("" if ci == "full_missing" else "124")
        else:
            print("" if ci == "missing" else "123")
    elif args[:2] == ["run", "view"]:
        ci = os.environ["FAKE_CI"]
        head_file.write_text("new-local-commit")
        if args[args.index("--json") + 1] == "jobs":
            assert '"Full validation"' in args[args.index("--jq") + 1]
            scoped = ci in {"partial", "stale_manual", "full_failure", "full_missing", "full_unconfirmed"}
            print("false" if (args[2] == "123" and scoped) or ci == "full_unconfirmed" else "true")
        elif ci == "transient" and not head_file.with_suffix(".retried").exists():
            head_file.with_suffix(".retried").touch()
            sys.exit(1)
        elif ci == "failure" or (args[2] == "124" and ci == "full_failure"):
            print("failure")
        else:
            print("success")
    elif args[:2] == ["workflow", "run"]:
        assert args == ["workflow", "run", "ci.yml", "--ref", "main"]
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
    shutil.copy(REPO_ROOT / "scripts/release-candidates.sh", root / "scripts")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("git", "gh", "python", "sleep"):
        _command_double(bin_dir, command, _RELEASE_DOUBLE)
    log = tmp_path / "commands.jsonl"
    head_file = tmp_path / "git-head"
    head_file.write_text("local-commit")
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
            "FAKE_GIT_HEAD": str(head_file),
            "EXPECTED_CI_HEAD": "local-commit" if mode == "resume" else "release-commit",
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
        assert ["git", "tag", "-a", f"v{version}", "local-commit" if mode == "resume" else "release-commit", "-m", f"Release v{version}"] in calls
        assert ["git", "push", "origin", f"v{version}"] in calls
        sync_calls = [
            call for call in calls if call[:3] == ["python", "scripts/release-version.py", "sync"]
        ]
        assert sync_calls == (
            [] if mode == "resume" else [["python", "scripts/release-version.py", "sync", version]]
        )


@pytest.mark.parametrize("ci", ["success", "partial", "expired", "stale_manual", "delayed", "transient", "failure", "missing", "full_failure", "full_missing", "full_unconfirmed"])
def test_release_creates_tag_only_after_successful_remote_ci(tmp_path, ci):
    result, calls = _run_release_script(tmp_path, state="aligned", ci=ci)
    assert ["git", "push", "origin", "release-commit:refs/heads/main"] in calls
    tag_calls = [call for call in calls if call[:2] == ["git", "tag"]]
    if ci in {"success", "partial", "expired", "stale_manual", "delayed", "transient"}:
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(tag_calls) == 1
        assert next(i for i, call in enumerate(calls) if call[:4] == ["gh", "run", "view", "123"]) < calls.index(tag_calls[0])
        dispatch = [call for call in calls if call[:2] == ["gh", "workflow"]]
        if ci in {"partial", "expired", "stale_manual"}:
            assert dispatch == [["gh", "workflow", "run", "ci.yml", "--ref", "main"]]
            assert next(i for i, call in enumerate(calls) if call[:4] == ["gh", "run", "view", "124"]) < calls.index(tag_calls[0])
        else:
            assert dispatch == []
    else:
        assert result.returncode != 0
        assert tag_calls == []
        assert [call for call in calls if call[:2] == ["git", "push"]] == [
            ["git", "push", "origin", "release-commit:refs/heads/main"]
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
    destination = tmp_path / "build/service"
    if entry == "desktop":
        if platform == "darwin":
            macos = json.loads((REPO_ROOT / "frontend/src-tauri/tauri.macos.conf.json").read_text())["bundle"]
            assert macos["resources"] == []
            source = macos["macOS"]["files"]["Resources/server-dist"]
            assert (tmp_path / "frontend/src-tauri" / source).resolve() == destination
            assert not (tmp_path / "frontend/src-tauri/server-dist").exists()
        else:
            destination = tmp_path / "frontend/src-tauri/server-dist"
    assert {path.name: path.read_bytes() for path in destination.iterdir()} == {
        binary: b"fixture service executable",
        "VERSION": b"1.2.3\n",
        "README.md": b"Bundled service\n",
    }


def test_workflow_wires_draft_desktop_and_signed_standalone_candidates():
    """Both platform uploads and the asset check must succeed before publication."""
    jobs = _workflow_jobs()
    steps = jobs["publish-tauri"]["steps"]
    builds = [step for step in steps if step.get("uses", "").startswith("tauri-apps/tauri-action@")]
    assert len(builds) == 1
    assert builds[0]["with"]["releaseDraft"] is True
    assert builds[0]["with"]["tagName"] == "${{ github.ref_name }}"
    assert builds[0]["with"]["releaseCommitish"] == "${{ github.event.repository.default_branch }}"
    assert any("check-release-tag.sh" in step.get("run", "") for step in steps[:steps.index(builds[0])])
    tauri_config = json.loads((REPO_ROOT / "frontend/src-tauri/tauri.conf.json").read_text())
    assert tauri_config["build"]["beforeBuildCommand"] == "node ../scripts/prepare-tauri-build.mjs"
    packages = [
        step for step in steps if "node scripts/package-service-macos.mjs" in step.get("run", "")
    ]
    assert len(packages) == 1
    assert "Magi.app/Contents/Resources/server-dist" in packages[0]["run"]
    assert "--signed-source" in packages[0]["run"]
    assert packages[0]["env"]["MAGI_REQUIRE_SERVICE_NOTARIZATION"] == "1"
    publish = jobs["publish-release"]
    assert publish["needs"] == "publish-tauri"
    assert jobs["publish-tauri"]["environment"] == "release"
    assert "environment" not in publish
    check, promote = publish["steps"][-2:]
    assert "scripts/check-release-assets.py" in check["run"]
    assert promote["run"].index("check-release-tag.sh") < promote["run"].index("--draft=false")
    assert not any("if" in item or "continue-on-error" in item for item in (publish, check, promote))


@pytest.mark.parametrize("defect", [None, "empty installer", "missing service", "missing platform", "wrong tag", "wrong URL", "wrong signature"])
def test_publication_checks_uploaded_assets_and_updater(tmp_path, defect):
    mac = "Magi_aarch64.app.tar.gz"
    win = "Magi_1.2.3_x64-setup.exe"
    service = "MagiServer_1.2.3_aarch64-apple-darwin.dmg"
    files = [win, mac, mac + ".sig", win + ".sig", "Magi_1.2.3_aarch64.dmg",
             service, service + ".json", service + ".sha256", "latest.json"]
    assets = [{"name": name, "size": 1, "state": "uploaded"} for name in files]
    platforms = {}
    for platform, bundle in [("darwin-aarch64", mac), ("windows-x86_64", win)]:
        (tmp_path / (bundle + ".sig")).write_text(platform + "\n")
        platforms[platform] = {"signature": platform, "url": f"https://github.com/org/repo/releases/download/v1.2.3/{bundle}"}
    if defect == "empty installer":
        assets[0]["size"] = 0
    if defect == "missing service":
        assets = [asset for asset in assets if asset["name"] != service]
    if defect == "missing platform":
        del platforms["windows-x86_64"]
    if defect == "wrong URL":
        platforms["darwin-aarch64"]["url"] += ".old"
    if defect == "wrong signature":
        platforms["darwin-aarch64"]["signature"] = "other"
    (tmp_path / "assets.json").write_text(json.dumps({"assets": assets}))
    (tmp_path / "latest.json").write_text(json.dumps({
        "version": "1.2.2" if defect == "wrong tag" else "1.2.3", "platforms": platforms,
    }))
    result = subprocess.run([sys.executable, REPO_ROOT / "scripts/check-release-assets.py",
                             tmp_path, "org/repo", "v1.2.3"], capture_output=True)
    assert (result.returncode == 0) == (defect is None), result.stderr


@pytest.mark.parametrize(
    "runner,target,relative",
    [
        ("macOS", "aarch64-apple-darwin", "macos/Magi.app/Contents/MacOS/magi-desktop"),
        ("Windows", "x86_64-pc-windows-msvc", "nsis/Magi_1.2.3_x64-setup.exe"),
    ],
)
def test_release_restores_the_candidate_archived_by_ci(tmp_path, runner, target, relative):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("Candidate archiving requires bash")
    ci = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    archive = next(s for s in ci["desktop-shell"]["steps"] if s["name"].startswith("Archive the checked"))
    restore = next(s for s in _workflow_jobs()["publish-tauri"]["steps"] if s["name"].startswith("Restore the checked"))
    build = tmp_path / "ci"
    release = tmp_path / "release"
    bundle = Path("target") / target / "release/bundle"
    binary = build / bundle / relative
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"checked candidate")
    binary.chmod(0o755)
    if runner == "macOS" and os.name != "nt":
        binary.with_name("link").symlink_to(binary.name)
    (build / "VERSION").write_text("1.2.3\n")
    subprocess.run([bash, "-euc", archive["run"]], cwd=build, check=True,
                   env={**os.environ, "RUNNER_OS": runner, "MAGI_BUILD_TARGET": target})
    release.mkdir()
    _command_double(tmp_path, "gh", """
import os, pathlib, shutil, sys
assert sys.argv[1:] == ["run", "download", "123", "--name", "desktop-" + os.environ["TARGET"], "--dir", "candidate"]
pathlib.Path("candidate").mkdir()
shutil.copy("../ci/desktop-candidate.tar", "candidate")
""")
    script = restore["run"].replace("${{ matrix.target }}", target).replace("${{ needs.verify-ci.outputs.run_id }}", "123")
    subprocess.run([bash, "-euc", script], cwd=release, check=True,
                   env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"], "TARGET": target})
    restored = release / bundle / relative
    assert restored.read_bytes() == binary.read_bytes()
    if runner == "macOS" and os.name != "nt":
        assert os.access(restored, os.X_OK)
        assert restored.with_name("link").readlink() == Path(binary.name)
