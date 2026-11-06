import type { TFunction } from 'i18next';
import type { ConnectionStartupDiagnostics } from './config';
import { redactLogText } from './log-redaction';

export interface StartupFailure {
  phase: string;
  startedAtMs: number;
  failedAtMs: number;
  durationMs: number;
}

export function redactStartupText(text: string): string {
  return redactLogText(text)
    .replace(/\/(?:Users|home)\/[^/\\"'\r\n]+/g, '~')
    .replace(/[A-Z]:[\\/]+Users[\\/]+[^\\/\r\n"']+/gi, '~');
}

export function buildStartupReport(
  t: TFunction<'app'>,
  error: string,
  diagnostics: ConnectionStartupDiagnostics | null,
  failure: StartupFailure,
) {
  const nativeFailure = diagnostics?.failedAtMs != null;
  const phase = nativeFailure ? diagnostics.phase : failure.phase;
  const metadata: [string, string][] = [
    [t('bootstrap.report.phase'), t(`bootstrap.phase.${phase}`, { defaultValue: phase })],
    [t('bootstrap.report.startedAt'), new Date(nativeFailure ? diagnostics.startedAtMs : failure.startedAtMs).toISOString()],
    [t('bootstrap.report.failedAt'), new Date(diagnostics?.failedAtMs ?? failure.failedAtMs).toISOString()],
    [t('bootstrap.report.duration'), `${nativeFailure ? diagnostics.durationMs : failure.durationMs} ms`],
  ];
  if (diagnostics) {
    metadata.push(
      [t('bootstrap.report.attempt'), diagnostics.attemptId],
      [t('bootstrap.report.version'), diagnostics.appVersion],
      [t('bootstrap.report.system'), [diagnostics.osName, diagnostics.osVersion, diagnostics.architecture].filter(Boolean).join(' / ')],
    );
    if (diagnostics.mode) metadata.push([t('bootstrap.report.mode'), t(`bootstrap.mode.${diagnostics.mode}`)]);
    if (diagnostics.processId != null) metadata.push([t('bootstrap.report.process'), String(diagnostics.processId)]);
    if (diagnostics.exitCode != null) metadata.push([t('bootstrap.report.exitCode'), String(diagnostics.exitCode)]);
  }
  const summary = redactStartupText(error);
  const logPath = redactStartupText(diagnostics?.logPath ?? '');
  const logExcerpt = redactStartupText(diagnostics?.logExcerpt ?? '');
  const logReadError = diagnostics?.logReadError
    ? redactStartupText(t('bootstrap.logReadError', { error: diagnostics.logReadError })) : '';
  const logLabel = t(diagnostics?.logExcerptScope === 'current_attempt' ? 'bootstrap.currentLogLabel'
    : diagnostics?.logExcerptScope === 'fallback_tail' ? 'bootstrap.fallbackLogLabel' : 'bootstrap.recentLogLabel');
  const logNotice = diagnostics?.logExcerptTruncated ? t('bootstrap.logTruncated') : '';
  const safeMetadata = metadata.map(([label, value]) => [label, redactStartupText(value)] as const);
  const sections = [
    `${t('bootstrap.summaryLabel')}\n${summary}`,
    safeMetadata.map(([label, value]) => `${label}: ${value}`).join('\n'),
  ];
  if (diagnostics?.failureMessage && diagnostics.failureMessage !== error) {
    sections.push(`${t('bootstrap.report.nativeError')}\n${redactStartupText(diagnostics.failureMessage)}`);
  }
  if (logPath) sections.push(`${t('bootstrap.logPathLabel')}\n${logPath}`);
  if (logExcerpt) sections.push(`${logLabel}\n${logNotice ? `${logNotice}\n` : ''}${logExcerpt}`);
  if (logReadError) sections.push(logReadError);
  return { metadata: safeMetadata, summary, logPath, logExcerpt, logLabel, logNotice, logReadError, text: sections.join('\n\n') };
}
