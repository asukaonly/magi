import { ChevronDown } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type { LLMUsageSummary, UsageDisplayCurrency } from '@/api/modules/metrics';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

export function formatUsageCost(amount: number | null | undefined, currency: string, locale: string) {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return '—';
  const validCode = /^[A-Z]{3}$/.test(currency);
  const money = new Intl.NumberFormat(locale, {
    style: validCode ? 'currency' : 'decimal',
    currency: validCode ? currency : undefined,
    currencyDisplay: 'narrowSymbol', minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
  return amount > 0 && amount < 0.01 ? `<${money.format(0.01)}` : money.format(amount);
}

export function UsageCostSummary({ summary, currency, locale }: {
  summary: LLMUsageSummary; currency: UsageDisplayCurrency; locale: string;
}) {
  const { t } = useTranslation('app');
  const { totals } = summary;
  const cost = totals.display_costs[currency];
  const unknown = totals.unpriced_calls;
  const failed = totals.unpriced_failed_without_usage;
  const missingUsage = totals.unpriced_success_without_usage;
  const missingPrice = unknown - failed - missingUsage;
  const nativeCharges = summary.providers.flatMap((provider) =>
    provider.cost_by_currency.map((charge) => ({ ...charge, provider: provider.provider })));
  const missingRate = cost == null && nativeCharges.length > 0;
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground">{t('settings.statistics.llm.estimatedCost')}</div>
      <Popover>
        <PopoverTrigger asChild>
          <button type="button" aria-label={t('settings.statistics.llm.costDetails')}
            className="mt-1 inline-flex items-baseline gap-1 text-left text-2xl font-semibold tracking-tight text-foreground tabular-nums hover:text-primary focus-visible:outline-primary">
            {cost != null && <span className="text-base font-normal text-muted-foreground">≈</span>}
            {formatUsageCost(cost, currency, locale)}
            <ChevronDown aria-hidden="true" className="size-3 self-center text-muted-foreground" />
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-80 max-w-[90vw] space-y-3 p-4 text-sm"
          aria-label={t('settings.statistics.llm.costDetails')}>
          <h3 className="font-semibold">{t('settings.statistics.llm.nativeCharges')}</h3>
          {nativeCharges.length > 0 && (
            <ul className="divide-y divide-border">
              {nativeCharges.map((entry) => (
                <li key={JSON.stringify([entry.provider, entry.currency])} className="flex items-baseline justify-between gap-3 py-1.5">
                  <span className="break-all">{entry.provider}</span>
                  <span className="shrink-0 tabular-nums">{formatUsageCost(entry.amount, entry.currency, locale)} <small>{entry.currency}</small></span>
                </li>
              ))}
            </ul>
          )}
          {nativeCharges.length === 0 && <p>{t('settings.statistics.llm.noPricedCalls')}</p>}
          {nativeCharges.some((entry) => entry.currency !== currency) &&
            <p className="text-xs leading-relaxed text-muted-foreground">{t('settings.statistics.llm.rateNote')}</p>}
          {missingRate && <p>{t('settings.statistics.llm.missingRate')}</p>}
          {unknown > 0 && (
            <div className="space-y-1 border-t border-border pt-2 text-xs leading-relaxed">
              <p className="font-medium">{t('settings.statistics.llm.excludedCalls', { count: unknown })}</p>
              {failed > 0 && <p>{t('settings.statistics.llm.failedWithoutUsage', { count: failed })}</p>}
              {missingUsage > 0 && <p>{t('settings.statistics.llm.successWithoutUsage', { count: missingUsage })}</p>}
              {missingPrice > 0 && <p>{t('settings.statistics.llm.missingPrice', { count: missingPrice })}</p>}
            </div>
          )}
        </PopoverContent>
      </Popover>
      {unknown > 0 && <p className="mt-1 text-xs text-muted-foreground">{t(failed === unknown ? 'settings.statistics.llm.failedWithoutUsage' : 'settings.statistics.llm.excludedCalls', { count: unknown })}</p>}
      {missingRate && <p className="mt-1 text-xs text-muted-foreground">{t('settings.statistics.llm.rateUnavailable')}</p>}
    </div>
  );
}
