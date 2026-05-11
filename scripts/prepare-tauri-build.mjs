import { spawnSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const frontendDir = path.join(repoRoot, "frontend");

function run(command, args, cwd) {
  const result = spawnSync(command, args, {
    cwd,
    stdio: "inherit",
  });

  if (result.error) {
    throw result.error;
  }

  if (typeof result.status === "number" && result.status !== 0) {
    process.exit(result.status);
  }
}

if (process.platform === "win32") {
  run(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", "npm run build"], frontendDir);
} else {
  run("npm", ["run", "build"], frontendDir);
}

if (process.platform === "win32") {
  run(
    "powershell.exe",
    ["-ExecutionPolicy", "Bypass", "-File", path.join(scriptDir, "build-sidecar.ps1")],
    repoRoot,
  );
} else {
  run("bash", [path.join(scriptDir, "build-sidecar.sh")], repoRoot);
}
