/**
 * Application entry point.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { useTranslation } from 'react-i18next';
import { Copy, RotateCw } from 'lucide-react';
import { toast } from 'sonner';
import App from './App';
import './index.css';
import './i18n';
import i18n from './i18n';
import { configureApiClient } from './api/client';
import { configApi } from './api/modules/config';
import type { LanguageCode } from './api/modules/config';
import { initializeRuntime, readBackendStartupDiagnostics, resetRuntimeInitialization } from './runtime/config';
import type { BackendStartupDiagnostics, StartupPhase } from './runtime/config';
import { Button } from './components/ui/button';
import { syncCloseToTrayPreference, syncAutoStartPreference, syncStartMinimizedPreference, syncSkipQuitConfirmationPreference, applyStartMinimized } from './runtime/desktop';
import { syncDesktopNotificationPreferences } from './runtime/desktop-notifications';
import { initializeDesktopLogging } from './runtime/logging';
import { scheduleStartupUpdateCheck } from './runtime/updater';
import { initializeTheme } from './stores/theme';
import { persistLanguageSelection, previewLanguageSelection } from './utils/settings-helpers';
import { shouldApplyConfigLanguagePreference } from './utils/language';
import { finishPendingFullDataClearBeforeAppReady } from './runtime/fullDataClearBootstrap';
import { useFullDataClearInteractionGate } from './hooks/useFullDataClearInteractionGate';

initializeDesktopLogging();
initializeTheme();

const RuntimeBootstrap: React.FC = () => {
  const { t } = useTranslation('app');
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<BackendStartupDiagnostics | null>(null);
  const [diagnosticsCopied, setDiagnosticsCopied] = useState(false);
  const [phase, setPhase] = useState<StartupPhase>('spawning');
  const { gate: fullDataClearGate, markRetrying: markFullDataClearRetrying } = (
    useFullDataClearInteractionGate()
  );

  const diagnosticText = useMemo(() => {
    if (!error) {
      return '';
    }

    const sections = [`${t('bootstrap.summaryLabel')}\n${error}`];
    if (diagnostics?.logPath) {
      sections.push(`${t('bootstrap.logPathLabel')}\n${diagnostics.logPath}`);
    }
    if (diagnostics?.logExcerpt) {
      sections.push(`${t('bootstrap.recentLogLabel')}\n${diagnostics.logExcerpt}`);
    }
    if (diagnostics?.logReadError) {
      sections.push(`${t('bootstrap.logReadError', { error: diagnostics.logReadError })}`);
    }
    return sections.join('\n\n');
  }, [diagnostics, error, t]);

  const copyDiagnostics = useCallback(async () => {
    if (!diagnosticText || !navigator.clipboard) {
      return;
    }

    try {
      await navigator.clipboard.writeText(diagnosticText);
      setDiagnosticsCopied(true);
      window.setTimeout(() => setDiagnosticsCopied(false), 1600);
    } catch {
      setDiagnosticsCopied(false);
    }
  }, [diagnosticText]);

  const bootstrap = useCallback(async (
    releaseInteractionGateWhenNotPending = false,
  ) => {
    setError(null);
    setDiagnostics(null);
    setDiagnosticsCopied(false);
    setReady(false);
    setPhase('spawning');
    try {
      let runtime = await initializeRuntime((p) => setPhase(p));
      configureApiClient({
        baseUrl: runtime.apiBaseUrl,
        sessionToken: runtime.sessionToken,
      });
      const restartedRuntime = await finishPendingFullDataClearBeforeAppReady(setPhase, {
        releaseInteractionGateWhenNotPending,
      });
      if (restartedRuntime) {
        runtime = restartedRuntime;
        configureApiClient({
          baseUrl: runtime.apiBaseUrl,
          sessionToken: runtime.sessionToken,
        });
      }
      setPhase('connecting');
      try {
        const response = await configApi.get();
        const prefs = response.data?.preferences;
        if (
          prefs?.language
          && shouldApplyConfigLanguagePreference({
            onboardingCompleted: prefs.onboarding_completed,
          })
        ) {
          const lang = prefs.language as LanguageCode;
          persistLanguageSelection(lang);
          await previewLanguageSelection(lang);
        }
        await syncCloseToTrayPreference(prefs?.close_to_tray_enabled ?? true);
        await syncAutoStartPreference(prefs?.auto_start_enabled ?? false);
        await syncStartMinimizedPreference(prefs?.start_minimized ?? false);
        await syncSkipQuitConfirmationPreference(prefs?.skip_quit_confirmation ?? false);
        syncDesktopNotificationPreferences(prefs);
        await applyStartMinimized();
        void scheduleStartupUpdateCheck({
          network: response.data?.network,
          onUpdateAvailable: (result) => {
            if (!result.update) {
              return;
            }

            toast.info(i18n.t('settings.updates.availableToast', {
              ns: 'app',
              version: result.update.version,
            }));
          },
        });
      } catch {
        await syncCloseToTrayPreference(true);
        syncDesktopNotificationPreferences(null);
      }
      setReady(true);
    } catch (err) {
      const message = err instanceof Error
        ? err.message
        : i18n.t('bootstrap.initializeFailedFallback', { ns: 'app' });
      setError(message);
      setDiagnostics(await readBackendStartupDiagnostics());
    }
  }, []);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  if (ready && fullDataClearGate.status !== 'idle') {
    const failed = fullDataClearGate.status === 'failed';
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4 py-8 text-foreground">
        <section className="w-full max-w-xl rounded-md border border-border bg-card p-6 text-left shadow-sm">
          <div className="space-y-2">
            <h1 className="text-xl font-semibold">
              {t(failed ? 'bootstrap.dataClearRecoveryFailed' : 'bootstrap.dataClearInProgress')}
            </h1>
            <p className="text-sm text-muted-foreground">
              {t(failed ? 'bootstrap.dataClearRecoveryHint' : 'bootstrap.dataClearInProgressHint')}
            </p>
          </div>
          {failed ? (
            <>
              <pre className="mt-5 whitespace-pre-wrap break-words rounded-md border border-destructive/30 bg-destructive/5 p-3 font-mono text-xs leading-5 text-destructive">
                {fullDataClearGate.message}
              </pre>
              <Button
                className="mt-5"
                type="button"
                onClick={() => {
                  markFullDataClearRetrying();
                  resetRuntimeInitialization();
                  void bootstrap(true);
                }}
              >
                <RotateCw className="h-4 w-4" />
                {t('bootstrap.retry')}
              </Button>
            </>
          ) : (
            <div className="mt-5 h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
          )}
        </section>
      </div>
    );
  }

  if (ready) {
    return <App />;
  }

  if (error) {
    const hasLogExcerpt = Boolean(diagnostics?.logExcerpt?.trim());
    const recoveringDataClear = phase === 'recovering_data_clear';

    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4 py-8 text-foreground">
        <section className="w-full max-w-4xl rounded-md border border-border bg-card p-6 text-left shadow-sm">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0 space-y-2">
              <h1 className="text-xl font-semibold">
                {t(recoveringDataClear ? 'bootstrap.dataClearRecoveryFailed' : 'bootstrap.startupFailed')}
              </h1>
              <p className="text-sm text-muted-foreground">
                {t(recoveringDataClear ? 'bootstrap.dataClearRecoveryHint' : 'bootstrap.diagnosticsHint')}
              </p>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => void copyDiagnostics()}
                disabled={!diagnosticText}
              >
                <Copy className="h-4 w-4" />
                {diagnosticsCopied ? t('bootstrap.copiedDiagnostics') : t('bootstrap.copyDiagnostics')}
              </Button>
              <Button
                type="button"
                onClick={() => {
                  resetRuntimeInitialization();
                  void bootstrap();
                }}
              >
                <RotateCw className="h-4 w-4" />
                {t('bootstrap.retry')}
              </Button>
            </div>
          </div>

          <div className="mt-6 space-y-5">
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t('bootstrap.summaryLabel')}
              </p>
              <pre className="m-0 whitespace-pre-wrap break-words rounded-md border border-destructive/30 bg-destructive/5 p-3 font-mono text-xs leading-5 text-destructive">
                {error}
              </pre>
            </div>

            {diagnostics?.logPath ? (
              <div className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {t('bootstrap.logPathLabel')}
                </p>
                <p className="break-all rounded-md border border-border bg-muted/40 px-3 py-2 font-mono text-xs text-muted-foreground">
                  {diagnostics.logPath}
                </p>
              </div>
            ) : null}

            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t('bootstrap.recentLogLabel')}
              </p>
              {hasLogExcerpt ? (
                <pre className="m-0 max-h-[48vh] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted/40 p-3 font-mono text-xs leading-5 text-muted-foreground">
                  {diagnostics?.logExcerpt}
                </pre>
              ) : (
                <p className="rounded-md border border-border bg-muted/40 px-3 py-2 text-sm text-muted-foreground">
                  {diagnostics?.logReadError
                    ? t('bootstrap.logReadError', { error: diagnostics.logReadError })
                    : t('bootstrap.noLogAvailable')}
                </p>
              )}
            </div>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3">
      <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
      <p className="text-sm text-muted-foreground">{t(`bootstrap.phase.${phase}`, t('bootstrap.starting'))}</p>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RuntimeBootstrap />
  </React.StrictMode>
);
