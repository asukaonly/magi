#!/usr/bin/env python3
"""Exercise dependency installer routing and failure handling without downloads."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().with_name("install-deps.sh")
COMMAND = r'''
import json, os
from pathlib import Path
import shutil, sys
args = sys.argv[1:]
name = Path(sys.argv[0]).name
with open(os.environ["INSTALL_TEST_LOG"], "a") as log:
    log.write(json.dumps({"command": str(Path(sys.argv[0])), "args": args}) + "\n")
stage = name
if args[:2] == ["-m", "venv"]:
    stage = "venv"
elif args[:1] == ["-c"]:
    stage = "runtime"
elif args and args[-1].endswith("[dev]"):
    stage = "backend"
if stage == os.environ.get("INSTALL_TEST_FAIL"):
    print("injected failure: " + stage, file=sys.stderr)
    sys.exit(23)
if stage == "venv":
    target = Path(args[2]) / "bin" / "python"
    target.parent.mkdir(parents=True)
    shutil.copy2(sys.argv[0], target)
'''


@unittest.skipIf(os.name == "nt", "The shell installer targets macOS and Linux")
class DependencyInstaller(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="magi-install-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "checkout with spaces"
        for directory in ("scripts", "frontend", "backend", "sdk"):
            (self.root / directory).mkdir(parents=True)
        shutil.copy2(SCRIPT, self.root / "scripts" / SCRIPT.name)
        self.commands = self.base / "commands"
        self.commands.mkdir()
        for name in ("npm", "cargo", "python3", "python", "pip"):
            self.command(self.commands / name)
        self.python = self.root / ".venv" / "bin" / "python"
        self.log = self.base / "calls.jsonl"
        self.env = {
            **os.environ,
            "PATH": f"{self.commands}:{os.environ['PATH']}",
            "VIRTUAL_ENV": str(self.base / "unrelated-environment"),
            "INSTALL_TEST_LOG": str(self.log),
        }

    def command(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!{sys.executable}\n{COMMAND}")
        path.chmod(0o755)

    def run_installer(self, fail=""):
        result = subprocess.run(
            ["bash", str(self.root / "scripts" / SCRIPT.name)],
            cwd=self.base,
            env={**self.env, "INSTALL_TEST_FAIL": fail},
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return result, calls

    def test_installs_speech_in_the_service_environment_despite_another_active_python(self):
        self.command(self.python)
        result, calls = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        installs = [call for call in calls if call["args"][:3] == ["-m", "pip", "install"]]
        self.assertTrue(installs)
        self.assertTrue(all(call["command"] == str(self.python) for call in installs))
        self.assertIn(str(self.root / "sdk"), [call["args"][-1] for call in installs])
        self.assertIn(str(self.root / "backend") + "[dev]", [call["args"][-1] for call in installs])
        runtime = next(call for call in calls if call["args"][:1] == ["-c"])
        self.assertEqual(runtime["command"], str(self.python))
        self.assertIn("from magi.utils.inference_runtime import validate_inference_runtime", runtime["args"][1])
        self.assertIn("validate_inference_runtime()", runtime["args"][1])
        self.assertEqual(Path(calls[-1]["command"]).name, "cargo")
        self.assertIn("All dependencies installed successfully.", result.stdout)

    def test_creates_the_service_environment_instead_of_installing_into_path_python(self):
        result, calls = self.run_installer()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.python.is_file())
        creators = [call for call in calls if call["args"][:2] == ["-m", "venv"]]
        self.assertEqual(len(creators), 1)
        self.assertEqual(creators[0]["args"][2], str(self.root / ".venv"))
        self.assertTrue(all(call["command"] == str(self.python) for call in calls if call["args"][:2] == ["-m", "pip"]))

    def test_dependency_failure_remains_visible_and_never_falls_back_to_a_partial_install(self):
        self.command(self.python)
        result, calls = self.run_installer("backend")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("injected failure: backend", result.stderr)
        self.assertNotIn("All dependencies installed successfully.", result.stdout)
        self.assertTrue(calls[-1]["args"][-1].endswith("[dev]"))
        self.assertFalse(any(Path(call["command"]).name == "cargo" for call in calls))

    def test_native_import_failure_stops_before_a_success_or_build(self):
        self.command(self.python)
        result, calls = self.run_installer("runtime")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("injected failure: runtime", result.stderr)
        self.assertEqual(calls[-1]["args"][0], "-c")
        self.assertNotIn("All dependencies installed successfully.", result.stdout)

    def test_other_failed_stages_cannot_report_success(self):
        for stage in ("npm", "venv", "cargo"):
            with self.subTest(stage=stage):
                if self.log.exists():
                    self.log.unlink()
                result, _calls = self.run_installer(stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"injected failure: {stage}", result.stderr)
                self.assertNotIn("All dependencies installed successfully.", result.stdout)

    def test_does_not_replace_an_incomplete_existing_environment(self):
        (self.root / ".venv").mkdir()
        marker = self.root / ".venv" / "keep"
        marker.write_text("existing environment")
        result, calls = self.run_installer()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Project environment is incomplete", result.stderr)
        self.assertEqual(marker.read_text(), "existing environment")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
