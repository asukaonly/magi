import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { memoryApi } from "@/api/modules/memory";
import { manualEntriesApi, type ManualEntry } from "@/api/modules/manualEntries";
import {
  timelineApi,
  type TimelineMoodCalendarDay,
  type TimelineStandoutItem,
  type TimelineViewportResponse,
} from "@/api/modules/timeline";
import type { TimelineCoverChangeRequest } from "@/components/timeline/immersive/CoverPickerSheet";
import { HourDetail } from "@/components/timeline/immersive/HourDetail";
import { PeriodCard } from "@/components/timeline/immersive/PeriodCard";
import { QuickEntrySheet } from "@/components/timeline/manual-entries/QuickEntrySheet";
import { LoadingSpinner } from "@/components/ui/loading-spinner";
import { useChatShellStore } from "@/stores";
import { Feather } from "lucide-react";
import { cn } from "@/lib/utils";

type TimelineScale = "month" | "week" | "day" | "hour";

const padNumber = (value: number): string => String(value).padStart(2, "0");
const toUnixSeconds = (date: Date): number => Math.floor(date.getTime() / 1000);

const startOfLocalHour = (date: Date): Date =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate(), date.getHours());
const startOfLocalDay = (date: Date): Date =>
  new Date(date.getFullYear(), date.getMonth(), date.getDate());
const startOfLocalMonth = (date: Date): Date => new Date(date.getFullYear(), date.getMonth(), 1);
const startOfLocalWeek = (date: Date): Date => {
  const day = startOfLocalDay(date);
  const mondayOffset = (day.getDay() + 6) % 7;
  day.setDate(day.getDate() - mondayOffset);
  return day;
};

const shiftPeriodDate = (scale: TimelineScale, start: Date, amount: number): Date => {
  const next = new Date(start);
  if (scale === "month") next.setMonth(next.getMonth() + amount);
  if (scale === "week") next.setDate(next.getDate() + amount * 7);
  if (scale === "day") next.setDate(next.getDate() + amount);
  if (scale === "hour") next.setHours(next.getHours() + amount);
  return next;
};

const getLatestCompletePeriodStart = (scale: TimelineScale, now = new Date()): number => {
  if (scale === "month") return toUnixSeconds(shiftPeriodDate(scale, startOfLocalMonth(now), -1));
  if (scale === "week") return toUnixSeconds(shiftPeriodDate(scale, startOfLocalWeek(now), -1));
  if (scale === "day") return toUnixSeconds(shiftPeriodDate(scale, startOfLocalDay(now), -1));
  return toUnixSeconds(shiftPeriodDate(scale, startOfLocalHour(now), -1));
};
const getPeriodEnd = (scale: TimelineScale, start: number): number =>
  toUnixSeconds(shiftPeriodDate(scale, new Date(start * 1000), 1));
const shiftPeriodStart = (scale: TimelineScale, start: number, amount: number): number =>
  toUnixSeconds(shiftPeriodDate(scale, new Date(start * 1000), amount));
const clampToLatestCompletePeriod = (scale: TimelineScale, start: number): number =>
  Math.min(start, getLatestCompletePeriodStart(scale));

function formatWindowLabel(scale: TimelineScale, start: number, end: number, locale: string): string {
  const s = new Date(start * 1000);
  if (scale === "month")
    return s.toLocaleDateString(locale, { year: "numeric", month: "long" });
  if (scale === "day")
    return s.toLocaleDateString(locale, { year: "numeric", month: "short", day: "numeric", weekday: "short" });
  if (scale === "hour") {
    const e = new Date(end * 1000);
    const day = s.toLocaleDateString(locale, { month: "short", day: "numeric" });
    const startTime = s.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", hour12: false });
    const endTime = e.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", hour12: false });
    return `${day} ${startTime}–${endTime}`;
  }
  const e = new Date(Math.max(start, end - 1) * 1000);
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  const sf = s.toLocaleDateString(locale, opts);
  const ef = e.toLocaleDateString(locale, opts);
  return sf === ef ? sf : `${sf} – ${ef}`;
}

const isoWeekStart = (isoYear: number, isoWeek: number): Date => {
  const januaryFourth = new Date(isoYear, 0, 4);
  const firstWeekStart = startOfLocalWeek(januaryFourth);
  firstWeekStart.setDate(firstWeekStart.getDate() + (isoWeek - 1) * 7);
  return firstWeekStart;
};

const parsePeriodInputValue = (scale: TimelineScale, value: string): number | null => {
  if (!value) return null;
  if (scale === "month") {
    const match = /^(\d{4})-(\d{2})$/.exec(value);
    if (!match) return null;
    return toUnixSeconds(new Date(Number(match[1]), Number(match[2]) - 1, 1));
  }
  if (scale === "week") {
    const match = /^(\d{4})-W(\d{2})$/.exec(value);
    if (!match) return null;
    return toUnixSeconds(isoWeekStart(Number(match[1]), Number(match[2])));
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  if (scale === "day") return toUnixSeconds(startOfLocalDay(parsed));
  return toUnixSeconds(startOfLocalHour(parsed));
};

function monthKeyForDate(timestampSec: number): string {
  const d = new Date(timestampSec * 1000);
  return `${d.getFullYear()}-${padNumber(d.getMonth() + 1)}`;
}

function isoDateForTimestamp(timestampSec: number): string {
  const d = new Date(timestampSec * 1000);
  return `${d.getFullYear()}-${padNumber(d.getMonth() + 1)}-${padNumber(d.getDate())}`;
}

export const TimelinePage: React.FC = () => {
  const { t, i18n } = useTranslation("app");
  const navigate = useNavigate();
  const timelineLocale = i18n.resolvedLanguage || i18n.language || "en";
  const setActivePanel = useChatShellStore((state) => state.setActivePanel);
  const setTimelinePanel = useChatShellStore((state) => state.setTimelinePanel);

  const [scale, setScale] = useState<TimelineScale>("day");
  const [viewportStart, setViewportStart] = useState<number>(
    () => getLatestCompletePeriodStart("day"),
  );
  const [entrySheetOpen, setEntrySheetOpen] = useState(false);
  const [editingEntry, setEditingEntry] = useState<ManualEntry | null>(null);
  const [manualEntries, setManualEntries] = useState<ManualEntry[]>([]);
  const [viewport, setViewport] = useState<TimelineViewportResponse | null>(null);
  const [moodDays, setMoodDays] = useState<TimelineMoodCalendarDay[]>([]);
  const [standoutItems, setStandoutItems] = useState<TimelineStandoutItem[]>([]);
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [firstLoad, setFirstLoad] = useState(true);
  const [pendingAction, setPendingAction] = useState<Record<string, "pin" | "hide" | null>>({});
  const [coverSaving, setCoverSaving] = useState(false);

  const viewportEnd = getPeriodEnd(scale, viewportStart);
  const latestPeriodStart = getLatestCompletePeriodStart(scale);
  const canGoNext = shiftPeriodStart(scale, viewportStart, 1) <= latestPeriodStart;
  const dateLabel = formatWindowLabel(scale, viewportStart, viewportEnd, timelineLocale);

  const loadViewport = useCallback(async () => {
    // Only show the full-page spinner on the very first load. Subsequent
    // refetches (scale/date switch) keep the previous viewport visible so
    // the page doesn't flash through an empty state.
    if (firstLoad) setLoading(true);
    try {
      const response = await timelineApi.getViewport({
        scale,
        start: viewportStart,
        end: viewportEnd,
        query: query || undefined,
        locale: timelineLocale,
        focus: "self",
      });
      setViewport(response);
    } catch (error: any) {
      toast.error(
        t("timeline.errors.loadFailed", {
          message: error?.message || "unknown",
          defaultValue: "Failed to load timeline",
        })
      );
    } finally {
      setLoading(false);
      setFirstLoad(false);
    }
  }, [scale, viewportStart, viewportEnd, query, timelineLocale, t, firstLoad]);

  const loadManualEntries = useCallback(async () => {
    try {
      const entries = await manualEntriesApi.list({
        timeStart: viewportStart,
        timeEnd: viewportEnd,
      });
      setManualEntries(entries);
    } catch {
      /* best-effort — clusters still render even if entries fetch fails */
    }
  }, [viewportStart, viewportEnd]);

  const loadSidebar = useCallback(async () => {
    const month = monthKeyForDate(viewportStart);
    try {
      const [mood, standout] = await Promise.all([
        timelineApi.getMoodCalendar(month),
        timelineApi.getStandout({
          periodStart: viewportStart,
          periodEnd: viewportEnd,
          limit: 50,
        }),
      ]);
      setMoodDays(mood.days ?? []);
      setStandoutItems(standout.items ?? []);
    } catch {
      /* sidebar is best-effort; failures don't block the main pane */
    }
  }, [viewportStart, viewportEnd]);

  useEffect(() => {
    setActivePanel("timeline");
  }, [setActivePanel]);

  useEffect(() => {
    void loadViewport();
  }, [loadViewport]);

  useEffect(() => {
    void loadSidebar();
  }, [loadSidebar]);

  useEffect(() => {
    void loadManualEntries();
  }, [loadManualEntries]);

  const handleTogglePinned = async (episodeId: string, nextPinned: boolean) => {
    setPendingAction((s) => ({ ...s, [episodeId]: "pin" }));
    try {
      await memoryApi.annotateEpisode(episodeId, { user_pinned: nextPinned });
      // Optimistic local update so the ♡ flips immediately
      setViewport((current) => {
        if (!current) return current;
        return {
          ...current,
          clusters: current.clusters.map((c) =>
            c.episode_id === episodeId ? { ...c, user_pinned: nextPinned } : c
          ),
        };
      });
      await loadSidebar();
    } catch (error: any) {
      toast.error(
        t("timeline.errors.feedbackFailed", {
          message: error?.message || "unknown",
          defaultValue: "Failed to update",
        })
      );
    } finally {
      setPendingAction((s) => ({ ...s, [episodeId]: null }));
    }
  };

  const handleHide = async (episodeId: string) => {
    setPendingAction((s) => ({ ...s, [episodeId]: "hide" }));
    try {
      await memoryApi.forgetEpisode(episodeId, false);
      setViewport((current) => {
        if (!current) return current;
        return {
          ...current,
          clusters: current.clusters.filter((c) => c.episode_id !== episodeId),
        };
      });
      await loadSidebar();
      toast.success(
        t("timeline.immersive.hideConfirm", { defaultValue: "已隐藏" })
      );
    } catch (error: any) {
      toast.error(
        t("timeline.errors.feedbackFailed", {
          message: error?.message || "unknown",
          defaultValue: "Failed to hide",
        })
      );
    } finally {
      setPendingAction((s) => ({ ...s, [episodeId]: null }));
    }
  };

  const handleChangeCover = useCallback(async (payload: TimelineCoverChangeRequest) => {
    setCoverSaving(true);
    try {
      const cover = await timelineApi.setCoverPreference({
        scale,
        start: viewportStart,
        end: viewportEnd,
        mode: payload.mode,
        asset_ref: payload.asset_ref,
        source: payload.source,
        locale: timelineLocale,
      });
      setViewport((current) => (current ? { ...current, cover } : current));
      toast.success(t("timeline.cover.saved", { defaultValue: "封面已更新" }));
    } catch (error: any) {
      toast.error(
        t("timeline.errors.coverFailed", {
          message: error?.message || "unknown",
          defaultValue: "封面更新失败：{{message}}",
        })
      );
    } finally {
      setCoverSaving(false);
    }
  }, [scale, timelineLocale, t, viewportEnd, viewportStart]);

  const handleUploadCover = useCallback(async (file: File): Promise<string> => {
    try {
      const uploaded = await manualEntriesApi.uploadAsset(file);
      return uploaded.asset_ref;
    } catch (error: any) {
      toast.error(
        t("timeline.errors.coverUploadFailed", {
          message: error?.message || "unknown",
          defaultValue: "封面图片上传失败：{{message}}",
        })
      );
      throw error;
    }
  }, [t]);

  const handleSelectDate = useCallback((isoDate: string) => {
    const [y, m, d] = isoDate.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    const newStart =
      scale === "day"
        ? toUnixSeconds(startOfLocalDay(dt))
        : scale === "hour"
          ? toUnixSeconds(startOfLocalHour(dt))
          : scale === "week"
            ? toUnixSeconds(startOfLocalWeek(dt))
            : toUnixSeconds(startOfLocalMonth(dt));
    setViewportStart(clampToLatestCompletePeriod(scale, newStart));
  }, [scale]);

  /** Drill-down: jump from week-strip card into the day view of that date. */
  const handleSelectDayFromWeek = useCallback((isoDate: string) => {
    const [y, m, d] = isoDate.split("-").map(Number);
    const dayStart = toUnixSeconds(startOfLocalDay(new Date(y, m - 1, d)));
    setScale("day");
    setViewportStart(clampToLatestCompletePeriod("day", dayStart));
  }, []);

  const handleScaleChange = useCallback((next: TimelineScale) => {
    setScale(next);
    setViewportStart(getLatestCompletePeriodStart(next));
  }, []);

  const handlePrevious = useCallback(() => {
    setViewportStart((v) => shiftPeriodStart(scale, v, -1));
  }, [scale]);

  const handleNext = useCallback(() => {
    setViewportStart((v) => clampToLatestCompletePeriod(scale, shiftPeriodStart(scale, v, 1)));
  }, [scale]);

  const handleDraftQueryChange = useCallback((next: string) => {
    setDraftQuery(next);
  }, []);

  const handleSubmitQuery = useCallback(() => {
    setQuery(draftQuery.trim());
  }, [draftQuery]);

  /**
   * Click a "值得回来的" item → jump to its day. Switches scale to "day"
   * and sets viewportStart to the local midnight of the episode's date.
   * (A future enhancement could scroll-to + highlight the specific
   * episode within the day, but jumping there is the meaningful step.)
   */
  const handleSelectStandoutEpisode = useCallback((episodeId: string) => {
    const item = standoutItems.find((s) => s.episode_id === episodeId);
    if (!item) return;
    const dayStart = toUnixSeconds(startOfLocalDay(new Date(item.start * 1000)));
    setScale("day");
    setViewportStart(clampToLatestCompletePeriod("day", dayStart));
  }, [standoutItems]);

  const handleSelectFromDateInput = useCallback((value: string) => {
    const parsed = parsePeriodInputValue(scale, value);
    if (parsed == null) return;
    setViewportStart(clampToLatestCompletePeriod(scale, parsed));
  }, [scale]);

  const handleOpenExperience = useCallback(
    (experienceId: string) => {
      navigate(`/memory/episodes/${encodeURIComponent(experienceId)}`);
    },
    [navigate],
  );

  const handleOrganizeExperience = useCallback(() => {
    navigate("/memory/episodes");
  }, [navigate]);

  // Selection range covered by the current viewport — used by the sidebar
  // calendar to highlight one cell (day/hour), a 7-cell band (week), or the
  // full month (month scale).
  const { selectedRangeStart, selectedRangeEnd } = (() => {
    const end = new Date(viewportEnd * 1000);
    // viewportEnd is exclusive (next-period start) — step back one second to
    // get the last covered date.
    end.setSeconds(end.getSeconds() - 1);
    return {
      selectedRangeStart: isoDateForTimestamp(viewportStart),
      selectedRangeEnd: isoDateForTimestamp(Math.floor(end.getTime() / 1000)),
    };
  })();

  // Push all timeline state into the shell store for Sidebar + AppTitleBar
  useEffect(() => {
    setTimelinePanel({
      monthForCalendar: monthKeyForDate(viewportStart),
      selectedDate: isoDateForTimestamp(viewportStart),
      selectedRangeStart,
      selectedRangeEnd,
      moodDays,
      standoutItems,
      onSelectDate: handleSelectDate,
      onSelectStandoutEpisode: handleSelectStandoutEpisode,
      scale,
      dateLabel,
      viewportStart,
      draftQuery,
      canGoNext,
      onScaleChange: handleScaleChange,
      onPrevious: handlePrevious,
      onNext: handleNext,
      onDraftQueryChange: handleDraftQueryChange,
      onSubmitQuery: handleSubmitQuery,
      onSelectFromDateInput: handleSelectFromDateInput,
    });
  }, [
    viewportStart,
    selectedRangeStart,
    selectedRangeEnd,
    moodDays,
    standoutItems,
    scale,
    dateLabel,
    draftQuery,
    canGoNext,
    handleSelectDate,
    handleSelectStandoutEpisode,
    handleScaleChange,
    handlePrevious,
    handleNext,
    handleDraftQueryChange,
    handleSubmitQuery,
    handleSelectFromDateInput,
    setTimelinePanel,
  ]);

  // Global "n" hotkey opens the quick-entry sheet — only when no input
  // already has focus (otherwise typing "n" in the search box would
  // hijack the keystroke).
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'n' && e.key !== 'N') return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const active = document.activeElement;
      const tag = active?.tagName?.toLowerCase();
      if (tag === 'input' || tag === 'textarea' || (active as HTMLElement)?.isContentEditable) {
        return;
      }
      e.preventDefault();
      setEntrySheetOpen(true);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const handleEntrySaved = useCallback(() => {
    // Re-fetch entries (primary timeline placement) + viewport (so any
    // L2-derived clusters reflect the new event) + sidebar.
    void loadManualEntries();
    void loadViewport();
    void loadSidebar();
    setEditingEntry(null);
  }, [loadManualEntries, loadViewport, loadSidebar]);

  const handleEditEntry = useCallback((entry: ManualEntry) => {
    setEditingEntry(entry);
    setEntrySheetOpen(true);
  }, []);

  const handleDeleteEntry = useCallback(async (entryId: string) => {
    try {
      await manualEntriesApi.remove(entryId);
      toast.success(t('timeline.manualEntry.deletedToast', { defaultValue: '已删除' }));
      await loadManualEntries();
      await loadViewport();
    } catch (err: any) {
      toast.error(
        t('timeline.manualEntry.errors.deleteFailed', {
          defaultValue: '删除失败',
          message: err?.message,
        }),
      );
    }
  }, [loadManualEntries, loadViewport, t]);

  return (
    <main className="flex h-full min-h-0 flex-col overflow-hidden bg-background">
      {/* Block layout (not flex) so PeriodCard/HourDetail fill the column width
          when the sidebar's secondary panel collapses. With flex-row, children
          size to content, leaving a white strip on the right after the
          sidebar shrinks. */}
      <div className="min-h-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        {loading && !viewport ? (
          <div className="flex h-full w-full items-center justify-center gap-2 text-sm text-muted-foreground">
            <LoadingSpinner className="h-4 w-4" />
            {t("timeline.loading", { defaultValue: "加载中" })}
          </div>
        ) : viewport ? (
          scale === "hour" ? (
            <HourDetail viewport={viewport} />
          ) : (
            <PeriodCard
              scale={scale}
              viewport={viewport}
              dateLabel={dateLabel}
              onTogglePinned={handleTogglePinned}
              onHide={handleHide}
              pendingAction={pendingAction}
              onSelectDay={handleSelectDayFromWeek}
              manualEntries={manualEntries}
              onEditManualEntry={handleEditEntry}
              onDeleteManualEntry={handleDeleteEntry}
              onChangeCover={handleChangeCover}
              onUploadCover={handleUploadCover}
              coverSaving={coverSaving}
              onOpenExperience={handleOpenExperience}
              onOrganizeExperience={handleOrganizeExperience}
              onAddNote={() => setEntrySheetOpen(true)}
            />
          )
        ) : null}
      </div>

      {/* Floating ✎ button for manual memory entries. Hidden while the
          sheet is open so it doesn't sit on top of the dialog overlay. */}
      {!entrySheetOpen && scale !== "day" ? (
        <button
          type="button"
          onClick={() => setEntrySheetOpen(true)}
          title={t('timeline.manualEntry.openButton', { defaultValue: '记一笔 (n)' })}
          aria-label={t('timeline.manualEntry.openButton', { defaultValue: '记一笔' })}
          className={cn(
            'absolute bottom-6 right-6 z-20 flex h-12 w-12 items-center justify-center rounded-full',
            'bg-foreground text-background shadow-lg',
            'transition-transform hover:scale-105 active:scale-95',
          )}
        >
          <Feather className="h-5 w-5" />
        </button>
      ) : null}

      <QuickEntrySheet
        open={entrySheetOpen}
        existingEntry={editingEntry}
        onClose={() => { setEntrySheetOpen(false); setEditingEntry(null); }}
        onSaved={handleEntrySaved}
        initialLocationLabel={viewport?.place_hints?.[0] ?? null}
      />
    </main>
  );
};

export default TimelinePage;
