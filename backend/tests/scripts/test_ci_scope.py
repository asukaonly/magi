"""Dependency-free scope checks also run before CI chooses any expensive jobs."""

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("ci_scope", ROOT / "scripts/ci_scope.py")
scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scope)


class TestScope(unittest.TestCase):
    def test_frontend_source_only(self):
        plan = scope.select_scope(["frontend/src/pages/Chat.tsx"], ROOT)
        self.assertEqual({job for job in scope.JOBS if plan[job]}, {"frontend"})
        self.assertEqual(plan["backend_targets"], [])

    def test_native_changes_include_callers_and_security(self):
        for path in ["crates/magi-gateway/src/lib.rs", "server/src/main.rs", "Cargo.lock"]:
            with self.subTest(path=path):
                plan = scope.select_scope([path], ROOT)
                self.assertTrue(all(plan[job] for job in ("gateway", "desktop", "rust_security", "backend")))
                self.assertFalse(plan["plugin_runtime"])

    def test_desktop_and_frontend_configuration(self):
        plan = scope.select_scope(["frontend/src-tauri/src/main.rs"], ROOT)
        self.assertTrue(all(plan[job] for job in ("desktop", "frontend", "rust_security")))
        plan = scope.select_scope(["frontend/package-lock.json"], ROOT)
        self.assertTrue(all(plan[job] for job in ("frontend", "desktop", "backend")))

    def test_feature_groups_include_callers_and_lifecycle(self):
        for feature, groups in scope.FEATURE_TESTS.items():
            with self.subTest(feature=feature):
                plan = scope.select_scope([f"backend/src/magi/{feature}/service.py"], ROOT)
                self.assertTrue(plan["backend"] and plan["plugin_runtime"])
                self.assertFalse(plan["frontend"])
                self.assertNotIn("tests", plan["backend_targets"])
                self.assertTrue({f"tests/{group}" for group in groups}.issubset(plan["backend_targets"]))
                self.assertTrue({"tests/bootstrap", "tests/runtime", "tests/integration"}.issubset(plan["backend_targets"]))

    def test_shared_backend_uses_full_backend(self):
        for feature in ["memory", "agent", "runtime_trace", "skills", "tools", "db", "config"]:
            with self.subTest(feature=feature):
                plan = scope.select_scope([f"backend/src/magi/{feature}/service.py"], ROOT)
                self.assertEqual(plan["backend_targets"], ["tests"])
                self.assertFalse(plan["full"])
        plan = scope.select_scope(["backend/src/magi/api/routes.py"], ROOT)
        self.assertTrue(all(plan[job] for job in ("frontend", "gateway", "desktop")))

    def test_media_changes_include_timeline_consumers(self):
        plan = scope.select_scope(["backend/src/magi/media/selector.py"], ROOT)
        self.assertIn("tests/timeline", plan["backend_targets"])

    def test_test_only_changes_and_union(self):
        plan = scope.select_scope([
            "backend/tests/memory/test_store.py", "backend/tests/chat/test_session.py",
            "frontend/src/main.tsx",
        ], ROOT)
        self.assertEqual(plan["backend_targets"], ["tests/chat", "tests/memory"])
        self.assertTrue(plan["frontend"])
        self.assertFalse(plan["plugin_runtime"])
        for path in ["backend/tests/conftest.py", "backend/tests/agent/conftest.py", "backend/tests/_shared/fixtures.py"]:
            self.assertEqual(scope.select_scope([path], ROOT)["backend_targets"], ["tests"])

    def test_shared_and_unknown_inputs_require_every_job(self):
        for paths in [None, ["sdk/src/magi_sdk/models.py"], ["contracts/api/gateway_routes.json"],
                      ["scripts/ci_scope.py"], [".github/workflows/ci.yml"], ["VERSION"],
                      ["backend/pyinstaller-hooks/hook-chromadb.py"], ["frontend/src-tauri/tauri.conf.json"],
                      ["backend/pyproject.toml"], ["configs/config.yaml"], ["new-component/code.py"]]:
            with self.subTest(paths=paths):
                plan = scope.select_scope(paths, ROOT)
                self.assertTrue(plan["full"])
                self.assertTrue(all(plan[job] for job in scope.JOBS))
                self.assertEqual(plan["backend_targets"], ["tests"])

    def test_docs_only_and_runtime_doc_contract(self):
        plan = scope.select_scope(["docs/project-overview.md", "README.md"], ROOT)
        self.assertFalse(any(plan[job] for job in scope.JOBS))
        plan = scope.select_scope(["docs/task-agent-runtime-architecture.md"], ROOT)
        self.assertEqual(plan["backend_targets"], ["tests/runtime"])

    def test_removed_test_directory_falls_back_to_full_backend(self):
        plan = scope.select_scope(["backend/tests/removed_group/test_old.py"], ROOT)
        self.assertEqual(plan["backend_targets"], ["tests"])

    def test_non_diff_events_and_missing_baselines_require_full(self):
        for event in ["schedule", "workflow_dispatch", "unexpected"]:
            self.assertIsNone(scope.changed_paths(ROOT, event, {}))
        for before in ["0" * 40, "missing-commit", None]:
            self.assertIsNone(scope.changed_paths(ROOT, "push", {"before": before, "after": "HEAD"}))

    def test_complete_push_and_pr_diff_including_renames(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def git(*args):
                return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

            def commit(name):
                git("add", ".")
                git("-c", "user.name=CI Test", "-c", "user.email=ci@example.test", "commit", "-qm", name)
                return git("rev-parse", "HEAD")

            git("init", "-q")
            (root / "old name.py").write_text("original\n")
            base = commit("base")
            (root / "old name.py").rename(root / "new name.py")
            commit("rename")
            # Do not inherit GitHub path-filter limits or inspect only the latest commit.
            for index in range(305):
                (root / f"change-{index}.txt").write_text("change\n")
            head = commit("second change")
            expected = {"old name.py", "new name.py", *(f"change-{i}.txt" for i in range(305))}
            self.assertEqual(set(scope.changed_paths(root, "push", {"before": base, "after": head})), expected)
            git("checkout", "-q", "--detach", base)
            (root / "base-only.txt").write_text("unrelated base advancement\n")
            advanced = commit("advance base")
            event = {"pull_request": {"base": {"sha": advanced}, "head": {"sha": head}}}
            self.assertEqual(set(scope.changed_paths(root, "pull_request", event)), expected)


if __name__ == "__main__":
    unittest.main()
