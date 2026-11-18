import assert from 'node:assert/strict';
import { test } from 'node:test';
import { evaluateAudit } from './audit-build-dependencies.mjs';

const today = '2026-11-18';
const advisory = {
  name: 'picomatch', severity: 'high',
  url: 'https://github.com/advisories/GHSA-fc5q-39xc-vjpf',
};

function fixture() {
  const packages = {
    'node_modules/picomatch': { version: '4.0.7', dev: true },
    'node_modules/tinyglobby': { version: '0.2.17', dev: true, dependencies: { picomatch: '^4' } },
    'node_modules/tinyglobby/node_modules/fdir': { version: '6.5.0', dev: true, peerDependencies: { picomatch: '^3 || ^4' } },
    'node_modules/vite': { version: '8.1.6', dev: true, dependencies: { picomatch: '^4' } },
    'node_modules/vitest': { version: '4.1.12', dev: true, dependencies: { picomatch: '^4' } },
  };
  const entries = {
    picomatch: { via: [{ ...advisory }], nodes: ['node_modules/picomatch'] },
    fdir: { via: ['picomatch'], nodes: ['node_modules/tinyglobby/node_modules/fdir'] },
    tinyglobby: { via: ['fdir', 'picomatch'], nodes: ['node_modules/tinyglobby'] },
    vite: { via: ['tinyglobby', 'picomatch'], nodes: ['node_modules/vite'] },
    vitest: { via: ['vite', 'tinyglobby', 'picomatch'], nodes: ['node_modules/vitest'] },
  };
  return {
    lock: { lockfileVersion: 3, packages },
    report: { auditReportVersion: 2, vulnerabilities: Object.fromEntries(
      Object.entries(entries).map(([name, entry]) => [name, { name, severity: 'high', ...entry }]),
    ) },
  };
}

test('accepts the exact reviewed dev-only advisory and its propagated findings', () => {
  const { report, lock } = fixture();
  assert.deepEqual(evaluateAudit(report, lock, today), { rejected: [], excepted: true });
});

test('retains the high build threshold while allowing clean reports', () => {
  const { report, lock } = fixture();
  report.vulnerabilities = {};
  assert.deepEqual(evaluateAudit(report, lock, today), { rejected: [], excepted: false });
  report.vulnerabilities.vite = {
    name: 'vite', severity: 'moderate', nodes: ['node_modules/vite'],
    via: [{ name: 'vite', severity: 'moderate', url: 'https://example.test/advisory' }],
  };
  assert.deepEqual(evaluateAudit(report, lock, today), { rejected: [], excepted: false });
});

test('rejects another high advisory in the same package and every affected parent', () => {
  const { report, lock } = fixture();
  report.vulnerabilities.picomatch.via.push({ ...advisory, url: 'https://example.test/new-high' });
  assert.deepEqual(evaluateAudit(report, lock, today).rejected.sort(), ['fdir', 'picomatch', 'tinyglobby', 'vite', 'vitest']);
});

test('rejects independent high findings even when an approved cause is also present', () => {
  const { report, lock } = fixture();
  report.vulnerabilities.vite.via.push({ name: 'vite', severity: 'high', url: 'https://example.test/new-high' });
  assert.deepEqual(evaluateAudit(report, lock, today).rejected, ['vite', 'vitest']);
});

test('never excepts a critical advisory or a critical package finding', () => {
  for (const field of ['cause', 'package']) {
    const { report, lock } = fixture();
    if (field === 'cause') report.vulnerabilities.picomatch.via[0].severity = 'critical';
    else report.vulnerabilities.picomatch.severity = 'critical';
    assert(evaluateAudit(report, lock, today).rejected.includes('picomatch'));
  }
});

test('rejects a high finding without a reviewed high cause', () => {
  const { report, lock } = fixture();
  report.vulnerabilities.vite.via = [{ name: 'vite', severity: 'moderate', url: 'https://example.test/cause' }];
  assert(evaluateAudit(report, lock, today).rejected.includes('vite'));
});

test('rejects changed versions, consumers, paths and production dependencies', () => {
  const changes = [
    (lock) => { lock.packages['node_modules/picomatch'].version = '4.0.8'; },
    (lock) => { lock.packages['node_modules/picomatch'].dev = false; },
    (lock) => { lock.packages['node_modules/vite'].dev = false; },
    (lock) => { lock.packages['node_modules/vite'].version = '8.2.0'; },
    (lock) => { delete lock.packages['node_modules/vite'].dependencies.picomatch; },
    (lock) => { lock.packages['node_modules/extra'] = { version: '1.0.0', dev: true, dependencies: { picomatch: '^4' } }; },
    (lock) => { lock.packages['node_modules/extra/node_modules/picomatch'] = { version: '4.0.7', dev: true }; },
  ];
  for (const change of changes) {
    const { report, lock } = fixture();
    change(lock);
    assert.throws(() => evaluateAudit(report, lock, today));
  }
});

test('requires another review on the deadline', () => {
  const { report, lock } = fixture();
  assert.throws(() => evaluateAudit(report, lock, '2026-12-18'), /requires review/);
});

test('fails closed on audit errors, missing causes and cyclic references', () => {
  const changes = [
    (report) => { report.error = { code: 'ENOAUDIT' }; },
    (report) => { delete report.auditReportVersion; },
    (report) => { delete report.vulnerabilities; },
    (report) => { report.vulnerabilities.vite.via = []; },
    (report) => { report.vulnerabilities.vite.via = ['missing']; },
    (report) => { report.vulnerabilities.vite.via = ['vitest']; },
    (report) => { report.vulnerabilities.vite.via = [{ severity: 'unexpected' }]; },
    (report) => { report.vulnerabilities.picomatch.nodes = ['node_modules/missing']; },
  ];
  for (const change of changes) {
    const { report, lock } = fixture();
    change(report);
    assert.throws(() => evaluateAudit(report, lock, today));
  }
});
