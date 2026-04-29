import React from 'react';
import { CalendarDays, ChevronLeft, ChevronRight, RefreshCw, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type TimelineScale = 'month' | 'week' | 'day' | 'hour';

interface TimelineToolbarProps {
  scale: TimelineScale;
  draftQuery: string;
  periodInputValue: string;
  periodInputMax: string;
  periodDisplayLabel: string;
  canGoNext: boolean;
  refreshing: boolean;
  onDraftQueryChange: (value: string) => void;
  onSubmitQuery: () => void;
  onPeriodInputChange: (value: string) => void;
  onScaleChange: (scale: TimelineScale) => void;
  onPrevious: () => void;
  onNext: () => void;
  onRefresh: () => void;
}

const SCALE_SEQUENCE: TimelineScale[] = ['month', 'week', 'day', 'hour'];

const OPTION_COUNT_BY_SCALE: Record<TimelineScale, number> = {
  month: 48,
  week: 52,
  day: 90,
  hour: 48,
};

const padNumber = (value: number): string => String(value).padStart(2, '0');

const startOfLocalWeek = (date: Date): Date => {
  const dayStart = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const mondayOffset = (dayStart.getDay() + 6) % 7;
  dayStart.setDate(dayStart.getDate() - mondayOffset);
  return dayStart;
};

const shiftPeriodDate = (scale: TimelineScale, date: Date, amount: number): Date => {
  const next = new Date(date);
  if (scale === 'month') next.setMonth(next.getMonth() + amount);
  if (scale === 'week') next.setDate(next.getDate() + amount * 7);
  if (scale === 'day') next.setDate(next.getDate() + amount);
  if (scale === 'hour') next.setHours(next.getHours() + amount);
  return next;
};

const isoWeekStart = (year: number, week: number): Date => {
  const januaryFourth = new Date(year, 0, 4);
  const firstWeekStart = startOfLocalWeek(januaryFourth);
  firstWeekStart.setDate(firstWeekStart.getDate() + (week - 1) * 7);
  return firstWeekStart;
};

const isoWeekValue = (date: Date): string => {
  const weekStart = startOfLocalWeek(date);
  const thursday = new Date(weekStart);
  thursday.setDate(thursday.getDate() + 3);
  const isoYear = thursday.getFullYear();
  const firstWeekStart = startOfLocalWeek(new Date(isoYear, 0, 4));
  const week = Math.round((weekStart.getTime() - firstWeekStart.getTime()) / (7 * 24 * 60 * 60 * 1000)) + 1;
  return `${isoYear}-W${padNumber(week)}`;
};

const parsePeriodDate = (scale: TimelineScale, value: string): Date | null => {
  if (scale === 'month') {
    const match = /^(\d{4})-(\d{2})$/.exec(value);
    return match ? new Date(Number(match[1]), Number(match[2]) - 1, 1) : null;
  }
  if (scale === 'week') {
    const match = /^(\d{4})-W(\d{2})$/.exec(value);
    return match ? isoWeekStart(Number(match[1]), Number(match[2])) : null;
  }
  if (scale === 'hour') {
    const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):00$/.exec(value);
    return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4])) : null;
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
};

const formatPeriodValue = (scale: TimelineScale, date: Date): string => {
  const datePart = `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}-${padNumber(date.getDate())}`;
  if (scale === 'month') return `${date.getFullYear()}-${padNumber(date.getMonth() + 1)}`;
  if (scale === 'week') return isoWeekValue(date);
  if (scale === 'hour') return `${datePart}T${padNumber(date.getHours())}:00`;
  return datePart;
};

const normalizeTypedPeriodValue = (scale: TimelineScale, value: string): string | null => {
  const trimmed = value.trim();
  if (scale === 'month') {
    const match = /^(\d{4})-(\d{1,2})$/.exec(trimmed);
    return match ? `${match[1]}-${padNumber(Number(match[2]))}` : null;
  }
  if (scale === 'week') {
    const match = /^(\d{4})-W(\d{1,2})$/i.exec(trimmed);
    return match ? `${match[1]}-W${padNumber(Number(match[2]))}` : null;
  }
  if (scale === 'hour') {
    const match = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2})(?::\d{1,2})?)?$/.exec(trimmed);
    return match
      ? `${match[1]}-${padNumber(Number(match[2]))}-${padNumber(Number(match[3]))}T${padNumber(Number(match[4] || 0))}:00`
      : null;
  }
  const match = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(trimmed);
  return match ? `${match[1]}-${padNumber(Number(match[2]))}-${padNumber(Number(match[3]))}` : null;
};

const buildPeriodOptions = (scale: TimelineScale, maxValue: string, currentValue: string): string[] => {
  const maxDate = parsePeriodDate(scale, maxValue);
  if (!maxDate) return currentValue ? [currentValue] : [];
  const values: string[] = [];
  for (let index = 0; index < OPTION_COUNT_BY_SCALE[scale]; index += 1) {
    values.push(formatPeriodValue(scale, shiftPeriodDate(scale, maxDate, -index)));
  }
  if (currentValue && !values.includes(currentValue)) {
    values.unshift(currentValue);
  }
  return values;
};

const formatOptionLabel = (scale: TimelineScale, value: string, locale: string): string => {
  const date = parsePeriodDate(scale, value);
  if (!date) return value;
  if (scale === 'month') {
    return date.toLocaleDateString(locale, { year: 'numeric', month: 'long' });
  }
  if (scale === 'week') {
    const end = new Date(date);
    end.setDate(end.getDate() + 6);
    const startLabel = date.toLocaleDateString(locale, { month: 'short', day: 'numeric' });
    const endLabel = end.toLocaleDateString(locale, { month: 'short', day: 'numeric' });
    return `${startLabel} – ${endLabel}`;
  }
  if (scale === 'hour') {
    const day = date.toLocaleDateString(locale, { month: 'short', day: 'numeric' });
    const hour = date.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit', hour12: false });
    return `${day} ${hour}`;
  }
  return date.toLocaleDateString(locale, { month: 'short', day: 'numeric', weekday: 'short' });
};

export const TimelineToolbar: React.FC<TimelineToolbarProps> = ({
  scale,
  draftQuery,
  periodInputValue,
  periodInputMax,
  periodDisplayLabel,
  canGoNext,
  refreshing,
  onDraftQueryChange,
  onSubmitQuery,
  onPeriodInputChange,
  onScaleChange,
  onPrevious,
  onNext,
  onRefresh,
}) => {
  const { t, i18n } = useTranslation('app');
  const locale = i18n.resolvedLanguage || i18n.language || 'en';
  const [periodPickerOpen, setPeriodPickerOpen] = React.useState(false);
  const [periodDraft, setPeriodDraft] = React.useState(periodInputValue);
  const pickerRef = React.useRef<HTMLDivElement>(null);
  const periodOptions = React.useMemo(
    () => buildPeriodOptions(scale, periodInputMax, periodInputValue),
    [scale, periodInputMax, periodInputValue],
  );

  React.useEffect(() => {
    setPeriodDraft(periodInputValue);
  }, [periodInputValue]);

  React.useEffect(() => {
    if (!periodPickerOpen) return undefined;
    const handlePointerDown = (event: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(event.target as Node)) {
        setPeriodPickerOpen(false);
      }
    };
    document.addEventListener('mousedown', handlePointerDown);
    return () => document.removeEventListener('mousedown', handlePointerDown);
  }, [periodPickerOpen]);

  const applyPeriodDraft = () => {
    const normalized = normalizeTypedPeriodValue(scale, periodDraft);
    if (!normalized) return;
    onPeriodInputChange(normalized);
    setPeriodPickerOpen(false);
  };

  const selectPeriod = (value: string) => {
    setPeriodDraft(value);
    onPeriodInputChange(value);
    setPeriodPickerOpen(false);
  };

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <div className="flex rounded-lg border border-border/60 p-0.5">
        {SCALE_SEQUENCE.map((item) => (
          <button
            key={item}
            type="button"
            aria-pressed={scale === item}
            className={cn(
              'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
              scale === item
                ? 'bg-foreground/[0.07] text-foreground'
                : 'text-muted-foreground hover:text-foreground',
            )}
            onClick={() => onScaleChange(item)}
          >
            {t(`timeline.scale.${item}`)}
          </button>
        ))}
      </div>

      <div className="flex h-8 items-center rounded-lg border border-border/60 bg-background/70">
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 rounded-md p-0"
          onClick={onPrevious}
          aria-label={t('timeline.nav.previous')}
          title={t('timeline.nav.previous')}
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <div ref={pickerRef} className="relative h-full border-x border-border/50">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-full w-[10.5rem] justify-start rounded-none px-2 text-xs font-normal text-foreground hover:bg-muted/45"
            aria-label={t('timeline.period.label')}
            aria-expanded={periodPickerOpen}
            onClick={() => setPeriodPickerOpen((open) => !open)}
          >
            <CalendarDays className="h-3.5 w-3.5 text-muted-foreground/60" />
            <span className="min-w-0 truncate">{periodDisplayLabel}</span>
          </Button>
          {periodPickerOpen ? (
            <div
              role="dialog"
              aria-label={t('timeline.period.label')}
              className="absolute right-0 top-9 z-50 w-72 rounded-lg border border-border/70 bg-background p-2 shadow-lg"
              onKeyDown={(event) => {
                if (event.key === 'Escape') setPeriodPickerOpen(false);
              }}
            >
              <form
                className="flex gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  applyPeriodDraft();
                }}
              >
                <label className="min-w-0 flex-1">
                  <span className="sr-only">{t('timeline.period.jump')}</span>
                  <input
                    aria-label={t('timeline.period.jump')}
                    value={periodDraft}
                    onChange={(event) => setPeriodDraft(event.target.value)}
                    placeholder={t(`timeline.period.placeholder.${scale}`)}
                    className="h-8 w-full rounded-md border border-border/60 bg-muted/25 px-2 text-xs text-foreground outline-none placeholder:text-muted-foreground/45 focus:border-ring/40 focus:bg-background"
                  />
                </label>
                <Button type="submit" variant="outline" size="sm" className="h-8 px-2 text-xs">
                  {t('timeline.period.apply')}
                </Button>
              </form>
              <div className="mt-2 max-h-64 space-y-1 overflow-y-auto pr-1 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
                {periodOptions.map((value) => {
                  const selected = value === periodInputValue;
                  return (
                    <button
                      key={value}
                      type="button"
                      aria-current={selected ? 'date' : undefined}
                      className={cn(
                        'flex h-8 w-full items-center justify-between rounded-md px-2 text-left text-xs transition-colors',
                        selected
                          ? 'bg-foreground/[0.07] text-foreground'
                          : 'text-muted-foreground hover:bg-muted/45 hover:text-foreground',
                      )}
                      onClick={() => selectPeriod(value)}
                    >
                      <span>{formatOptionLabel(scale, value, locale)}</span>
                      <span className="font-mono text-[11px] text-muted-foreground/55">{value}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-7 w-7 rounded-md p-0"
          onClick={onNext}
          disabled={!canGoNext}
          aria-label={t('timeline.nav.next')}
          title={t('timeline.nav.next')}
        >
          <ChevronRight className="h-4 w-4" />
        </Button>
      </div>

      <form
        className="relative min-w-[180px] flex-1 sm:max-w-[240px]"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmitQuery();
        }}
      >
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/50" />
        <input
          aria-label={t('timeline.filters.query')}
          value={draftQuery}
          onChange={(e) => onDraftQueryChange(e.target.value)}
          className="h-8 w-full rounded-lg border border-border/60 bg-transparent pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-ring/30"
          placeholder={t('timeline.filters.queryInWindow')}
        />
      </form>

      <Button
        variant="ghost"
        size="sm"
        className="h-8 w-8 p-0"
        onClick={onRefresh}
        disabled={refreshing}
        aria-label={t('timeline.nav.refresh')}
        title={t('timeline.nav.refresh')}
      >
        <RefreshCw className={cn('h-3.5 w-3.5', refreshing && 'animate-spin')} />
      </Button>
    </div>
  );
};

export default TimelineToolbar;
