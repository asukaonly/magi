import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, ExternalLink } from 'lucide-react';
import type { SourceSyncFailure } from '@/api/modules/sources';
import { Button } from '@/components/ui/button';
import { getRuntimeConfig } from '@/runtime/config';
import { openExternalUrl } from '@/runtime/desktop';
import { useRequestOwner } from '@/hooks/useRequestOwner';
import { getErrorMessage } from '@/utils/error-handler';

type MacPrivacyPane = 'all_files' | 'calendars' | 'photos' | 'files_and_folders';

const MAC_PRIVACY_URLS: Record<MacPrivacyPane, string> = {
  all_files: 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles',
  calendars: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars',
  photos: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Photos',
  files_and_folders: 'x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders',
};

const MAC_PRIVACY_COPY_KEYS: Record<MacPrivacyPane, string> = {
  all_files: 'sourceRecovery.macFullDiskAccess',
  calendars: 'sourceRecovery.macCalendars',
  photos: 'sourceRecovery.macPhotos',
  files_and_folders: 'sourceRecovery.macFiles',
};

function resolveMacPrivacyPane(sourceName?: string | null): MacPrivacyPane {
  const normalized = (sourceName ?? '').trim().toLowerCase().replace(/-/g, '_');
  if (!normalized) return 'files_and_folders';
  if (
    normalized.includes('chrome') ||
    normalized.includes('safari') ||
    normalized.includes('edge') ||
    normalized.includes('arc') ||
    normalized.includes('brave') ||
    normalized.includes('firefox') ||
    normalized.includes('browser') ||
    normalized.includes('screen_time') ||
    normalized.includes('app_usage') ||
    normalized.includes('messages') ||
    normalized.includes('imessage') ||
    normalized.includes('mail') ||
    normalized.includes('notes')
  ) {
    return 'all_files';
  }
  if (normalized.includes('calendar')) return 'calendars';
  if (normalized.includes('photo')) return 'photos';
  return 'files_and_folders';
}

export function SourceSyncIssue({ message, failure, sourceName, onAuthorize }: {
  message: string;
  failure?: SourceSyncFailure | null;
  sourceName?: string | null;
  onAuthorize?: () => Promise<void>;
}) {
  const { t } = useTranslation('app');
  const [actionError, setActionError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const begin = useRequestOwner(JSON.stringify([message, failure, sourceName]));
  const permission = failure?.code === 'file_access_denied' || failure?.code === 'permission_required';
  const macFiles = failure?.code === 'file_access_denied' && failure.platform === 'darwin';
  const macPane = resolveMacPrivacyPane(sourceName);
  const remote = getRuntimeConfig().mode === 'remote';
  const act = async () => {
    const current = begin('recovery');
    setPending(true);
    setActionError(null);
    try {
      if (macFiles) {
        await openExternalUrl(MAC_PRIVACY_URLS[macPane]);
      } else if (onAuthorize) {
        await onAuthorize();
      }
    } catch (error) {
      if (current()) setActionError(getErrorMessage(error) || String(error));
    } finally {
      if (current()) setPending(false);
    }
  };
  return (
    <div role="alert" className="rounded-xl bg-muted/60 p-4 text-sm">
      <div className="flex items-start gap-3">
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden="true" />
        <div className="min-w-0 flex-1 space-y-2">
          <p className="font-medium">{t(permission ? 'sourceRecovery.permissionTitle' : 'sourceRecovery.failed')}</p>
          <p className="wrap-break-word text-muted-foreground wrap-anywhere">
            {permission ? t(remote ? 'sourceRecovery.remote' : macFiles ? MAC_PRIVACY_COPY_KEYS[macPane] : 'sourceRecovery.permissionHelp') : message}
          </p>
          {permission ? <details className="text-xs text-muted-foreground">
            <summary className="w-fit cursor-pointer py-1">{t('sourceRecovery.details')}</summary>
            <p className="mt-1 whitespace-pre-wrap wrap-break-word wrap-anywhere">{message}</p>
          </details> : null}
          {permission && !remote && (macFiles || onAuthorize) ? (
            <Button size="sm" variant="outline" disabled={pending} onClick={() => void act()}>
              <ExternalLink className="mr-2 h-3.5 w-3.5" aria-hidden="true" />
              {t(macFiles ? 'sourceRecovery.openSettings' : 'sourceRecovery.authorize')}
            </Button>
          ) : null}
          {actionError ? <p className="wrap-break-word text-destructive">{actionError}</p> : null}
        </div>
      </div>
    </div>
  );
}
