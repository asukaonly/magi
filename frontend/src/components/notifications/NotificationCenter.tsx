import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNotifications } from '@/hooks/useNotifications';
import { usePluginActivation } from '@/hooks/usePluginActivation';
import { EmptyStateSensorCard } from '@/components/empty-state/EmptyStateSensorCard';
import { PluginActivationDialog } from '@/components/plugins/PluginActivationDialog';
import { getEmptyStatePluginMeta } from '@/constants/emptyStatePriorities';
import type { NotificationItem } from '@/api/modules/notifications';

export function NotificationCenter(): JSX.Element {
  const { t } = useTranslation('app');
  const { items, markRead, markAllRead, act } = useNotifications();
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  const { dialogState, installingPluginId, openDialog, closeDialog, confirm } = usePluginActivation({
    onSuccess: (pluginId) => { void pluginId; },
  });

  const toggle = (n: NotificationItem) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(n.id)) { next.delete(n.id); }
      else { next.add(n.id); if (n.status === 'unread') void markRead([n.id]); }
      return next;
    });
  };

  return (
    <div className="flex max-h-[70vh] w-full flex-col">
      <div className="flex items-center justify-between border-b border-border/55 px-4 py-2.5">
        <h3 className="text-sm font-medium text-foreground">{t('notifications.title')}</h3>
        {items.length > 0 ? (
          <button type="button" onClick={() => void markAllRead()}
            className="text-xs text-muted-foreground hover:text-foreground">
            {t('notifications.markAllRead')}
          </button>
        ) : null}
      </div>

      {items.length === 0 ? (
        <p className="px-4 py-8 text-center text-sm text-muted-foreground">{t('notifications.empty')}</p>
      ) : (
        <ul className="divide-y divide-border/55 overflow-y-auto">
          {items.map((n) => {
            const isExpanded = expanded.has(n.id);
            const installable = n.payload.installable_plugin_ids ?? [];
            return (
              <li key={n.id} data-testid="notification-row">
                <button type="button" onClick={() => toggle(n)}
                  className="flex w-full items-start gap-2 px-4 py-3 text-left hover:bg-muted/40">
                  {n.status === 'unread' ? (
                    <span aria-hidden className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" />
                  ) : <span className="mt-1.5 h-2 w-2 shrink-0" />}
                  <span className={`min-w-0 flex-1 truncate text-sm ${n.status === 'unread' ? 'font-medium text-foreground' : 'text-muted-foreground'}`}>
                    {n.title}
                  </span>
                </button>
                {isExpanded ? (
                  <div className="space-y-2 px-4 pb-3">
                    <p className="text-xs text-muted-foreground">{n.body}</p>
                    {(n.payload.plugin_ids ?? []).map((pid) => {
                      const meta = getEmptyStatePluginMeta(pid);
                      const needsInstall = installable.includes(pid);
                      const isInstalling = installingPluginId === pid;
                      return (
                        <EmptyStateSensorCard
                          key={pid}
                          pluginId={pid}
                          titleKey={meta?.titleKey ?? 'emptyState.connect'}
                          valueKey={meta?.valueKey ?? 'emptyState.connect'}
                          disabled={isInstalling}
                          connectLabelKey={isInstalling ? 'emptyState.installing'
                            : needsInstall ? 'emptyState.installAndConnect' : 'emptyState.connect'}
                          onConnect={(p) => { void openDialog(p, { install: needsInstall }).then(() => { void act(n.id); }); }}
                        />
                      );
                    })}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}

      {dialogState ? (
        <PluginActivationDialog open onClose={closeDialog} flow={dialogState.flow}
          initialValues={{}} onConfirm={confirm} pluginId={dialogState.pluginId} />
      ) : null}
    </div>
  );
}

export default NotificationCenter;
