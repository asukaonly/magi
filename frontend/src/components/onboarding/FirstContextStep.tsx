import { AlertCircle, CheckCircle2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { InstallableItem } from "@/api/modules/systemSuggestions";
import type { LLMConfig } from "@/api/modules/config";
import { EmptyStateAvailableSensors } from "@/components/empty-state/EmptyStateAvailableSensors";
import type { PluginInstallDoneInfo } from "@/stores/pluginInstallPanel";
import { getMemoryModelStatus } from "./memoryModelStatus";

interface FirstContextStepProps {
  llmConfig: LLMConfig;
  installableItems?: InstallableItem[];
  installableLoading?: boolean;
  installableError?: Error | null;
  onRetryInstallable?: () => void;
  connectedPluginIds?: string[];
  connectedCountsByPluginId?: Record<string, number | null>;
  onConnectDone: (pluginId: string, info?: PluginInstallDoneInfo) => void;
}

export function FirstContextStep({
  llmConfig,
  installableItems,
  installableLoading,
  installableError,
  onRetryInstallable,
  connectedPluginIds = [],
  connectedCountsByPluginId = {},
  onConnectDone,
}: FirstContextStepProps): JSX.Element {
  const { t } = useTranslation("onboarding");
  const memoryModelMissing = getMemoryModelStatus(llmConfig) === "missing";
  const connectedCount = connectedPluginIds.length;
  const preparedCount = connectedPluginIds.reduce((total, pluginId) => {
    const value = connectedCountsByPluginId[pluginId];
    return typeof value === "number" && Number.isFinite(value)
      ? total + value
      : total;
  }, 0);

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
              <span className="block font-medium">
                {t("firstContext.memoryWarningTitle")}
              </span>
              <span className="block text-xs leading-5 opacity-80">
                {t("firstContext.memoryWarningBody")}
              </span>
            </span>
          </div>
        ) : null}

        <div className="space-y-2">
          <h3 className="text-2xl font-semibold leading-8 text-foreground">
            {t("firstContext.title")}
          </h3>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
            {t("firstContext.body")}
          </p>
        </div>

        <div
          data-testid="first-context-scope-note"
          className="-mt-1 text-xs leading-5 text-muted-foreground"
        >
          {t("firstContext.scopeHint")}
        </div>

        {connectedCount > 0 ? (
          <div className="flex items-start gap-3 rounded-lg border border-primary/18 bg-primary/5 px-3.5 py-3 text-sm">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <span className="space-y-2">
              <span className="block font-medium text-foreground">
                {t("firstContext.connectedCount", { count: connectedCount })}
              </span>
              <span className="flex flex-wrap gap-1.5">
                {connectedPluginIds.map((pluginId) => (
                  <span
                    key={pluginId}
                    className="rounded-full border border-primary/15 bg-background/70 px-2 py-0.5 text-xs font-medium text-foreground"
                  >
                    {t(`pluginNames.${pluginId}`, { defaultValue: pluginId })}
                  </span>
                ))}
              </span>
              {preparedCount > 0 ? (
                <span className="block text-xs leading-5 text-muted-foreground">
                  {t("firstContext.preparedCount", { count: preparedCount })}
                </span>
              ) : (
                <span className="block text-xs leading-5 text-muted-foreground">
                  {t("firstContext.connectedHint")}
                </span>
              )}
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
          {t("firstContext.note")}
        </p>
      </div>
    </div>
  );
}

export default FirstContextStep;
