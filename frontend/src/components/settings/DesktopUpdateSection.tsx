import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, RefreshCcw, RotateCcw } from 'lucide-react';
import type { Update } from '@tauri-apps/plugin-updater';

import { Button } from '@/components/ui/button';
import {
  checkForAppUpdate,
  getCurrentAppVersion,
  isUpdaterRuntimeAvailable,
  restartToApplyUpdate,
} from '@/runtime/updater';
import { toast } from 'sonner';

function formatReleaseDate(value: string | undefined): string | null {
  if (!value) {
    return null;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString();
}

export function DesktopUpdateSection() {
  const { t } = useTranslation('app');
  const desktopRuntime = isUpdaterRuntimeAvailable();
  const [currentVersion, setCurrentVersion] = useState<string | null>(null);
  const [availableUpdate, setAvailableUpdate] = useState<Update | null>(null);
  const [checking, setChecking] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [downloadedBytes, setDownloadedBytes] = useState(0);
  const [contentLength, setContentLength] = useState<number | null>(null);
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);
  const [installedVersion, setInstalledVersion] = useState<string | null>(null);

  const progressPercent = contentLength && contentLength > 0
    ? Math.min(100, Math.round((downloadedBytes / contentLength) * 100))
    : null;

  useEffect(() => {
    let disposed = false;

    if (!desktopRuntime) {
      return () => {
        disposed = true;
      };
    }

    void getCurrentAppVersion()
      .then((version) => {
        if (!disposed) {
          setCurrentVersion(version);
        }
      })
      .catch(() => {
        if (!disposed) {
          setCurrentVersion(null);
        }
      });

    return () => {
      disposed = true;
      if (availableUpdate) {
        void availableUpdate.close();
      }
    };
  }, [availableUpdate, desktopRuntime]);

  const replaceAvailableUpdate = async (nextUpdate: Update | null) => {
    if (availableUpdate && availableUpdate !== nextUpdate) {
      await availableUpdate.close();
    }
    setAvailableUpdate(nextUpdate);
  };

  const handleCheckForUpdates = async () => {
    if (!desktopRuntime) {
      return;
    }

    setChecking(true);
    setInstalledVersion(null);
    setDownloadedBytes(0);
    setContentLength(null);

    try {
      const result = await checkForAppUpdate();
      setCurrentVersion(result.currentVersion);
      setLastCheckedAt(new Date());

      if (result.update) {
        await replaceAvailableUpdate(result.update);
        toast.success(t('settings.updates.availableToast', { version: result.update.version }));
      } else {
        await replaceAvailableUpdate(null);
        toast.success(t('settings.updates.upToDateToast'));
      }
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : t('settings.errorUnknown');
      toast.error(t('settings.updates.checkFailed', { message }));
    } finally {
      setChecking(false);
    }
  };

  const handleInstallUpdate = async () => {
    if (!availableUpdate) {
      return;
    }

    setInstalling(true);
    setDownloadedBytes(0);
    setContentLength(null);

    try {
      await availableUpdate.downloadAndInstall((event) => {
        switch (event.event) {
          case 'Started':
            setDownloadedBytes(0);
            setContentLength(event.data.contentLength ?? null);
            break;
          case 'Progress':
            setDownloadedBytes((value) => value + event.data.chunkLength);
            break;
          case 'Finished':
            break;
        }
      });

      const version = availableUpdate.version;
      await availableUpdate.close();
      setAvailableUpdate(null);
      setInstalledVersion(version);
      setDownloadedBytes(0);
      setContentLength(null);
      toast.success(t('settings.updates.installSuccess', { version }));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : t('settings.errorUnknown');
      toast.error(t('settings.updates.installFailed', { message }));
    } finally {
      setInstalling(false);
    }
  };

  const handleRestart = async () => {
    try {
      await restartToApplyUpdate();
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : t('settings.errorUnknown');
      toast.error(t('settings.updates.restartFailed', { message }));
    }
  };

  return (
    <section className="space-y-4">
      <h3 className="text-sm font-semibold tracking-[0.01em] text-foreground">
        {t('settings.updates.title')}
      </h3>

      <div className="space-y-4 rounded-xl border border-[hsl(var(--settings-subnav-border)/0.68)] bg-[hsl(var(--settings-shell-elevated)/0.54)] px-4 py-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
              {t('settings.updates.currentVersionLabel')}
            </div>
            <div className="text-sm font-medium text-foreground">
              {currentVersion ?? t('settings.updates.unavailableVersion')}
            </div>
          </div>

          <div className="space-y-1">
            <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground">
              {t('settings.updates.channelLabel')}
            </div>
            <div className="text-sm font-medium text-foreground">
              {t('settings.updates.channelValue')}
            </div>
          </div>
        </div>

        {!desktopRuntime ? (
          <p className="text-xs leading-6 text-muted-foreground">
            {t('settings.updates.desktopOnly')}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  void handleCheckForUpdates();
                }}
                disabled={checking || installing}
              >
                <RefreshCcw className="mr-2 h-4 w-4" />
                {checking ? t('settings.updates.checking') : t('settings.updates.checkAction')}
              </Button>

              {availableUpdate ? (
                <Button
                  type="button"
                  onClick={() => {
                    void handleInstallUpdate();
                  }}
                  disabled={installing || checking}
                >
                  <Download className="mr-2 h-4 w-4" />
                  {installing ? t('settings.updates.installing') : t('settings.updates.installAction')}
                </Button>
              ) : null}

              {installedVersion ? (
                <Button
                  type="button"
                  onClick={() => {
                    void handleRestart();
                  }}
                >
                  <RotateCcw className="mr-2 h-4 w-4" />
                  {t('settings.updates.restartAction')}
                </Button>
              ) : null}
            </div>

            {lastCheckedAt ? (
              <p className="text-xs text-muted-foreground">
                {t('settings.updates.lastChecked', {
                  time: lastCheckedAt.toLocaleString(),
                })}
              </p>
            ) : null}

            {availableUpdate ? (
              <div className="space-y-3 rounded-lg border border-primary/20 bg-primary/5 px-3 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-foreground">
                    {t('settings.updates.availableVersion', { version: availableUpdate.version })}
                  </span>
                  {availableUpdate.date ? (
                    <span className="text-xs text-muted-foreground">
                      {t('settings.updates.releaseDate', {
                        date: formatReleaseDate(availableUpdate.date) ?? availableUpdate.date,
                      })}
                    </span>
                  ) : null}
                </div>

                <p className="whitespace-pre-wrap text-xs leading-6 text-muted-foreground">
                  {availableUpdate.body?.trim() || t('settings.updates.noReleaseNotes')}
                </p>

                {installing ? (
                  <p className="text-xs text-muted-foreground">
                    {progressPercent !== null
                      ? t('settings.updates.downloadProgress', {
                          progress: progressPercent,
                        })
                      : t('settings.updates.downloadPreparing')}
                  </p>
                ) : null}
              </div>
            ) : null}

            {!availableUpdate && lastCheckedAt && !installedVersion ? (
              <p className="text-xs leading-6 text-muted-foreground">
                {t('settings.updates.upToDate')}
              </p>
            ) : null}

            {installedVersion ? (
              <p className="text-xs leading-6 text-muted-foreground">
                {t('settings.updates.restartHint', { version: installedVersion })}
              </p>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}
