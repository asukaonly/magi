import { AlertCircle, CheckCircle2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import type { InstallableItem } from '@/api/modules/systemSuggestions';
import type { LLMConfig } from '@/api/modules/config';
import { EmptyStateAvailableSensors } from '@/components/empty-state/EmptyStateAvailableSensors';
import { getMemoryModelStatus } from './memoryModelStatus';

interface FirstContextStepProps {
  llmConfig: LLMConfig;
  installableItems?: InstallableItem[];
  installableLoading?: boolean;
  installableError?: Error | null;
  connectedPluginIds?: string[];
  onRetryInstallable?: () => void;
  onConnectDone: (pluginId: string) => void;
}

export function FirstContextStep({
  llmConfig,
  installableItems,
  installableLoading,
  installableError,
  connectedPluginIds = [],
  onRetryInstallable,
  onConnectDone,
}: FirstContextStepProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  const memoryModelMissing = getMemoryModelStatus(llmConfig) === 'missing';
  const connectedCount = connectedPluginIds.length;

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 px-8 pb-7 pt-0 lg:pb-8 lg:pt-0">
        {memoryModelMissing ? (
          <div
            data-testid="first-context-memory-warning"
            className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50/80 px-3.5 py-3 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-200"
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <span className="space-y-1">
              <span className="block font-medium">{t('firstContext.memoryWarningTitle')}</span>
              <span className="block text-xs leading-5 opacity-80">
                {t('firstContext.memoryWarningBody')}
              </span>
            </span>
          </div>
        ) : null}

        <div className="space-y-2">
          <h3 className="text-2xl font-semibold leading-8 text-foreground">
            {t('firstContext.title')}
          </h3>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
            {t('firstContext.body')}
          </p>
        </div>

        {connectedCount > 0 ? (
          <div className="flex items-start gap-3 rounded-lg border border-primary/18 bg-primary/5 px-3.5 py-3 text-sm">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span className="space-y-1">
              <span className="block font-medium text-foreground">
                {t('firstContext.connectedCount', { count: connectedCount })}
              </span>
              <span className="block text-xs leading-5 text-muted-foreground">
                {t('firstContext.connectedHint')}
              </span>
            </span>
          </div>
        ) : null}

        <EmptyStateAvailableSensors
          variant="first_context"
          showBrowseAll={false}
          panelContext="first_context"
          excludePluginIds={connectedPluginIds}
          installableItems={installableItems}
          installableLoading={installableLoading}
          installableError={installableError}
          onRetryInstallable={onRetryInstallable}
          onConnectDone={onConnectDone}
        />

        <p className="text-xs leading-5 text-muted-foreground">
          {t('firstContext.note')}
        </p>
      </div>
    </div>
  );
}

export default FirstContextStep;
