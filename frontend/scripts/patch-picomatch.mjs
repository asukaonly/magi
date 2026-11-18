import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync, realpathSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const ORIGINAL = '4e1e05447668aa1e94366c5516a2bcd8f5fff800cc92b1d0cd7d77703b8618c4';
const PATCHED = 'c1d392e215586cd6377b588b77451b75cd8b1b3700c060bd179ede7d14c22ed1';
const ANCHOR = '  const extglobOpen = (type, value) => {\n';
// shortcut: repeated extglobs are unsupported until a verified upstream fix replaces this restriction.
const REPLACEMENT = `${ANCHOR}    // Reject unbounded extglob repetition until upstream fixes GHSA-fc5q-39xc-vjpf.
    if (type === 'plus' || type === 'star') {
      throw new SyntaxError('Repeated extglobs are disabled by the Magi build security patch');
    }

`;
const hash = (source) => createHash('sha256').update(source).digest('hex');
const parserPath = (root) => join(root, 'node_modules/picomatch/lib/parse.js');

export function patchSource(source) {
  if (hash(source) === PATCHED) return source;
  assert.equal(hash(source), ORIGINAL, 'Unreviewed picomatch parser; review the security patch');
  const patched = source.replace(ANCHOR, REPLACEMENT);
  assert.equal(hash(patched), PATCHED, 'Picomatch security patch did not match');
  return patched;
}

export function verifyPicomatchPatch(root = ROOT) {
  const parser = parserPath(root);
  assert.equal(hash(readFileSync(parser)), PATCHED, 'Picomatch security patch is missing or modified; run npm ci');
  const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
  for (const [name, pkg] of Object.entries(lock.packages)) {
    if (!['dependencies', 'optionalDependencies', 'peerDependencies'].some((key) => pkg[key]?.picomatch)) continue;
    const require = createRequire(join(root, name, 'package.json'));
    assert.equal(realpathSync(require.resolve('picomatch/lib/parse')), realpathSync(parser), `${name} bypasses the patched parser`);
  }
}

function runCli() {
  assert(process.argv.length === 2 || (process.argv.length === 3 && process.argv[2] === '--check'));
  if (process.argv[2] !== '--check') {
    const path = parserPath(ROOT);
    const source = readFileSync(path, 'utf8');
    const patched = patchSource(source);
    if (patched !== source) writeFileSync(path, patched);
  }
  verifyPicomatchPatch();
  console.log('Verified picomatch security patch: repeated extglobs are disabled.');
}

if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href) runCli();
