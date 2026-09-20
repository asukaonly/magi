#!/usr/bin/env python3
"""Check development command routing without starting or registering services."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().with_name("dev-server.sh")


class DevelopmentCommands(unittest.TestCase):
    def test_commands_keep_the_selected_deployment_without_initializing_it(self):
        with tempfile.TemporaryDirectory(prefix="magi-dev-entry-") as directory:
            root = Path(directory)
            cargo = root / "cargo"
            cargo.write_text('#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n')
            cargo.chmod(0o755)
            env = {**os.environ, "HOME": str(root), "PATH": f"{root}:{os.environ['PATH']}"}
            config = root / ".config/magi-server/dev.json"
            for arguments in (["status"], ["status", "--details"], ["status", "--json"], ["logs", "--lines", "20"], ["config", "show"], ["run"], ["connect"], ["configure"], ["stop"]):
                result = subprocess.run([str(SCRIPT), *arguments], env=env, capture_output=True, text=True, check=True)
                args = json.loads(result.stdout)
                self.assertEqual(args[args.index("--") + 1:], ["--config", str(config), *arguments])
                self.assertFalse(config.exists())
                if arguments[0] == "status":
                    self.assertEqual(result.stderr, "")
            chosen = root / "config with spaces.json"
            result = subprocess.run([str(SCRIPT), "status", "--config", str(chosen)], env=env, capture_output=True, text=True, check=True)
            self.assertIn(str(chosen), json.loads(result.stdout))
            result = subprocess.run([str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            args = json.loads(result.stdout)
            self.assertIn("--development-root", args)
            self.assertIn(str(root / ".magi-center-dev"), args)
            self.assertFalse(config.exists())
            config.parent.mkdir(parents=True)
            config.write_text("existing config")
            result = subprocess.run([str(SCRIPT)], env=env, capture_output=True, text=True, check=True)
            self.assertNotIn("--development-root", json.loads(result.stdout))
            result = subprocess.run([str(SCRIPT), "collect", "status"], env=env, capture_output=True, text=True, check=True)
            args = json.loads(result.stdout)
            self.assertLess(args.index("--development-root"), args.index("collect"))
            result = subprocess.run([str(SCRIPT), "collect", "status", "--data-dir", str(root / "collector")], env=env, capture_output=True, text=True, check=True)
            args = json.loads(result.stdout)
            self.assertLess(args.index("--data-dir"), args.index("collect"))
            self.assertEqual(config.read_text(), "existing config")


if __name__ == "__main__":
    unittest.main()
