import { describe, expect, it } from 'vitest';
import { createInstance } from 'i18next';
import en from '@/i18n/locales/en/app.json';
import zh from '@/i18n/locales/zh-CN/app.json';
import { buildStartupReport, redactStartupText } from '@/runtime/startup-report';
import { startupDiagnostics } from './fixtures/startupDiagnostics';

const i18n = createInstance();
await i18n.init({ lng: 'en', resources: { en: { app: en }, 'zh-CN': { app: zh } }, interpolation: { escapeValue: false } });
const failure = { phase: 'connecting', startedAtMs: 1_730_000_000_000, failedAtMs: 1_730_000_002_000, durationMs: 2000 };

describe('startup reports', () => {
  it('includes native failure details and redacts every copied section', () => {
    const report = buildStartupReport(i18n.getFixedT('en', 'app'), 'Failed: session_token=summary-secret', startupDiagnostics({
      failureMessage: 'Bearer native-secret',
      logExcerpt: 'api_key=log-secret /Users/alice/.magi/data\n/home/bob/.magi/data\nC:\\Users\\Alice Smith\\AppData\\Local\\magi\nC:/Users/carol/AppData/Local/magi',
      logReadError: 'password=read-secret /Users/alice/Library/Logs/magi',
    }), failure);
    expect(report.text).toContain('Waiting for service listener');
    expect(report.text).toContain('1234 ms');
    expect(report.text).toContain('Process ID: 42');
    expect(report.text).toContain('Exit code: 7');
    expect(report.text).toContain('macos / 15.0 / aarch64');
    expect(report.text).toContain('0.1.34');
    expect(report.text).toContain('~/Library/Logs/magi/service.log');
    for (const secret of ['summary-secret', 'native-secret', 'log-secret', 'read-secret', 'alice', 'bob', 'Alice Smith', 'carol']) expect(report.text).not.toContain(secret);
    expect(report.text).toContain('[REDACTED]');
  });

  it('reports frontend timeouts or maintenance failures after native readiness', () => {
    const report = buildStartupReport(i18n.getFixedT('en', 'app'), 'Maintenance failed', startupDiagnostics({
      phase: 'ready', failedAtMs: null, failureMessage: null, durationMs: 10,
    }), { ...failure, phase: 'recovering_maintenance' });
    expect(report.text).toContain('Checking center maintenance');
    expect(report.text).toContain('2000 ms');
    expect(report.text).not.toContain('Almost ready');
  });

  it('labels fallback and bounded tails and translates metadata in Chinese', () => {
    const report = buildStartupReport(i18n.getFixedT('zh-CN', 'app'), '失败', startupDiagnostics({ logExcerptScope: 'fallback_tail', logExcerptTruncated: true }), failure);
    expect(report.text).toContain('日志末尾（无法确定本次启动范围）');
    expect(report.text).toContain('64 KiB');
    expect(report.text).toContain('应用版本: 0.1.34');
    expect(report.text).not.toContain('bootstrap.');
  });

  it('keeps a useful report when native diagnostics are unavailable', () => {
    const report = buildStartupReport(i18n.getFixedT('en', 'app'), 'Profiles unavailable', null, { ...failure, phase: 'profiles' });
    expect(report.text).toContain('Reading connection profiles');
    expect(report.text).toContain('2000 ms');
    expect(report.text).not.toContain('undefined');
    expect(report.logExcerpt).toBe('');
  });

  it('redacts credential URLs and JSON paths without changing useful filenames', () => {
    expect(redactStartupText('/Users/Alice Smith/Library/Logs/service.log')).toBe('~/Library/Logs/service.log');
    expect(redactStartupText('https://user:password@example.com/api?access_token=url-secret')).toBe('https://user:[REDACTED]@example.com/api?access_token=[REDACTED]');
    expect(redactStartupText(JSON.stringify({ path: 'C:\\Users\\alice\\AppData\\magi\\service.log' }))).toContain('service.log');
    expect(redactStartupText(JSON.stringify({ path: 'C:\\Users\\alice\\AppData\\magi\\service.log' }))).not.toContain('alice');
  });
});
