import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const serviceBundle = path.join(root, 'build', 'service');

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`Service build failed: ${command} (${result.status})`);
}

export function prepareServiceBundle() {
  mkdirSync(serviceBundle, { recursive: true });
  const rustc = spawnSync('rustc', ['-vV'], { encoding: 'utf8' });
  if (rustc.status !== 0) throw new Error('Could not determine the Rust host target');
  const target = process.env.MAGI_BUILD_TARGET || process.env.CARGO_BUILD_TARGET || rustc.stdout.match(/^host: (.+)$/m)?.[1];
  if (!target || !/^[a-z0-9_-]+$/.test(target)) throw new Error('Invalid service build target');
  run('cargo', ['build', '--locked', '--release', '-p', 'magi-server', '--target', target]);
  if (process.platform === 'win32') {
    run('powershell.exe', ['-ExecutionPolicy', 'Bypass', '-File', path.join(root, 'scripts/build-sidecar.ps1')]);
  } else {
    run('bash', [path.join(root, 'scripts/build-sidecar.sh')]);
  }
  const binary = target.includes('windows') ? 'magi-server.exe' : 'magi-server';
  copyFileSync(path.join(root, 'target', target, 'release', binary), path.join(serviceBundle, binary));
  copyFileSync(path.join(root, 'VERSION'), path.join(serviceBundle, 'VERSION'));
  return { target, directory: serviceBundle };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  prepareServiceBundle();
}
