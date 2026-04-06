import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { MEMORY_ACTION_BUTTON_CLASS } from './MemoryPageFrame';

const PAGE_SIZE = 50;

interface MemoryPaginationProps {
  total: number;
  offset: number;
  limit?: number;
  loading?: boolean;
  onPageChange: (offset: number) => void;
}

export const MemoryPagination = ({
  total,
  offset,
  limit = PAGE_SIZE,
  loading,
  onPageChange,
}: MemoryPaginationProps) => {
  const { t } = useTranslation('app');
  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  if (total <= limit && offset === 0) return null;

  const rangeStart = Math.min(offset + 1, total);
  const rangeEnd = Math.min(offset + limit, total);

  return (
    <div className="flex items-center justify-between rounded-xl border border-[hsl(var(--memory-border)/0.52)] bg-[hsl(var(--memory-panel-elevated)/0.68)] px-4 py-2.5">
      <span className="text-sm text-[hsl(var(--memory-body))]">
        {t('memory.pagination.info', { from: rangeStart, to: rangeEnd, total })}
      </span>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          className={MEMORY_ACTION_BUTTON_CLASS}
          disabled={!hasPrev || loading}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
        >
          {t('memory.pagination.prev')}
        </Button>
        <span className="min-w-[4rem] text-center text-sm text-[hsl(var(--memory-title))]">
          {currentPage} / {totalPages}
        </span>
        <Button
          variant="outline"
          className={MEMORY_ACTION_BUTTON_CLASS}
          disabled={!hasNext || loading}
          onClick={() => onPageChange(offset + limit)}
        >
          {t('memory.pagination.next')}
        </Button>
      </div>
    </div>
  );
};

export { PAGE_SIZE };
export default MemoryPagination;
