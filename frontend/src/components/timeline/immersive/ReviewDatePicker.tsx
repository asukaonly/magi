import { useState } from 'react';
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useChatShellStore } from '@/stores';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { MonthGridPicker } from './picker/MonthGridPicker';
import { WeekListPicker } from './picker/WeekListPicker';

export function ReviewDatePicker({ dateLabel }: { dateLabel: string }) {
  const { t } = useTranslation('app');
  const panel = useChatShellStore(state => state.timelinePanel);
  const [open, setOpen] = useState(false);
  const select = (value: string) => { panel.onSelectFromDateInput?.(value); setOpen(false); };
  const date = new Date(panel.viewportStart * 1000);
  const number = (value: number) => String(value).padStart(2, '0');
  return <div className="flex min-w-0 flex-wrap items-center gap-2">
    <Popover open={open} onOpenChange={setOpen}>
      <h1 className="min-w-0 text-[24px] font-semibold leading-8 tracking-tight">
        <PopoverTrigger asChild><button id="timeline-review-date" type="button" className="inline-flex items-center gap-2 rounded-md text-left hover:text-foreground/75 focus-visible:ring-2 focus-visible:ring-ring">
          {dateLabel}<CalendarDays className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        </button></PopoverTrigger>
      </h1>
      <PopoverContent align="start" className="w-auto p-0">
        {panel.scale === 'month' ? <MonthGridPicker selectedMonth={`${date.getFullYear()}-${number(date.getMonth() + 1)}`} onSelectMonth={select} />
          : panel.scale === 'week' ? <WeekListPicker selectedWeekStart={panel.viewportStart} onSelectWeek={select} />
            : <Calendar mode="single" selected={date} onSelect={value => {
              if (value) select(`${value.getFullYear()}-${number(value.getMonth() + 1)}-${number(value.getDate())}`);
            }} />}
      </PopoverContent>
    </Popover>
    <div className="flex items-center gap-0.5">
      <button type="button" onClick={() => panel.onPrevious?.()} aria-label={t('timeline.nav.previous')} className="rounded-md p-1.5 text-muted-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"><ChevronLeft className="h-4 w-4" /></button>
      <button type="button" onClick={() => panel.onNext?.()} disabled={!panel.canGoNext} aria-label={t('timeline.nav.next')} className="rounded-md p-1.5 text-muted-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button>
    </div>
  </div>;
}
