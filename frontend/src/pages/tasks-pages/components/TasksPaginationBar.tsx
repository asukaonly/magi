import React from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';

export interface TasksPaginationBarProps {
  total: number;
  offset: number;
  limit: number;
  loading: boolean;
  onPageChange: (offset: number) => void;
}

export const TasksPaginationBar: React.FC<TasksPaginationBarProps> = ({
  total,
  offset,
  limit,
  loading,
  onPageChange,
}) => {
  const { t } = useTranslation('app');
  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  if (total <= limit && offset === 0) return null;

  const rangeStart = Math.min(offset + 1, total);
  const rangeEnd = Math.min(offset + limit, total);

  return (
    <div className="flex items-center justify-between gap-4 px-1 py-1.5">
      <span className="text-xs text-muted-foreground">
        {t('tasks.pagination.info', { from: rangeStart, to: rangeEnd, total })}
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          disabled={!hasPrev || loading}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
          className="rounded-lg text-muted-foreground hover:text-foreground"
        >
          {t('tasks.pagination.prev')}
        </Button>
        <span className="min-w-[4rem] text-center text-xs font-medium tabular-nums text-foreground">
          {currentPage} / {totalPages}
        </span>
        <Button
          variant="ghost"
          size="sm"
          disabled={!hasNext || loading}
          onClick={() => onPageChange(offset + limit)}
          className="rounded-lg text-muted-foreground hover:text-foreground"
        >
          {t('tasks.pagination.next')}
        </Button>
      </div>
    </div>
  );
};
