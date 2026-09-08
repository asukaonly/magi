import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { copyFile, mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
function option(name) {
  const indices = args.flatMap((value, index) => value === name ? [index] : []);
  if (indices.length > 1) throw new Error(`Specify ${name} once`);
  if (!indices.length) return undefined;
  const value = args[indices[0] + 1];
  if (!value || value.startsWith('--')) throw new Error(`${name} requires a value`);
  return value;
}
function run(command, values, capture = false) {
  const result = spawnSync(command, values, { cwd: root, encoding: 'utf8', stdio: capture ? 'pipe' : 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`Service packaging failed: ${command} (${result.status})`);
  return result.stdout;
}

if (process.platform !== 'darwin') throw new Error('Standalone Mac images must be built on macOS');
for (let index = 0; index < args.length; index++) {
  if (['--source', '--target'].includes(args[index])) index++;
  else if (args[index] !== '--signed-source') throw new Error(`Unknown packaging option: ${args[index]}`);
}
const target = option('--target');
if (!['aarch64-apple-darwin', 'x86_64-apple-darwin'].includes(target)) throw new Error('Choose a supported Mac target');
const source = path.resolve(option('--source') || path.join(root, 'build/service'));
const version = (await readFile(path.join(root, 'VERSION'), 'utf8')).trim();
if (!/^\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?$/.test(version)) throw new Error('Invalid service version');
if ((await readFile(path.join(source, 'VERSION'), 'utf8')).trim() !== version) throw new Error('Service bundle version is stale');
run('/usr/bin/lipo', [path.join(source, 'magi-server'), '-verify_arch', target.startsWith('aarch64') ? 'arm64' : 'x86_64']);
const identity = process.env.APPLE_SIGNING_IDENTITY;
const canNotarize = identity && process.env.APPLE_ID && process.env.APPLE_PASSWORD && process.env.APPLE_TEAM_ID;
if (process.env.MAGI_REQUIRE_SERVICE_NOTARIZATION === '1' && !canNotarize) {
  throw new Error('Release service packages require signing and notarization credentials');
}
const output = path.join(root, 'build/packages');
await mkdir(output, { recursive: true });
const staging = await mkdtemp(path.join(output, '.service-'));
const image = path.join(output, `MagiServer_${version}_${target}.dmg`);
try {
  const payload = path.join(staging, 'MagiServer');
  run('/usr/bin/ditto', [source, payload]);
  await copyFile(path.join(root, 'server/README.md'), path.join(payload, 'README.md'));
  if (identity) {
    if (!args.includes('--signed-source')) {
      for (const name of ['sidecar-dist', 'plugin-python']) {
        run('/bin/bash', [path.join(root, 'scripts/sign-runtime-root-macos.sh'), path.join(payload, name), path.join(root, 'scripts/sidecar.entitlements.plist'), name]);
      }
      run('/usr/bin/codesign', ['--force', '--options', 'runtime', '--sign', identity, '--timestamp', path.join(payload, 'magi-server')]);
    }
    // Verify all code, including embedded Python libraries, before distribution.
    run('/bin/bash', ['-c', 'while IFS= read -r -d "" item; do if /usr/bin/file "$item" | /usr/bin/grep -q "Mach-O"; then /usr/bin/codesign --verify --strict "$item" || exit 1; fi; done < <(/usr/bin/find "$1" -type f -print0)', 'verify-service', payload]);
  }
  run('/usr/bin/hdiutil', ['create', '-volname', 'Magi Server', '-srcfolder', staging, '-ov', '-format', 'UDZO', image]);
  if (identity) run('/usr/bin/codesign', ['--force', '--sign', identity, '--timestamp', image]);
  if (canNotarize) {
    const notarization = JSON.parse(run('/usr/bin/xcrun', ['notarytool', 'submit', image, '--apple-id', process.env.APPLE_ID, '--password', process.env.APPLE_PASSWORD, '--team-id', process.env.APPLE_TEAM_ID, '--wait', '--timeout', '30m', '--output-format', 'json'], true));
    if (notarization.status !== 'Accepted') throw new Error('Apple did not accept the standalone service image');
    run('/usr/bin/xcrun', ['stapler', 'staple', image]);
    run('/usr/bin/xcrun', ['stapler', 'validate', image]);
  }
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(image)) hash.update(chunk);
  await writeFile(`${image}.sha256`, `${hash.digest('hex')}  ${path.basename(image)}\n`);
  await writeFile(`${image}.json`, JSON.stringify({ version, target, protocol: 1, signed: Boolean(identity), notarized: Boolean(canNotarize) }, null, 2) + '\n');
  process.stdout.write(`${image}\n`);
} finally {
  await rm(staging, { recursive: true, force: true });
}
