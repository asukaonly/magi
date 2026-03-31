/**
 * Application entry point.
 */
import React, { useCallback, useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { useTranslation } from 'react-i18next';
import App from './App';
import './index.css';
import './i18n';
import { configureApiClient } from './api/client';
import { configApi } from './api/modules/config';
import { initializeRuntime, resetRuntimeInitialization } from './runtime/config';
import { syncCloseToTrayPreference } from './runtime/desktop';
import { initializeTheme } from './stores/theme';

initializeTheme();

const RuntimeBootstrap: React.FC = () => {
  const { t } = useTranslation('app');
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bootstrap = useCallback(async () => {
    setError(null);
    setReady(false);
    try {
      const runtime = await initializeRuntime();
      configureApiClient({
        baseUrl: runtime.apiBaseUrl,
        sessionToken: runtime.sessionToken,
      });
      try {
        const response = await configApi.get();
        const enabled = response.data?.preferences?.close_to_tray_enabled;
        await syncCloseToTrayPreference(enabled ?? true);
      } catch {
        await syncCloseToTrayPreference(true);
      }
      setReady(true);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to initialize runtime';
      setError(message);
    }
  }, []);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  if (ready) {
    return <App />;
  }

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
        <h1 className="text-xl font-semibold">{t('bootstrap.startupFailed')}</h1>
        <p className="max-w-xl text-sm text-muted-foreground">{error}</p>
        <button
          className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          onClick={() => {
            resetRuntimeInitialization();
            void bootstrap();
          }}
          type="button"
        >
          {t('bootstrap.retry')}
        </button>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center">
      <p className="text-sm text-muted-foreground">{t('bootstrap.starting')}</p>
    </div>
  );
};

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <RuntimeBootstrap />
  </React.StrictMode>
);
