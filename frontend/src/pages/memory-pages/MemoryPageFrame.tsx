import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';

interface MemoryPageFrameProps {
  title: string;
  description: string;
  filters?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export const MemoryPageFrame = ({
  title,
  description,
  filters,
  actions,
  children,
  className,
}: MemoryPageFrameProps) => {
  const { t } = useTranslation('app');

  return (
    <div className={cn('mx-auto flex h-full max-w-7xl flex-col gap-6 overflow-y-auto p-5', className)}>
      <section className="rounded-[2rem] border border-border/40 bg-background/70 px-6 py-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <h1 className="text-3xl font-semibold tracking-tight text-foreground">{title}</h1>
            <p className="max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
      </section>

      {filters ? (
        <Card className="border-border/40 bg-background/75">
          <CardHeader className="pb-3">
            <CardTitle className="text-base">{t('memory.filters.title')}</CardTitle>
          </CardHeader>
          <CardContent>{filters}</CardContent>
        </Card>
      ) : null}

      <div className="pb-5">{children}</div>
    </div>
  );
};

export default MemoryPageFrame;
