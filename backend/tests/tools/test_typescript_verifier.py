"""Production-shaped tests for project-aware desktop verification."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from magi.tools.builtin import _verifiers
from magi.tools.builtin.verify_tool import VerifyTool
from magi.tools.schema import ToolExecutionContext

COMPILER = Path(__file__).resolve().parents[3] / "frontend" / "node_modules" / "typescript"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    assert shutil.which("node"), "Install Node to run project verifier integration tests"
    assert COMPILER.is_dir(), "Install frontend dependencies to run project verifier integration tests"
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "typescript").symlink_to(COMPILER, target_is_directory=True)
    (tmp_path / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {"strict": True, "jsx": "preserve", "types": [], "baseUrl": ".", "paths": {"@/*": ["src/*"]}},
        "include": ["src"],
    }))
    (tmp_path / "src").mkdir()
    return tmp_path


async def check(root: Path, *files: Path) -> dict:
    result = await VerifyTool().execute(
        {"mode": "paths", "paths": [str(file) for file in files], "timeout_s": 20},
        ToolExecutionContext(agent_id="test", workspace=str(root), env_vars={}),
    )
    assert result.success, result.error
    return result.data


@pytest.mark.asyncio
async def test_tsx_aliases_and_batch_use_one_project(project: Path, monkeypatch) -> None:
    value = project / "src" / "value.ts"
    value.write_text("export const value: number = 4;\n")
    view = project / "src" / "view.tsx"
    view.write_text(
        "import {value} from '@/value';\n"
        "declare global { namespace JSX { interface IntrinsicElements { div: {children?: number} } } }\n"
        "export const view = <div>{value}</div>;\n"
    )
    original = _verifiers._run_subprocess
    batches = []

    async def record(*args, **kwargs):
        result = await original(*args, **kwargs)
        batches.append(json.loads(result.stdout))
        return result

    monkeypatch.setattr(_verifiers, "_run_subprocess", record)
    result = await check(project, value, view)
    assert result["summary"]["pass"] == 2, result
    assert len(batches) == 1
    assert batches[0]["checked_project_count"] == 1
    assert all(row["project_path"] == str(project / "tsconfig.json") for row in result["results"])
    assert all(row["content_sha256"] and row["input_digest"] for row in result["results"])
    assert not list(project.rglob("*.tsbuildinfo"))


@pytest.mark.asyncio
async def test_real_type_error_fails(project: Path) -> None:
    target = project / "src" / "bad.ts"
    target.write_text("export const count: number = 'wrong';\n")
    result = await check(project, target)
    assert result["summary"]["fail"] == 1
    assert "TS2322" in result["results"][0]["stderr"]


@pytest.mark.asyncio
async def test_excluded_file_cannot_receive_project_evidence(project: Path) -> None:
    target = project / "excluded.ts"
    target.write_text("export const count: number = 1;\n")
    (project / "src" / "included.ts").write_text("export const count = 1;\n")
    result = await check(project, target)
    assert result["summary"]["skipped"] == 1
    assert "includes" in result["results"][0]["reason"]


@pytest.mark.asyncio
async def test_imported_file_is_checked_even_when_excluded_from_root_list(project: Path) -> None:
    target = project / "excluded.ts"
    target.write_text("export const count: number = 1;\n")
    (project / "src" / "included.ts").write_text("import {count} from '../excluded'; export const value = count;\n")
    result = await check(project, target)
    assert result["summary"]["pass"] == 1, result


@pytest.mark.asyncio
async def test_named_configuration_is_respected(project: Path) -> None:
    target = project / "tool.ts"
    target.write_text("export const value: number = 1;\n")
    (project / "tsconfig.tools.json").write_text(json.dumps({
        "compilerOptions": {"strict": True, "types": []}, "files": ["tool.ts"],
    }))
    result = await check(project, target)
    assert result["summary"]["pass"] == 1, result
    assert result["results"][0]["project_path"].endswith("tsconfig.tools.json")


@pytest.mark.asyncio
async def test_unbuilt_references_check_source_without_emitting(project: Path) -> None:
    lib = project / "lib"
    lib.mkdir()
    (lib / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {"composite": True, "types": []}, "files": ["value.ts"],
    }))
    (lib / "value.ts").write_text("export const value: number = 4;\n")
    config = json.loads((project / "tsconfig.json").read_text())
    config["references"] = [{"path": "./lib"}]
    (project / "tsconfig.json").write_text(json.dumps(config))
    target = project / "src" / "main.ts"
    target.write_text("import {value} from '../lib/value'; export const result: number = value;\n")
    result = await check(project, target)
    assert result["summary"]["pass"] == 1, result
    assert sorted(p.name for p in lib.iterdir()) == ["tsconfig.json", "value.ts"]
    (lib / "value.ts").write_text("export const value: number = 'broken';\n")
    result = await check(project, target)
    assert result["summary"]["fail"] == 1, result


@pytest.mark.asyncio
async def test_jsx_requires_a_project_checker(project: Path) -> None:
    config = json.loads((project / "tsconfig.json").read_text())
    config["compilerOptions"]["allowJs"] = True
    (project / "tsconfig.json").write_text(json.dumps(config))
    target = project / "src" / "view.jsx"
    target.write_text("export const view = <div />;\n")
    result = await check(project, target)
    assert result["summary"]["pass"] == 1, result
    assert result["results"][0]["check_kind"] == "syntax"


@pytest.mark.asyncio
async def test_missing_local_compiler_is_inconclusive(tmp_path: Path) -> None:
    target = tmp_path / "code.ts"
    target.write_text("const value: number = 1;\n")
    result = await check(tmp_path, target)
    assert result["summary"]["skipped"] == 1
    assert "TypeScript" in result["results"][0]["reason"]


@pytest.mark.asyncio
async def test_missing_node_is_inconclusive(project: Path, monkeypatch) -> None:
    target = project / "src" / "code.ts"
    target.write_text("const value: number = 1;\n")
    monkeypatch.setattr(_verifiers.shutil, "which", lambda *_args, **_kwargs: None)
    result = await check(project, target)
    assert result["summary"]["skipped"] == 1
    assert "Node" in result["results"][0]["reason"]


@pytest.mark.asyncio
async def test_python_check_does_not_launch_frozen_executable(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(_verifiers.sys, "executable", "/missing/frozen-sidecar")
    target = tmp_path / "code.py"
    target.write_text("raise RuntimeError('Do not execute this code')\n")
    result = await check(tmp_path, target)
    assert result["summary"]["pass"] == 1
    assert not (tmp_path / "__pycache__").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("relative", ["src/value.ts", "tsconfig.json"])
async def test_changed_project_input_invalidates_evidence(project: Path, monkeypatch, relative: str) -> None:
    value = project / "src" / "value.ts"
    value.write_text("export const value: number = 4;\n")
    target = project / "src" / "main.ts"
    target.write_text("import {value} from './value'; export const result = value;\n")
    hook = project / "mutate.cjs"
    hook.write_text(
        "const fs = require('node:fs'); const original = fs.readFileSync; let changed = false;\n"
        "fs.readFileSync = function(file, ...args) { const result = original.call(this, file, ...args);\n"
        f"if (!changed && String(file) === {json.dumps(str(project / relative))}) {{ "
        "changed = true; fs.appendFileSync(file, '\\n'); } return result; };\n"
    )
    monkeypatch.setenv("NODE_OPTIONS", f"--require={hook}")
    result = await check(project, target)
    assert result["summary"]["skipped"] == 1, result
    assert "inputs changed" in result["results"][0]["reason"]


@pytest.mark.asyncio
async def test_two_projects_keep_independent_results(project: Path) -> None:
    other = project / "other"
    other.mkdir()
    (other / "tsconfig.json").write_text(json.dumps({
        "compilerOptions": {"strict": True, "types": []}, "files": ["bad.ts"],
    }))
    good = project / "src" / "good.ts"
    bad = other / "bad.ts"
    good.write_text("export const count: number = 1;\n")
    bad.write_text("export const count: number = 'invalid';\n")
    result = await check(project, good, bad)
    assert [row["status"] for row in result["results"]] == ["pass", "fail"], result


@pytest.mark.asyncio
async def test_timeout_cannot_produce_passing_project_evidence(project: Path, monkeypatch) -> None:
    target = project / "src" / "code.ts"
    target.write_text("export const value = 1;\n")

    async def timeout(*_args, **_kwargs):
        return _verifiers.VerifyOutcome(
            path=str(project), verifier="typescript-project", status="timeout",
            exit_code=-1, stdout="", stderr="", reason="timeout", duration_ms=1000,
        )

    monkeypatch.setattr(_verifiers, "_run_subprocess", timeout)
    result = await check(project, target)
    assert result["summary"]["timeout"] == 1


@pytest.mark.asyncio
async def test_cancelled_checker_process_is_terminated(project: Path, monkeypatch) -> None:
    import asyncio
    import sys

    started = asyncio.Event()
    original = asyncio.create_subprocess_exec
    processes = []

    async def capture(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    task = asyncio.create_task(_verifiers._run_subprocess(
        "test", [sys.executable, "-c", "import time; time.sleep(60)"],
        rel_path=str(project), timeout_s=30,
    ))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[0].returncode is not None
