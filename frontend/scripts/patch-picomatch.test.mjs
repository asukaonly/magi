import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { glob } from 'tinyglobby';
import { patchSource, verifyPicomatchPatch } from './patch-picomatch.mjs';

const root = fileURLToPath(new URL('..', import.meta.url));
const patchedSource = () => readFileSync(join(root, 'node_modules/picomatch/lib/parse.js'), 'utf8');

test('the installed patch is exact, idempotent and used by every locked consumer', () => {
  verifyPicomatchPatch();
  assert.equal(patchSource(patchedSource()), patchedSource());
  assert.throws(() => patchSource(`${patchedSource()}\n`), /Unreviewed picomatch/);
});

test('known ReDoS patterns are rejected before matching, including nested and opt-out forms', () => {
  const result = spawnSync(process.execPath, ['-e', `
    const assert = require('node:assert/strict');
    const pm = require('picomatch');
    for (const pattern of ['+(*)', '+(*a)', '*(*)', '**/+(*a).txt', '+(ab|abab)', '@(+(*a))', '*(a)']) {
      for (const options of [{}, { fastpaths: false }, { maxExtglobRecursion: false }, { capture: true }, { windows: true }]) {
        for (const compile of [pm, pm.makeRe, pm.parse]) {
          assert.throws(() => compile(pattern, options), /Repeated extglobs are disabled/);
        }
      }
    }
    assert(pm.isMatch('src/a.test.ts', '**/*.test.{ts,tsx}'));
    assert(pm.isMatch('src/a.tsx', '**/!(*.d).@(ts|tsx)'));
    assert(!pm.isMatch('src/a.d.ts', '**/!(*.d).@(ts|tsx)'));
    assert(pm.isMatch('src/file.js', 'src/**/?(test-)file.[jt]s'));
  `], { cwd: root, encoding: 'utf8', timeout: 5000 });
  assert.ifError(result.error);
  assert.equal(result.status, 0, result.stderr);
});

test('tinyglobby retains normal discovery and rejects dangerous patterns', async () => {
  const files = await glob('src/**/*.test.{ts,tsx}', { cwd: root });
  assert(files.length > 0);
  await assert.rejects(async () => glob('src/**/+(*a)', { cwd: root }), /Repeated extglobs are disabled/);
});

test('the audit entry point rejects an unpatched install before requesting advisories', (t) => {
  const temporary = mkdtempSync(join(tmpdir(), 'magi-picomatch-audit-'));
  t.after(() => rmSync(temporary, { recursive: true, force: true }));
  const parser = join(temporary, 'node_modules/picomatch/lib/parse.js');
  mkdirSync(dirname(parser), { recursive: true });
  writeFileSync(parser, 'unpatched source');
  mkdirSync(join(temporary, 'scripts'));
  for (const name of ['patch-picomatch.mjs', 'audit-build-dependencies.mjs']) {
    copyFileSync(join(root, 'scripts', name), join(temporary, 'scripts', name));
  }
  const result = spawnSync(process.execPath, [join(temporary, 'scripts/audit-build-dependencies.mjs')], {
    encoding: 'utf8', timeout: 5000,
  });
  assert.ifError(result.error);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /security patch is missing or modified/);
});

test('verification fails on missing, modified or shadowed parsers', (t) => {
  const temporary = mkdtempSync(join(tmpdir(), 'magi-picomatch-'));
  t.after(() => rmSync(temporary, { recursive: true, force: true }));
  const parser = join(temporary, 'node_modules/picomatch/lib/parse.js');
  mkdirSync(dirname(parser), { recursive: true });
  writeFileSync(join(temporary, 'package-lock.json'), JSON.stringify({
    packages: { 'node_modules/consumer': { dependencies: { picomatch: '^4' } } },
  }));
  assert.throws(() => verifyPicomatchPatch(temporary), /ENOENT/);
  writeFileSync(parser, 'unpatched source');
  assert.throws(() => verifyPicomatchPatch(temporary), /security patch is missing or modified/);
  writeFileSync(parser, patchedSource());
  verifyPicomatchPatch(temporary);
  const shadow = join(temporary, 'node_modules/consumer/node_modules/picomatch/lib/parse.js');
  mkdirSync(dirname(shadow), { recursive: true });
  writeFileSync(shadow, patchedSource());
  // Use a fresh process so Node's module-resolution cache cannot hide the new copy.
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', `
    import { verifyPicomatchPatch } from ${JSON.stringify(new URL('./patch-picomatch.mjs', import.meta.url).href)};
    verifyPicomatchPatch(${JSON.stringify(temporary)});
  `], { encoding: 'utf8', timeout: 5000 });
  assert.ifError(result.error);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /bypasses the patched parser/);
});
