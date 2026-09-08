import { spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
mkdirSync(path.join(root, 'frontend/src-tauri/server-dist'), { recursive: true });
const build = spawnSync('cargo', ['build', '--locked', '-p', 'magi-server'], { cwd: root, stdio: 'inherit' });
if (build.error) throw build.error;
if (build.status !== 0) process.exit(build.status ?? 1);
const vite = spawnSync(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js')], { cwd: path.join(root, 'frontend'), stdio: 'inherit' });
if (vite.error) throw vite.error;
process.exit(vite.status ?? 1);
