import assert from 'node:assert/strict';
import { readFileSync, realpathSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { verifyPicomatchPatch } from './patch-picomatch.mjs';

const ADVISORY = 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf';
const PICOMATCH = 'node_modules/picomatch';
const REVIEWED_CONSUMERS = {
  'node_modules/tinyglobby': '0.2.17',
  'node_modules/tinyglobby/node_modules/fdir': '6.5.0',
  'node_modules/vite': '8.1.6',
  'node_modules/vitest': '4.1.12',
};
const SEVERITIES = new Set(['info', 'low', 'moderate', 'high', 'critical']);

function checkExceptionContext(lock) {
  assert.equal(lock.lockfileVersion, 3);
  assert.deepEqual(
    Object.keys(lock.packages).filter((name) => name.endsWith('/picomatch')),
    [PICOMATCH],
    'Picomatch installation paths changed',
  );
  assert.equal(lock.packages[PICOMATCH].version, '4.0.7', 'Unreviewed picomatch version');
  assert.equal(lock.packages[PICOMATCH].dev, true, 'Picomatch must remain dev-only');
  const consumers = Object.entries(lock.packages).filter(([, pkg]) =>
    ['dependencies', 'optionalDependencies', 'peerDependencies'].some((key) => pkg[key]?.picomatch),
  );
  assert.deepEqual(
    Object.fromEntries(consumers.map(([name, pkg]) => [name, pkg.version])),
    REVIEWED_CONSUMERS,
    'Picomatch dependency consumers changed',
  );
  for (const [name, pkg] of consumers) assert.equal(pkg.dev, true, `${name} must remain dev-only`);
}

export function evaluateAudit(report, lock) {
  assert.equal(report.auditReportVersion, 2, 'Unsupported npm audit report');
  assert(!report.error, 'npm audit returned an error');
  const entries = report.vulnerabilities;
  assert(entries && typeof entries === 'object' && !Array.isArray(entries), 'Missing audit findings');
  for (const [name, entry] of Object.entries(entries)) {
    assert.equal(entry.name, name, 'Invalid audit package name');
    assert(SEVERITIES.has(entry.severity), 'Invalid audit severity');
    assert(Array.isArray(entry.via) && entry.via.length > 0, 'Missing advisory causes');
    assert(Array.isArray(entry.nodes) && entry.nodes.length > 0, 'Missing affected installations');
    for (const node of entry.nodes) assert(lock.packages[node], `Unknown affected installation: ${node}`);
    for (const cause of entry.via) {
      if (typeof cause === 'string') assert(entries[cause], `Missing audit dependency: ${cause}`);
      else assert(cause && SEVERITIES.has(cause.severity) && typeof cause.url === 'string', 'Invalid advisory');
    }
  }

  const resolved = new Map();
  const allowed = (name, ancestors = new Set()) => {
    assert(!ancestors.has(name), `Cyclic audit dependency: ${name}`);
    if (resolved.has(name)) return resolved.get(name);
    const entry = entries[name];
    const causes = entry.via.map((cause) => {
      if (typeof cause === 'string') return allowed(cause, new Set([...ancestors, name]));
      if (!['high', 'critical'].includes(cause.severity)) return { allowed: true, excepted: false };
      if (name !== 'picomatch' || cause.name !== 'picomatch' || cause.url !== ADVISORY || cause.severity !== 'high') {
        return { allowed: false, excepted: false };
      }
      assert.deepEqual(entry.nodes, [PICOMATCH], 'Unreviewed affected picomatch installation');
      checkExceptionContext(lock);
      return { allowed: true, excepted: true };
    });
    const excepted = causes.some((cause) => cause.excepted);
    const result = {
      allowed: entry.severity !== 'critical' && causes.every((cause) => cause.allowed)
        && (entry.severity !== 'high' || excepted),
      excepted,
    };
    resolved.set(name, result);
    return result;
  };
  const rejected = Object.keys(entries).filter((name) => !allowed(name).allowed);
  return { rejected, excepted: [...resolved.values()].some((result) => result.excepted) };
}

function runCli() {
  verifyPicomatchPatch();
  const result = spawnSync('npm', ['audit', '--json'], {
    cwd: new URL('..', import.meta.url), encoding: 'utf8', maxBuffer: 8 * 1024 * 1024,
    shell: process.platform === 'win32',
  });
  assert(!result.error && [0, 1].includes(result.status), result.stderr || 'npm audit could not complete');
  const report = JSON.parse(result.stdout);
  console.log(JSON.stringify(report, null, 2));
  const lock = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url), 'utf8'));
  const { rejected, excepted } = evaluateAudit(report, lock);
  assert(result.status === 0 || Object.keys(report.vulnerabilities).length > 0, 'npm audit failed without findings');
  assert.equal(rejected.length, 0, `Unapproved build dependency advisories: ${rejected.join(', ')}`);
  if (excepted) console.log(`Verified local security patch for ${ADVISORY}. The registry release remains unfixed.`);
  console.log('Frontend build dependency audit passed.');
}

if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href) runCli();
