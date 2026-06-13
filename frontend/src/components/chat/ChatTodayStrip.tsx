import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, RefreshCw } from 'lucide-react';
import { sensorsApi, type SensorTodaySummaryEntry, type SensorTodaySummaryResponse } from '@/api';
import { cn } from '@/lib/utils';

const REFRESH_INTERVAL_MS = 60_000;

const SOURCE_NAME_TO_I18N_KEY: Record<string, string> = {
  chrome_history: 'timeline.sources.chrome_history',
  'chrome-history': 'timeline.sources.chrome_history',
  manual_journal: 'timeline.sources.manual_journal',
  chat: 'timeline.sources.chat',
  photo_library: 'timeline.sources.photo_library',
  'photo-library': 'timeline.sources.photo_library',
  screen_time: 'timeline.sources.screen_time',
  'screen-time': 'timeline.sources.screen_time',
  system_media: 'timeline.sources.system_media',
  'system-media': 'timeline.sources.system_media',
  terminal_history: 'timeline.sources.terminal_history',
  'terminal-history': 'timeline.sources.terminal_history',
  git_activity: 'timeline.sources.git_activity',
  'git-activity': 'timeline.sources.git_activity',
  calendar: 'timeline.sources.calendar',
  netease_music: 'timeline.sources.netease_music',
  'netease-music': 'timeline.sources.netease_music',
  chat_projector: 'timeline.sources.chat_projector',
  tool_invocation_service: 'timeline.sources.tool_invocation_service',
  task_orchestrator: 'timeline.sources.task_orchestrator',
  skill_runner: 'timeline.sources.skill_runner',
};

type LabeledEntry = SensorTodaySummaryEntry & {
  label: string;
};

const useTodaySummary = (): {
  summary: SensorTodaySummaryResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
} => {
  const [summary, setSummary] = useState<SensorTodaySummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fetchSeqRef = useRef(0);

  const refresh = useMemo(() => {
    return () => {
      const seq = ++fetchSeqRef.current;
      setLoading(true);
      sensorsApi
        .getTodaySummary()
        .then((response) => {
          if (seq !== fetchSeqRef.current) return;
          setSummary(response);
          setError(null);
        })
        .catch((exc: unknown) => {
          if (seq !== fetchSeqRef.current) return;
          const message = exc instanceof Error ? exc.message : String(exc);
          setError(message);
        })
        .finally(() => {
          if (seq !== fetchSeqRef.current) return;
          setLoading(false);
        });
    };
  }, []);

  useEffect(() => {
    refresh();
    const interval = window.setInterval(refresh, REFRESH_INTERVAL_MS);
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        refresh();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [refresh]);

  return { summary, loading, error, refresh };
};

const formatWeekday = (isoDate: string, locale: string): string => {
  try {
    const parsed = new Date(`${isoDate}T00:00:00`);
    if (Number.isNaN(parsed.getTime())) {
      return '';
    }
    return new Intl.DateTimeFormat(locale || undefined, { weekday: 'short' }).format(parsed);
  } catch {
    return '';
  }
};

export const ChatTodayStrip = () => {
  const { t, i18n } = useTranslation('app');
  const { summary, loading, error, refresh } = useTodaySummary();

  const labeledEntries = useMemo<LabeledEntry[]>(() => {
    if (!summary) return [];
    return summary.sources
      .filter((entry) => entry.enabled !== false && entry.count > 0)
      .map((entry) => {
        const i18nKey = SOURCE_NAME_TO_I18N_KEY[entry.source_name];
        const fallback = entry.display_name || entry.source_name;
        const translated = i18nKey ? t(i18nKey, { defaultValue: fallback }) : fallback;
        return { ...entry, label: translated };
      });
  }, [summary, t]);

  const weekday = summary ? formatWeekday(summary.date, i18n.language) : '';
  const totalCount = labeledEntries.reduce((sum, entry) => sum + entry.count, 0);
  const showInitialLoading = loading && !summary;
  const showEmpty = !showInitialLoading && labeledEntries.length === 0;

  return (
    <div
      className="flex min-h-[28px] min-w-0 flex-1 items-center gap-2.5 text-[12px] text-muted-foreground"
      data-testid="chat-today-strip"
      title={
        summary
          ? t('chat.today.tooltip', {
              defaultValue: '今日感知 · 共 {{total}} 条来自 {{count}} 个来源',
              total: totalCount,
              count: labeledEntries.length,
            })
          : undefined
      }
    >
      {weekday ? (
        <span className="inline-flex shrink-0 items-center font-medium text-foreground/85">
          {weekday}
        </span>
      ) : null}

      {showInitialLoading ? (
        <span className="inline-flex items-center gap-1.5 text-muted-foreground/70">
          <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
          <span>{t('chat.today.loading', { defaultValue: '正在汇总今日感知…' })}</span>
        </span>
      ) : null}

      {showEmpty && !error ? (
        <span className="inline-flex items-center gap-1 text-muted-foreground/65">
          <span aria-hidden="true">·</span>
          <span>{t('chat.today.idle', { defaultValue: '今天还没有传感器数据' })}</span>
        </span>
      ) : null}

      {error && !showInitialLoading ? (
        <button
          type="button"
          onClick={refresh}
          className="inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11px] text-destructive transition-colors hover:bg-destructive/10"
          aria-label={t('chat.today.retry', { defaultValue: '重新加载今日感知' })}
        >
          <RefreshCw className="h-3 w-3" aria-hidden="true" />
          <span>{t('chat.today.retry', { defaultValue: '重新加载' })}</span>
        </button>
      ) : null}

      {!showInitialLoading && !error && labeledEntries.length > 0 ? (
        <ul className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
          {labeledEntries.map((entry, index) => (
            <li
              key={entry.source_name}
              className={cn(
                'inline-flex shrink-0 items-center gap-1 truncate',
                index > 0 && 'before:mr-1 before:text-muted-foreground/45 before:content-[\'·\']',
              )}
            >
              <span className="font-medium tabular-nums text-foreground/90">{entry.count}</span>
              <span className="truncate">{entry.label}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
};
