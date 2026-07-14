import { useState } from 'react';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNotifications } from '@/hooks/useNotifications';
import { useSuggestionDismissals } from '@/hooks/useSuggestionDismissals';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';
import { resolveConflict } from '@/api/modules/notifications';
import type { NotificationItem } from '@/api/modules/notifications';
import type { SuggestionPlugin } from '@/api/modules/systemSuggestions';
import { localizedPluginText } from '@/utils/plugin-display-groups';

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
  const { t, i18n } = useTranslation('app');
  const { items, markRead, markAllRead, dismiss, dismissAll, act } = useNotifications();
  const { items: dismissed, refresh: refreshDismissed, clear: restore } = useSuggestionDismissals();
  const [showDismissed, setShowDismissed] = useState(false);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [conflictLoading, setConflictLoading] = useState<Map<number, 'confirm' | 'reject' | null>>(new Map());

  // Dismissing a notification records a preferences-level dismissal, so refresh
  // the "已忽略" footer after each dismiss to keep the restore list in sync.
  const onDismiss = (id: number) => { void dismiss(id).then(refreshDismissed); };
  const onDismissAll = () => { void dismissAll().then(refreshDismissed); };
  // Open the shared install panel (mounted once in MainLayout). The server-side
  // `action` is recorded only when the panel's connect flow actually succeeds
  // (its onDone), not when the panel merely opens — so cancelling/closing the
  // panel never drops the suggestion item.
  const openPanel = usePluginInstallPanelStore((s) => s.openPanel);

  const pluginName = (plugin: SuggestionPlugin): string =>
    localizedPluginText(plugin.name, plugin.name_i18n, i18n.language);

  // Short, plugin-centric collapsed title — distinct from the body so the same
  // sentence never appears twice. Replaces any placeholder rationale.
  const displayTitle = (n: NotificationItem): string => {
    const plugins = n.payload.plugins ?? [];
    if (plugins.length > 0) {
      return t('notifications.suggestionTitle', { plugin: plugins.map(pluginName).join('、') });
    }
    if (n.title && !PLACEHOLDER_RATIONALE.test(n.title)) return n.title;
    return t('notifications.suggestionTitleGeneric');
  };

  // The "why connect" line shown once when expanded: the rationale if it's
  // real, otherwise a generic hint.
  const description = (n: NotificationItem): string => {
    if (n.body && !PLACEHOLDER_RATIONALE.test(n.body)) return n.body;
    return t('notifications.connectHint');
  };

  const handleConflict = async (n: NotificationItem, action: 'confirm' | 'reject') => {
    setConflictLoading((prev) => new Map(prev).set(n.id, action));
    try {
      await resolveConflict(n.id, action);
      await act(n.id);
    } finally {
      setConflictLoading((prev) => { const next = new Map(prev); next.delete(n.id); return next; });
    }
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
            const plugins = n.payload.plugins ?? [];
            const multi = plugins.length > 1;
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
                    {plugins.length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {plugins.map((plugin) => {
                          const needsInstall = !plugin.installed;
                          const base = needsInstall
                            ? t('notifications.installAndConnect')
                            : t('notifications.connect');
                          return (
                            <button
                              key={plugin.plugin_id}
                              type="button"
                              data-testid={`notification-connect-${plugin.plugin_id}`}
                              onClick={() => {
                                openPanel(plugin.plugin_id, {
                                  install: needsInstall,
                                  pluginName: pluginName(plugin),
                                  pluginIcon: plugin.icon,
                                  onDone: () => {
                                    void act(n.id);
                                  },
                                });
                              }}
                              className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition hover:bg-primary/90"
                            >
                              {multi ? `${base} ${pluginName(plugin)}` : base}
                            </button>
                          );
                        })}
                      </div>
                    ) : n.payload.conflict_type === 'profile_conflict' ? (
                      <div className="flex flex-wrap gap-2">
                        <button
                          type="button"
                          data-testid="notification-conflict-confirm"
                          disabled={conflictLoading.has(n.id)}
                          onClick={() => { void handleConflict(n, 'confirm'); }}
                          className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition hover:bg-primary/90 disabled:opacity-50"
                        >
                          {t('notifications.conflictConfirm')}
                        </button>
                        <button
                          type="button"
                          data-testid="notification-conflict-reject"
                          disabled={conflictLoading.has(n.id)}
                          onClick={() => { void handleConflict(n, 'reject'); }}
                          className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition hover:bg-muted/60 disabled:opacity-50"
                        >
                          {t('notifications.conflictReject')}
                        </button>
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
    </div>
  );
}

export default NotificationCenter;
