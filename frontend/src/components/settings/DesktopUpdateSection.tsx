import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, RefreshCcw, RotateCcw } from 'lucide-react';
import type { Update } from '@tauri-apps/plugin-updater';

import type { NetworkProxyConfig } from '@/api/modules/config';
import { Button } from '@/components/ui/button';
import {
  buildUpdaterProxyUrl,
  checkForAppUpdate,
  DEFAULT_UPDATE_CHECK_TIMEOUT_MS,
  getCurrentAppVersion,
  isUpdaterRuntimeAvailable,
  restartToApplyUpdate,
} from '@/runtime/updater';
import { toast } from 'sonner';

const POST_BACKEND_STOP_QUIESCE_MS = 600;

async function stopBackendBeforeInstall(): Promise<void> {
  const { invoke } = await import('@tauri-apps/api/core');
  await invoke('stop_backend');
  // Give Windows a moment to release file handles on sidecar-dist binaries
  // before NSIS tries to overwrite them. Harmless on macOS/Linux.
  await new Promise((resolve) => setTimeout(resolve, POST_BACKEND_STOP_QUIESCE_MS));
}

async function restartBackendAfterInstallFailure(): Promise<void> {
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    await invoke('start_backend');
  } catch (error) {
    console.warn('[updater] failed to restart backend after install failure', {
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

interface DesktopUpdateSectionProps {
  networkConfig?: NetworkProxyConfig | null;
}

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

function serializeUpdaterError(error: unknown): Record<string, unknown> {
  if (error instanceof Error) {
    return {
      name: error.name,
      message: error.message,
      stack: error.stack ?? null,
    };
  }

  return {
    value: error,
  };
}

export function DesktopUpdateSection({ networkConfig }: DesktopUpdateSectionProps) {
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

    const proxy = buildUpdaterProxyUrl(networkConfig);
    console.info('[updater] manual update check requested from settings', {
      currentVersion,
      proxy: proxy ?? null,
      timeoutMs: DEFAULT_UPDATE_CHECK_TIMEOUT_MS,
    });

    setChecking(true);
    setInstalledVersion(null);
    setDownloadedBytes(0);
    setContentLength(null);

    try {
      const result = await checkForAppUpdate({
        proxy,
        timeoutMs: DEFAULT_UPDATE_CHECK_TIMEOUT_MS,
      });
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
      console.error('[updater] manual update check failed in settings', {
        currentVersion,
        proxy: proxy ?? null,
        error: serializeUpdaterError(error),
      });
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

    console.info('[updater] manual update install requested', {
      currentVersion,
      targetVersion: availableUpdate.version,
      releaseDate: availableUpdate.date ?? null,
    });

    setInstalling(true);
    setDownloadedBytes(0);
    setContentLength(null);

    let downloadCompleted = false;
    let backendStopped = false;

    try {
      let totalDownloadedBytes = 0;
      let expectedContentLength: number | null = null;
      let lastLoggedProgressBucket = -1;

      // 1) Download the installer while the backend is still serving the UI.
      await availableUpdate.download((event) => {
        switch (event.event) {
          case 'Started':
            setDownloadedBytes(0);
            setContentLength(event.data.contentLength ?? null);
            expectedContentLength = event.data.contentLength ?? null;
            lastLoggedProgressBucket = -1;
            console.info('[updater] update download started', {
              targetVersion: availableUpdate.version,
              contentLength: expectedContentLength,
            });
            break;
          case 'Progress':
            totalDownloadedBytes += event.data.chunkLength;
            setDownloadedBytes((value) => value + event.data.chunkLength);
            if (expectedContentLength && expectedContentLength > 0) {
              const progressPercent = Math.min(
                100,
                Math.round((totalDownloadedBytes / expectedContentLength) * 100)
              );
              const progressBucket = Math.floor(progressPercent / 10);

              if (progressBucket > lastLoggedProgressBucket) {
                lastLoggedProgressBucket = progressBucket;
                console.info('[updater] update download progress', {
                  targetVersion: availableUpdate.version,
                  downloadedBytes: totalDownloadedBytes,
                  contentLength: expectedContentLength,
                  progressPercent,
                });
              }
            }
            break;
          case 'Finished':
            console.info('[updater] update download finished', {
              targetVersion: availableUpdate.version,
              downloadedBytes: totalDownloadedBytes,
              contentLength: expectedContentLength,
            });
            break;
        }
      });
      downloadCompleted = true;

      // 2) Stop the Python sidecar before NSIS rewrites sidecar-dist binaries.
      // On Windows the sidecar holds file locks on _internal\*.pyd; without
      // this step the installer fails mid-extraction with a sharing violation.
      console.info('[updater] stopping backend before install', {
        targetVersion: availableUpdate.version,
      });
      await stopBackendBeforeInstall();
      backendStopped = true;

      // 3) Run the platform installer.
      await availableUpdate.install();

      const version = availableUpdate.version;
      await availableUpdate.close();
      setAvailableUpdate(null);
      setInstalledVersion(version);
      setDownloadedBytes(0);
      setContentLength(null);
      console.info('[updater] update download and install completed', {
        currentVersion,
        installedVersion: version,
      });
      toast.success(t('settings.updates.installSuccess', { version }));
    } catch (error: unknown) {
      console.error('[updater] update download or install failed', {
        currentVersion,
        targetVersion: availableUpdate.version,
        downloadCompleted,
        backendStopped,
        error: serializeUpdaterError(error),
      });

      // If we stopped the backend but the installer didn't take over, bring it
      // back so the UI isn't stranded without an API.
      if (backendStopped) {
        await restartBackendAfterInstallFailure();
      }

      const message = error instanceof Error ? error.message : t('settings.errorUnknown');
      toast.error(t('settings.updates.installFailed', { message }));
    } finally {
      setInstalling(false);
    }
  };

  const handleRestart = async () => {
    try {
      console.info('[updater] relaunch requested to apply installed update', {
        installedVersion,
      });
      await restartToApplyUpdate();
    } catch (error: unknown) {
      console.error('[updater] relaunch to apply update failed', {
        installedVersion,
        error: serializeUpdaterError(error),
      });
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

            <p className="text-xs leading-6 text-muted-foreground">
              {t('settings.updates.backgroundCheckHint')}
            </p>

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
