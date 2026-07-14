import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { formatBytes } from './overviewModel';

export function OverviewEmptyState({ diskUsageBytes }: { diskUsageBytes?: number | null }) {
  const { t } = useTranslation('app');

  return (
    <section
      data-testid="memory-overview-empty"
      className="flex min-h-[clamp(30rem,68vh,42rem)] items-start justify-center px-4 pt-[clamp(6rem,16vh,10rem)]"
    >
      <div className="w-full max-w-[34rem] text-center">
        <h1 className="text-[clamp(1.5rem,2.4vw,2rem)] font-semibold tracking-[-0.025em] text-[hsl(var(--memory-title))]">
          {t('memory.overview.empty.title')}
        </h1>
        <p className="mx-auto mt-3 max-w-[31rem] text-sm leading-7 text-[hsl(var(--memory-body))]">
          {t('memory.overview.empty.body')}
        </p>
        <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
          <Button asChild size="sm" variant="secondary" className="rounded-lg px-4">
            <Link to="/memory/sources">{t('memory.overview.actions.addSource')}</Link>
          </Button>
          <Button asChild size="sm" variant="ghost" className="rounded-lg px-4">
            <Link to="/chat">{t('memory.overview.actions.startChat')}</Link>
          </Button>
        </div>
        <p className="mt-8 text-xs leading-5 text-[hsl(var(--memory-muted))]">
          {t('memory.overview.empty.storage', { value: formatBytes(diskUsageBytes) })}
        </p>
      </div>
    </section>
  );
}
