import React, { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export interface TasksPageFrameProps {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  filters?: ReactNode;
  actions?: ReactNode;
  onRefresh?: () => void;
  refreshing?: boolean;
  children: ReactNode;
}

export const TasksPageFrame: React.FC<TasksPageFrameProps> = ({
  title,
  subtitle,
  icon,
  filters,
  actions,
  onRefresh,
  refreshing,
  children,
}) => {
  const { t } = useTranslation('app');
  return (
    <div className="flex h-full flex-col bg-background">
      <header className="flex items-start justify-between gap-4 border-b border-border/60 px-6 py-5">
        <div>
          <div className="flex items-center gap-2">
            {icon}
            <h1 className="text-lg font-semibold text-foreground">{title}</h1>
          </div>
          {subtitle ? (
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{subtitle}</p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {actions}
          {onRefresh ? (
            <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing}>
              <RefreshCw className={cn('mr-2 h-3.5 w-3.5', refreshing && 'animate-spin')} />
              {refreshing ? t('tasks.page.refreshing') : t('tasks.page.refresh')}
            </Button>
          ) : null}
        </div>
      </header>
      {filters ? (
        <div className="border-b border-border/60 px-6 py-3">{filters}</div>
      ) : null}
      <div className="flex-1 overflow-hidden px-6 py-5">{children}</div>
    </div>
  );
};
