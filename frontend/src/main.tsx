import { CenterMaintenanceBoundary } from './components/connections/CenterMaintenanceBoundary';
import { CenterPathPickerHost } from './components/files/CenterPathPickerHost';
import { readDevicePreferences } from './runtime/device-preferences';
import { APP_EVENTS } from './constants/events';
import { setCenterStorageScope } from './runtime/center-storage';
import { recoverPendingCenterMaintenance } from './hooks/clearAllMemory';
import { ConnectionPicker } from './components/connections/ConnectionPicker';
import { listConnectionProfiles } from './runtime/connections';
/**
 * Application entry point.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { syncCloseToTrayPreference, syncAutoStartPreference, syncStartMinimizedPreference, syncSkipQuitConfirmationPreference, syncOnboardingCompleted, applyStartMinimized } from './runtime/desktop';
import { syncDesktopNotificationPreferences } from './runtime/desktop-notifications';
import { initializeDesktopLogging } from './runtime/logging';
import { scheduleStartupUpdateCheck } from './runtime/updater';
import { initializeTheme } from './stores/theme';
import { persistLanguageSelection, previewLanguageSelection } from './utils/settings-helpers';
import { shouldApplyConfigLanguagePreference } from './utils/language';
import { finishPendingCenterMaintenanceBeforeAppReady } from './runtime/fullDataClearBootstrap';
import { useFullDataClearInteractionGate } from './hooks/useFullDataClearInteractionGate';
import DesktopQuitPrompt from './components/layout/DesktopQuitPrompt';
import { PreAppWindowFrame } from './components/layout/PreAppWindowFrame';

initializeDesktopLogging();
initializeTheme();

const RuntimeBootstrap: React.FC = () => {
  const { t } = useTranslation('app');
  const [ready, setReady] = useState(false);
  const [choosingConnection, setChoosingConnection] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [diagnostics, setDiagnostics] = useState<BackendStartupDiagnostics | null>(null);
  const [diagnosticsCopied, setDiagnosticsCopied] = useState(false);
  const [phase, setPhase] = useState<StartupPhase>('spawning');
  const bootstrapGeneration = useRef(0);
  const logExcerptRef = useRef<HTMLPreElement>(null);
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
    const owner = ++bootstrapGeneration.current;
    const current = () => owner === bootstrapGeneration.current;
    setError(null);
    setDiagnostics(null);
    setDiagnosticsCopied(false);
    setReady(false);
    setPhase('spawning');
    try {
      const profiles = await listConnectionProfiles();
      if (!current()) return;
      if (!profiles.state.active_profile_id) { setChoosingConnection(true); return; }
      const runtime = await initializeRuntime((p) => { if (current()) setPhase(p); });
      if (!current()) return;
      if (!runtime.serverId || !runtime.contentEpoch) throw new Error('Center identity is missing');
      setCenterStorageScope(runtime.serverId, runtime.contentEpoch);
      configureApiClient({
        baseUrl: runtime.apiBaseUrl,
        sessionToken: runtime.sessionToken,
      });
      await finishPendingCenterMaintenanceBeforeAppReady(setPhase, {
        releaseInteractionGateWhenNotPending,
      });
      if (!current()) return;
      setPhase('connecting');
      try {
        const response = await configApi.get();
        if (!current()) return;
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
        const devicePrefs = readDevicePreferences();
        await syncCloseToTrayPreference(devicePrefs.close_to_tray_enabled);
        await syncOnboardingCompleted(prefs?.onboarding_completed ?? false);
        try {
          await syncAutoStartPreference(devicePrefs.auto_start_enabled);
        } catch {
          toast.error(i18n.t('settings.autoStartSyncFailed', { ns: 'app' }));
        }
        await syncStartMinimizedPreference(devicePrefs.start_minimized);
        await syncSkipQuitConfirmationPreference(devicePrefs.skip_quit_confirmation);
        syncDesktopNotificationPreferences(devicePrefs);
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
        // Config unavailable: keep the previous hide-to-tray fallback instead of
        // the not-onboarded default (which quits immediately on window close).
        await syncOnboardingCompleted(true);
        await syncCloseToTrayPreference(true);
        syncDesktopNotificationPreferences(null);
      }
      if (current()) setReady(true);
    } catch (err) {
      if (!current()) return;
      const message = err instanceof Error
        ? err.message
        : i18n.t('bootstrap.initializeFailedFallback', { ns: 'app' });
      setError(message);
      const detail = await readBackendStartupDiagnostics();
      if (current()) setDiagnostics(detail);
    }
  }, []);

  useEffect(() => {
    void bootstrap();
    return () => { bootstrapGeneration.current += 1; };
  }, [bootstrap]);

  useEffect(() => {
    if (!ready || fullDataClearGate.status !== 'idle') return;
    let current = true;
    let pending = false;
    const inspect = async () => {
      if (!current || pending) return;
      pending = true;
      try { await recoverPendingCenterMaintenance(); }
      catch { /* Connection failures remain visible through health and event status. */ }
      finally { pending = false; }
    };
    const timer = window.setInterval(() => { void inspect(); }, 10_000);
    const wake = () => { void inspect(); };
    window.addEventListener(APP_EVENTS.CENTER_STATE_CHANGED, wake);
    window.addEventListener('focus', wake);
    return () => { current = false; window.clearInterval(timer); window.removeEventListener(APP_EVENTS.CENTER_STATE_CHANGED, wake); window.removeEventListener('focus', wake); };
  }, [ready, fullDataClearGate.status]);

  useEffect(() => {
    if (error && diagnostics?.logExcerpt && logExcerptRef.current) {
      logExcerptRef.current.scrollTop = logExcerptRef.current.scrollHeight;
    }
  }, [diagnostics?.logExcerpt, error]);

  if (choosingConnection) return <PreAppWindowFrame><section className="mx-auto my-10 w-full max-w-xl rounded-md border border-border bg-card p-6"><h1 className="mb-4 text-xl font-semibold">{t('connections.choose')}</h1><ConnectionPicker /></section></PreAppWindowFrame>;

  if (ready) {
    return <CenterMaintenanceBoundary gate={fullDataClearGate} onRetry={() => {
      markFullDataClearRetrying();
      void recoverPendingCenterMaintenance(true).catch(() => { /* The maintenance owner exposes the retry result. */ });
    }}><App /></CenterMaintenanceBoundary>;
  }

  if (error) {
    const hasLogExcerpt = Boolean(diagnostics?.logExcerpt?.trim());
    const recoveringMaintenance = phase === 'recovering_maintenance';

    return (
      <PreAppWindowFrame>
        <div className="flex min-h-full items-center justify-center px-4 py-8 text-foreground">
          <section className="w-full max-w-4xl rounded-md border border-border bg-card p-6 text-left shadow-sm">
            <Button className="mb-4" variant="outline" onClick={() => setChoosingConnection(true)}>{t('connections.change')}</Button>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 space-y-2">
                <h1 className="text-xl font-semibold">
                  {t(recoveringMaintenance ? 'bootstrap.maintenanceRecoveryFailed' : 'bootstrap.startupFailed')}
                </h1>
                <p className="text-sm text-muted-foreground">
                  {t(recoveringMaintenance ? 'bootstrap.maintenanceRecoveryHint' : 'bootstrap.diagnosticsHint')}
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
                  <pre
                    ref={logExcerptRef}
                    className="m-0 max-h-[48vh] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted/40 p-3 font-mono text-xs leading-5 text-muted-foreground"
                  >
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
      </PreAppWindowFrame>
    );
  }

  return (
    <PreAppWindowFrame>
      <div className="flex min-h-full flex-col items-center justify-center gap-3">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
        <p className="text-sm text-muted-foreground">{t(`bootstrap.phase.${phase}`, t('bootstrap.starting'))}</p>
      </div>
    </PreAppWindowFrame>
  );
};

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <DesktopQuitPrompt />
    <RuntimeBootstrap />
    <CenterPathPickerHost />
  </React.StrictMode>
);
