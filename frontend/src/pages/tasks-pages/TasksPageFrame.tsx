import React, { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface TasksPageFrameProps {
  /**
   * Optional toolbar content (chips, segmented buttons, etc) rendered at the
   * very top of the page. The sidebar already names the page, so the frame
   * itself does not render any title.
   */
  toolbar?: ReactNode;
  /**
   * Optional action buttons (e.g. "+ Create") rendered right-aligned in the
   * sticky toolbar alongside the refresh button.
   */
  actions?: ReactNode;
  onRefresh?: () => void;
  refreshing?: boolean;
  children: ReactNode;
}

/**
 * Shared layout shell for the three Tasks sub-pages.
 *
 * Single scroll container with a sticky toolbar at the top — keeps filters in
 * view while the table scrolls. No title row (the sidebar provides that).
 */
export const TasksPageFrame: React.FC<TasksPageFrameProps> = ({
  toolbar,
  actions,
  onRefresh,
  refreshing,
  children,
}) => {
  const { t } = useTranslation('app');
  const hasToolbar = Boolean(toolbar) || Boolean(actions) || Boolean(onRefresh);
  return (
    <div className="h-full overflow-y-auto bg-background">
      {hasToolbar ? (
        <div className="sticky top-0 z-10 flex flex-wrap items-center gap-4 border-b border-border/40 bg-background/95 px-6 py-3.5 backdrop-blur supports-[backdrop-filter]:bg-background/88">
          <div className="flex flex-1 flex-wrap items-center gap-x-5 gap-y-2">
            {toolbar}
          </div>
          <div className="flex items-center gap-2">
            {actions}
            {onRefresh ? (
              <Button
                variant="ghost"
                size="icon"
                aria-label={refreshing ? t('tasks.page.refreshing') : t('tasks.page.refresh')}
                title={refreshing ? t('tasks.page.refreshing') : t('tasks.page.refresh')}
                onClick={onRefresh}
                disabled={refreshing}
                className="h-9 w-9 rounded-lg text-muted-foreground hover:bg-muted/45 hover:text-foreground"
              >
                <RefreshCw className={cn('h-4 w-4', refreshing && 'animate-spin')} />
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
      <div className="px-6 py-5">{children}</div>
    </div>
  );
};
