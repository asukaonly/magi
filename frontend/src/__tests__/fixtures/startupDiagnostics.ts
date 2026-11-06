import type { ConnectionStartupDiagnostics } from '@/runtime/config';

export const startupDiagnostics = (overrides: Partial<ConnectionStartupDiagnostics> = {}): ConnectionStartupDiagnostics => ({
  attemptId: 'ece92ced-5f84-4a33-9b20-6a1e4ce8bccf', appVersion: '0.1.34',
  osName: 'macos', osVersion: '15.0', architecture: 'aarch64', mode: 'local',
  phase: 'waiting_for_listener', startedAtMs: 1_730_000_000_000, failedAtMs: 1_730_000_001_234, durationMs: 1234,
  processId: 42, exitCode: 7, failureMessage: 'Listener failed',
  logPath: '/Users/alice/Library/Logs/magi/service.log', logExcerpt: 'Current startup failed',
  logReadError: null, logExcerptScope: 'current_attempt', logExcerptTruncated: false,
  ...overrides,
});
