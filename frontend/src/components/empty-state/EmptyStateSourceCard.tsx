import { Check } from "lucide-react";
import { useTranslation } from "react-i18next";
import { PluginIcon } from "@/components/plugins/PluginIcon";
import { cn } from "@/lib/utils";

export interface EmptyStateSourceCardProps {
  pluginId: string;
  title: string;
  value: string;
  iconId?: string;
  onConnect: (pluginId: string) => void;
  disabled?: boolean;
  i18nNamespace?: string;
  i18nKeyPrefix?: string;
  /**
   * i18n key for the connect button label. Defaults to `emptyState.connect`.
   * Consumers pass `emptyState.installAndConnect` for plugins that aren't yet
   * installed locally (registry install-first flow).
   */
  connectLabelKey?: string;
  variant?: "standard" | "first_context";
  connected?: boolean;
}

export function EmptyStateSourceCard({
  pluginId,
  title,
  value,
  iconId,
  onConnect,
  disabled,
  i18nNamespace = "onboarding",
  i18nKeyPrefix,
  connectLabelKey,
  variant = "standard",
  connected = false,
}: EmptyStateSourceCardProps): JSX.Element {
  const { t } = useTranslation(i18nNamespace);
  const keyed = (key: string) =>
    i18nKeyPrefix ? `${i18nKeyPrefix}.${key}` : key;
  const isFirstContext = variant === "first_context";

  return (
    <div
      className={cn(
        "grid min-w-0 items-center transition-colors",
        variant === "standard" &&
          "grid-cols-[2.75rem_minmax(0,1fr)_auto] gap-4 px-4 py-3.5 hover:bg-[hsl(var(--app-chrome-surface)/0.5)]",
        isFirstContext &&
          "grid-cols-[2rem_minmax(0,1fr)_auto] gap-3 py-5 sm:gap-5",
      )}
    >
      <span
        className={cn(
          "flex shrink-0 items-center justify-center",
          isFirstContext
            ? "h-8 w-8"
            : "h-11 w-11 rounded-lg bg-background/90 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.42)]",
        )}
      >
        <PluginIcon
          iconId={iconId}
          className={isFirstContext ? "h-7 w-7" : "h-6 w-6"}
        />
      </span>
      <div
        className={cn(
          "flex min-w-0 flex-col",
          isFirstContext ? "gap-1" : "gap-0.5",
        )}
      >
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3
            className={cn(
              "min-w-0 font-semibold text-foreground",
              isFirstContext ? "wrap-break-word text-[15px] leading-6" : "truncate text-sm",
            )}
          >
            {title}
          </h3>
        </div>
        {value ? (
          <p
            className={cn(
              "text-muted-foreground",
              isFirstContext
                ? "wrap-break-word text-sm leading-6"
                : "truncate text-xs leading-5",
            )}
          >
            {value}
          </p>
        ) : null}
      </div>
      {isFirstContext && connected ? (
        <span
          role="status"
          data-testid={`empty-state-connected-${pluginId}`}
          className="inline-flex min-w-20 items-center justify-end gap-1.5 whitespace-nowrap text-sm text-muted-foreground"
        >
          <Check className="h-4 w-4" aria-hidden="true" />
          {t(keyed("emptyState.connected"))}
        </span>
      ) : (
        <button
          type="button"
          data-testid={`empty-state-connect-${pluginId}`}
          aria-label={isFirstContext ? t(keyed("emptyState.connectApp"), { name: title }) : undefined}
          onClick={() => onConnect(pluginId)}
          disabled={disabled}
          className={cn(
            "shrink-0 rounded-md text-center font-medium transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2 disabled:opacity-50",
            isFirstContext
              ? "min-h-11 min-w-20 border border-border/80 bg-background/60 px-4 text-sm text-foreground hover:border-foreground/25 hover:bg-muted/60"
              : "border border-primary/30 bg-background px-3 py-1.5 text-xs font-semibold text-primary hover:border-primary/50 hover:bg-primary/10",
          )}
        >
          {t(keyed(connectLabelKey ?? "emptyState.connect"))}
        </button>
      )}
    </div>
  );
}
