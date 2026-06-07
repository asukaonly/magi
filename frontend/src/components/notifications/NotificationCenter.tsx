import { useRef, useState } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNotifications } from '@/hooks/useNotifications';
import { useSuggestionDismissals } from '@/hooks/useSuggestionDismissals';
import { usePluginActivation } from '@/hooks/usePluginActivation';
import { PluginActivationDialog } from '@/components/plugins/PluginActivationDialog';
import { getEmptyStatePluginMeta } from '@/constants/emptyStatePriorities';
import type { NotificationItem } from '@/api/modules/notifications';

// A non-localized fallback rationale some plugin descriptors still emit
// (e.g. "connect chrome-history (zh)"). We never surface it verbatim.
const PLACEHOLDER_RATIONALE = /^connect .+\((zh|en)\)$/i;

function humanizePluginId(pluginId: string): string {
  return pluginId
    .split(/[-_]/)
    .filter(Boolean)
    .map((s) => s.charAt(0).toUpperCase() + s.slice(1))
    .join(' ');
}

export function NotificationCenter(): JSX.Element {
  const { t } = useTranslation('app');
  const { items, markRead, markAllRead, dismiss, dismissAll, act } = useNotifications();
  const { items: dismissed, refresh: refreshDismissed, clear: restore } = useSuggestionDismissals();
  const [showDismissed, setShowDismissed] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  // Dismissing a notification records a preferences-level dismissal, so refresh
  // the "已忽略" footer after each dismiss to keep the restore list in sync.
  const onDismiss = (id: number) => { void dismiss(id).then(refreshDismissed); };
  const onDismissAll = () => { void dismissAll().then(refreshDismissed); };
  // Notification id whose connect flow is in-flight. The server-side `action`
  // is recorded only after activation actually succeeds (onSuccess), not when
  // the dialog merely opens — so cancelling does not drop the item.
  const pendingActionId = useRef<number | null>(null);

  const { dialogState, installingPluginId, openDialog, closeDialog, confirm } = usePluginActivation({
    onSuccess: () => {
      const id = pendingActionId.current;
      pendingActionId.current = null;
      if (id != null) void act(id);
    },
  });

  // Human-readable plugin name: localized via the shared `pluginNames` map
  // (onboarding ns; same source the in-chat side card uses, so naming is
  // consistent), humanized id ("netease-music" → "Netease Music") as fallback.
  const pluginName = (pluginId: string): string =>
    t(`pluginNames.${pluginId}`, { ns: 'onboarding', defaultValue: humanizePluginId(pluginId) });

  // Short, plugin-centric collapsed title — distinct from the body so the same
  // sentence never appears twice. Replaces any placeholder rationale.
  const displayTitle = (n: NotificationItem): string => {
    const ids = n.payload.plugin_ids ?? [];
    if (ids.length > 0) {
      return t('notifications.suggestionTitle', { plugin: ids.map(pluginName).join('、') });
    }
    if (n.title && !PLACEHOLDER_RATIONALE.test(n.title)) return n.title;
    return t('notifications.suggestionTitleGeneric');
  };

  // The "why connect" line shown once when expanded: the rationale if it's
  // real, else the known plugin's value statement, else a generic hint.
  const description = (n: NotificationItem): string => {
    if (n.body && !PLACEHOLDER_RATIONALE.test(n.body)) return n.body;
    for (const pid of n.payload.plugin_ids ?? []) {
      const meta = getEmptyStatePluginMeta(pid);
      if (meta) {
        const v = t(meta.valueKey, { ns: 'onboarding' });
        if (v && v !== meta.valueKey) return v;
      }
    }
    return t('notifications.connectHint');
  };

  const toggle = (n: NotificationItem) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(n.id)) {
        next.delete(n.id);
      } else {
        next.add(n.id);
        if (n.status === 'unread') void markRead([n.id]);
      }
      return next;
    });
  };

  return (
    <div className="flex max-h-[70vh] w-full flex-col">
      <div className="flex items-center justify-between border-b border-border/55 px-4 py-2.5">
        <h3 className="text-sm font-medium text-foreground">{t('notifications.title')}</h3>
        {items.length > 0 ? (
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <button type="button" onClick={() => void markAllRead()} className="hover:text-foreground">
              {t('notifications.markAllRead')}
            </button>
            <button type="button" onClick={onDismissAll} className="hover:text-foreground">
              {t('notifications.clearAll')}
            </button>
          </div>
        ) : null}
      </div>

      {items.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground">{t('notifications.empty')}</p>
      ) : (
        <ul className="divide-y divide-border/55 overflow-y-auto">
          {items.map((n) => {
            const isExpanded = expanded.has(n.id);
            const ids = n.payload.plugin_ids ?? [];
            const installable = n.payload.installable_plugin_ids ?? [];
            const multi = ids.length > 1;
            return (
              <li key={n.id} data-testid="notification-row" className="group">
                <div className="flex items-start gap-2 px-4 py-2.5 hover:bg-muted/40">
                  <button
                    type="button"
                    onClick={() => toggle(n)}
                    className="flex min-w-0 flex-1 items-start gap-2 text-left"
                  >
                    {n.status === 'unread' ? (
                      <span aria-hidden className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" />
                    ) : (
                      <span className="mt-1.5 h-2 w-2 shrink-0" />
                    )}
                    <span
                      className={`min-w-0 flex-1 truncate text-sm ${
                        n.status === 'unread' ? 'font-medium text-foreground' : 'text-muted-foreground'
                      }`}
                    >
                      {displayTitle(n)}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={t('notifications.dismissAria')}
                    onClick={(e) => {
                      e.stopPropagation();
                      onDismiss(n.id);
                    }}
                    className="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground/50 opacity-0 transition hover:text-foreground group-hover:opacity-100"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
                {isExpanded ? (
                  <div className="space-y-2 px-4 pb-3 pl-8">
                    <p className="text-xs leading-relaxed text-muted-foreground">{description(n)}</p>
                    {ids.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {ids.map((pid) => {
                          const needsInstall = installable.includes(pid);
                          const isInstalling = installingPluginId === pid;
                          const base = isInstalling
                            ? t('notifications.installing')
                            : needsInstall
                              ? t('notifications.installAndConnect')
                              : t('notifications.connect');
                          return (
                            <button
                              key={pid}
                              type="button"
                              data-testid={`notification-connect-${pid}`}
                              disabled={isInstalling}
                              onClick={() => {
                                pendingActionId.current = n.id;
                                void openDialog(pid, { install: needsInstall });
                              }}
                              className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
                            >
                              {multi ? `${base} ${pluginName(pid)}` : base}
                            </button>
                          );
                        })}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {dismissed.length > 0 ? (
        <div className="border-t border-border/55">
          <button type="button" onClick={() => setShowDismissed((v) => !v)}
            className="flex w-full items-center justify-between px-4 py-2 text-xs text-muted-foreground hover:text-foreground">
            <span>{t('notifications.dismissedTitle')} ({dismissed.length})</span>
            <span aria-hidden>{showDismissed ? '▾' : '▸'}</span>
          </button>
          {showDismissed ? (
            <ul className="max-h-40 overflow-y-auto pb-2">
              {dismissed.map((d) => (
                <li key={d.dedupe_key} className="flex items-center justify-between px-4 py-1.5">
                  <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                    {d.title || humanizePluginId(d.dedupe_key)}
                  </span>
                  <button type="button"
                    onClick={() => { void restore(d.dedupe_key).then(refreshDismissed); }}
                    className="shrink-0 text-xs text-primary hover:underline">
                    {t('notifications.restore')}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {dialogState ? (
        <PluginActivationDialog
          open
          onClose={closeDialog}
          flow={dialogState.flow}
          initialValues={{}}
          onConfirm={confirm}
          pluginId={dialogState.pluginId}
        />
      ) : null}
    </div>
  );
}

export default NotificationCenter;
