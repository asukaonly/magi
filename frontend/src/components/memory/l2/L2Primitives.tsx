import React from 'react';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export const PANEL_CARD_CLASS =
  'rounded-sm border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel-elevated)/0.74)] shadow-none';

export const SOFT_PANEL_CLASS =
  'rounded-sm border border-[hsl(var(--memory-border)/0.64)] bg-[hsl(var(--memory-panel)/0.72)] px-4 py-3 text-sm text-[hsl(var(--memory-body))]';

export const MetricCard: React.FC<{ label: string; value: number }> = ({ label, value }) => (
  <Card className={PANEL_CARD_CLASS}>
    <CardContent className="pt-5">
      <div className="text-[1.85rem] font-semibold tracking-[-0.03em] text-[hsl(var(--memory-title))]">{value}</div>
      <div className="mt-1 text-sm text-[hsl(var(--memory-muted))]">{label}</div>
    </CardContent>
  </Card>
);

export const InfoCard: React.FC<{
  icon: React.ReactNode;
  title: string;
  emptyText: string;
  children: React.ReactNode;
}> = ({ icon, title, emptyText, children }) => {
  const items = React.Children.toArray(children).filter(Boolean);

  return (
    <Card className={PANEL_CARD_CLASS}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base text-[hsl(var(--memory-title))]">
          {icon}
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <EmptyState copy={emptyText} />
        ) : (
          <div className="space-y-3">{items}</div>
        )}
      </CardContent>
    </Card>
  );
};

export const BreakdownCard: React.FC<{
  title: string;
  emptyText: string;
  entries: Array<[string, number]>;
}> = ({ title, emptyText, entries }) => (
  <Card className={PANEL_CARD_CLASS}>
    <CardHeader>
      <CardTitle className="text-base text-[hsl(var(--memory-title))]">{title}</CardTitle>
    </CardHeader>
    <CardContent>
      {entries.length === 0 ? (
        <EmptyState copy={emptyText} />
      ) : (
        <div className="space-y-3">
          {entries.map(([label, value]) => (
            <div key={label} className={`${SOFT_PANEL_CLASS} flex items-center justify-between`}>
              <span className="font-medium text-[hsl(var(--memory-title))]">{label}</span>
              <Badge variant="secondary">{value}</Badge>
            </div>
          ))}
        </div>
      )}
    </CardContent>
  </Card>
);

export const SummaryPill: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="inline-flex items-center rounded-full border border-[hsl(var(--memory-tag-border))] bg-[hsl(var(--memory-tag-bg)/0.95)] px-3 py-1 text-xs text-[hsl(var(--memory-body))]">
    {children}
  </span>
);

export const StatLine: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className={`${SOFT_PANEL_CLASS} flex items-center justify-between`}>
    <span>{label}</span>
    <span className="text-base font-semibold text-[hsl(var(--memory-title))]">{value}</span>
  </div>
);

export const EmptyState: React.FC<{ copy: string }> = ({ copy }) => (
  <div className="rounded-lg bg-[hsl(var(--memory-panel-subtle)/0.32)] px-4 py-3 text-sm leading-6 text-[hsl(var(--memory-muted))] shadow-[inset_0_0_0_1px_hsl(var(--memory-divider)/0.2)]">
    {copy}
  </div>
);
