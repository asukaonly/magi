import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Feather, Pencil, Trash2 } from "lucide-react";

import type { TimelineClusterBlock } from "@/api/modules/timeline";
import type { ManualEntry, MoodValence } from "@/api/modules/manualEntries";
import { weatherEmoji } from "@/api/modules/manualEntries";
import { ProtectedImage } from "@/components/media/ProtectedImage";
import { cn } from "@/lib/utils";
import {
  bucketIdForTimestamp,
  formatDurationCompact,
  groupClustersIntoBuckets,
  BUCKET_DEFS,
  type Bucket,
  type BucketId,
  type SourceGroup,
} from "@/lib/timeline-buckets";
import { resolveTimelineAssetUrl } from "@/utils/timelineAssetUrl";
import { renderRichTextHtml } from "@/components/timeline/manual-entries/renderRichText";

import { SourceIcon, labelForSource } from "./SourceIcon";

interface DayBucketsProps {
  clusters: TimelineClusterBlock[];
  manualEntries: ManualEntry[];
  onEditManualEntry?: (entry: ManualEntry) => void;
  onDeleteManualEntry?: (entryId: string) => void;
}

/** Same emoji set as QuickEntrySheet. Kept duplicated here (rather than
 *  importing from the sheet module) so this view doesn't depend on the
 *  edit surface. */
const MOOD_EMOJI: Record<MoodValence, string> = {
  warm: '😌',
  bright: '😊',
  neutral: '😐',
  cool: '😔',
  tense: '😣',
};

function formatHourMinute(sec: number): string {
  const d = new Date(sec * 1000);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function formatTimeRange(startSec: number, endSec: number): string {
  const start = formatHourMinute(startSec);
  const end = formatHourMinute(endSec);
  if (start === end) {
    return `${start} ·`;
  }
  return `${start} – ${end}`;
}

/**
 * Day-scale main content: events grouped into four time-of-day buckets
 * (深夜 / 上午 / 下午 / 晚上). Inside each bucket, the user's own manual
 * entries (if any) are rendered first as a distinct "你的记录" group,
 * then the regular source groups follow, ordered by total duration.
 */
export const DayBuckets: React.FC<DayBucketsProps> = ({
  clusters,
  manualEntries,
  onEditManualEntry,
  onDeleteManualEntry,
}) => {
  const { t } = useTranslation("app");

  // Bucket the (non-deleted) manual entries by their event_at.
  const entriesByBucket = useMemo(() => {
    const map = new Map<BucketId, ManualEntry[]>();
    for (const def of BUCKET_DEFS) map.set(def.id, []);
    for (const entry of manualEntries) {
      if (entry.deleted_at) continue;
      const bucketId = bucketIdForTimestamp(entry.event_at);
      map.get(bucketId)!.push(entry);
    }
    // Within a bucket, sort chronologically
    for (const arr of map.values()) {
      arr.sort((a, b) => a.event_at - b.event_at);
    }
    return map;
  }, [manualEntries]);

  // Exclude clusters whose primary source is manual_entry — those are
  // surfaced via the entries list directly, so showing them twice would
  // be confusing.
  const filteredClusters = useMemo(
    () => clusters.filter((c) => (c.source_types ?? [])[0] !== "manual_entry"),
    [clusters],
  );

  const buckets = groupClustersIntoBuckets(filteredClusters);
  // Merge: keep buckets that have either clusters OR manual entries.
  const visibleBuckets = buckets.filter((b) => {
    const entryCount = entriesByBucket.get(b.id)?.length ?? 0;
    return b.groups.length > 0 || entryCount > 0;
  });

  if (visibleBuckets.length === 0) {
    return (
      <div className="px-10 py-10 text-center text-sm text-muted-foreground">
        {t("timeline.immersive.dayEmpty", { defaultValue: "这一天没什么动静。" })}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-7 px-10 pb-10 pt-3">
      {visibleBuckets.map((bucket) => (
        <BucketSection
          key={bucket.id}
          bucket={bucket}
          manualEntries={entriesByBucket.get(bucket.id) ?? []}
          onEditManualEntry={onEditManualEntry}
          onDeleteManualEntry={onDeleteManualEntry}
        />
      ))}
    </div>
  );
};

const BucketSection: React.FC<{
  bucket: Bucket;
  manualEntries: ManualEntry[];
  onEditManualEntry?: (entry: ManualEntry) => void;
  onDeleteManualEntry?: (entryId: string) => void;
}> = ({ bucket, manualEntries, onEditManualEntry, onDeleteManualEntry }) => {
  const { t } = useTranslation("app");
  const headerLabel = t(`timeline.immersive.bucket.${bucket.id}`, {
    defaultValue: bucket.label,
  });

  // Include manual entries in the total-duration header — give them a
  // notional 5min weight each since manual entries don't have duration.
  const manualNotionalSeconds = manualEntries.length * 300;
  const totalDurationSeconds = bucket.totalDurationSeconds + manualNotionalSeconds;

  return (
    <section>
      <header className="mb-3 flex items-baseline gap-2.5">
        <span className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground">
          {headerLabel}
        </span>
        <span className="font-mono text-[10px] text-muted-foreground/60">
          {String(bucket.startHour).padStart(2, "0")}:00 – {String(bucket.endHour).padStart(2, "0")}:00
        </span>
        <span className="ml-auto font-mono text-[11px] text-muted-foreground/80">
          {formatDurationCompact(totalDurationSeconds)}
        </span>
      </header>
      <div className="flex flex-col gap-4">
        {manualEntries.length > 0 ? (
          <ManualEntryGroup
            entries={manualEntries}
            onEdit={onEditManualEntry}
            onDelete={onDeleteManualEntry}
          />
        ) : null}
        {bucket.groups.map((group) => (
          <SourceGroupBlock key={`${bucket.id}-${group.sourceType}`} group={group} />
        ))}
      </div>
    </section>
  );
};

const ManualEntryGroup: React.FC<{
  entries: ManualEntry[];
  onEdit?: (entry: ManualEntry) => void;
  onDelete?: (entryId: string) => void;
}> = ({ entries, onEdit, onDelete }) => {
  const { t } = useTranslation("app");
  return (
    <div className="relative pl-3">
      {/* Left accent stripe — gives the user's own records a visible "yours" mark */}
      <span
        className="absolute left-0 top-0 h-full w-[2px] rounded-full bg-[#c9a878]"
        aria-hidden="true"
      />
      <div className="mb-1.5 flex items-center gap-1.5">
        <Feather className="h-3.5 w-3.5 text-[#c9a878]" />
        <span className="text-[12px] font-medium text-foreground">
          {t("timeline.manualEntry.groupLabel", { defaultValue: "你的记录" })}
        </span>
        <span className="font-mono text-[11px] text-muted-foreground/50">
          · {t("timeline.manualEntry.entryCount", {
            defaultValue: "{{count}} 条",
            count: entries.length,
          })}
        </span>
      </div>
      <ul className="ml-5 flex flex-col gap-2">
        {entries.map((entry) => (
          <ManualEntryRow
            key={entry.entry_id}
            entry={entry}
            onEdit={onEdit}
            onDelete={onDelete}
          />
        ))}
      </ul>
    </div>
  );
};

const ManualEntryRow: React.FC<{
  entry: ManualEntry;
  onEdit?: (entry: ManualEntry) => void;
  onDelete?: (entryId: string) => void;
}> = ({ entry, onEdit, onDelete }) => {
  const { t } = useTranslation("app");
  const [previewIdx, setPreviewIdx] = useState<number | null>(null);

  const time = formatHourMinute(entry.event_at);

  return (
    <li className="group grid grid-cols-[92px_1fr] items-start gap-3 text-[13px] text-foreground/90">
      <div className="flex items-center gap-1.5 pt-0.5 font-mono text-[11px] text-muted-foreground/70">
        <span>{time}</span>
        {entry.mood ? (
          <span
            className="text-[12px] leading-none"
            title={entry.mood}
            aria-hidden="true"
          >
            {MOOD_EMOJI[entry.mood as MoodValence]}
          </span>
        ) : null}
        {entry.weather && weatherEmoji(entry.weather.code) ? (
          <span
            className="text-[12px] leading-none"
            title={`${entry.weather.code} · ${entry.weather.temp_c}°C`}
            aria-label={`weather ${entry.weather.temp_c} celsius`}
          >
            {weatherEmoji(entry.weather.code)}
            <span className="ml-0.5 text-[10px] tabular-nums">
              {Math.round(entry.weather.temp_c)}°
            </span>
          </span>
        ) : null}
      </div>
      <div>
        {/* Rich-text body: render Tiptap-generated HTML when body_doc is
            present, fall back to plain text otherwise. We trust the
            HTML because it's produced by our own renderRichTextHtml
            (Tiptap's generateHTML against our known extension set) —
            user input never reaches dangerouslySetInnerHTML directly.
            The `prose` classes match the editor's so rendered text
            looks like what the user saw while writing. */}
        {entry.body_doc ? (
          // Trusted HTML: renderRichTextHtml produces output via Tiptap's
          // generateHTML against our own extension set — user input
          // never reaches dangerouslySetInnerHTML directly. The
          // .rich-text-content class is shared with the editor so the
          // visual is identical to what the user saw while writing.
          <div
            className="rich-text-content leading-snug"
            dangerouslySetInnerHTML={{
              __html: renderRichTextHtml(entry.body_doc, entry.body),
            }}
          />
        ) : (
          <div className="whitespace-pre-wrap leading-snug">{entry.body}</div>
        )}
        {entry.attachments.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {entry.attachments.slice(0, 4).map((ref, i) => {
              const url = resolveTimelineAssetUrl(ref);
              if (!url) return null;
              return (
                <button
                  key={ref}
                  type="button"
                  onClick={() => setPreviewIdx(i)}
                  className="h-14 w-14 overflow-hidden rounded border border-border/60 hover:border-foreground/40"
                  aria-label={t("timeline.manualEntry.openImage", { defaultValue: "查看图片" })}
                >
                  <ProtectedImage src={url} alt="" className="h-full w-full object-cover" loading="lazy" />
                </button>
              );
            })}
            {entry.attachments.length > 4 ? (
              <span className="flex h-14 items-end pl-1 text-[11px] text-muted-foreground">
                +{entry.attachments.length - 4}
              </span>
            ) : null}
          </div>
        ) : null}
        <div className="mt-1 flex items-center gap-2 opacity-0 transition-opacity group-hover:opacity-100">
          {onEdit ? (
            <button
              type="button"
              onClick={() => onEdit(entry)}
              className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
              aria-label={t("timeline.manualEntry.editAction", { defaultValue: "编辑" })}
            >
              <Pencil className="h-3 w-3" />
              {t("timeline.manualEntry.editAction", { defaultValue: "编辑" })}
            </button>
          ) : null}
          {onDelete ? (
            <button
              type="button"
              onClick={() => {
                if (window.confirm(t("timeline.manualEntry.confirmDelete", { defaultValue: "删除这条记录？" }))) {
                  onDelete(entry.entry_id);
                }
              }}
              className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-red-500"
              aria-label={t("timeline.manualEntry.deleteAction", { defaultValue: "删除" })}
            >
              <Trash2 className="h-3 w-3" />
              {t("timeline.manualEntry.deleteAction", { defaultValue: "删除" })}
            </button>
          ) : null}
        </div>
      </div>

      {/* Fullscreen image preview when a thumbnail is clicked */}
      {previewIdx !== null ? (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80"
          onClick={() => setPreviewIdx(null)}
          role="dialog"
        >
          <ProtectedImage
            src={resolveTimelineAssetUrl(entry.attachments[previewIdx]) ?? ""}
            alt=""
            eager
            className="max-h-[90vh] max-w-[90vw] object-contain"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      ) : null}
    </li>
  );
};

/**
 * Cluster labels the backend treats as "no useful name" — these appear
 * when episode_formation couldn't extract tags / entities and the cluster
 * builder fell back to the literal default. Rendering the placeholder
 * verbatim (e.g. "activity" four times under a Chrome group) gives the
 * user no signal; we render a soft em-dash instead so the time column
 * still has visual structure but the row isn't shouting "I have no idea
 * what this was".
 *
 * NOTE: lowercase comparison — the backend writes "activity" but a
 * future entrant might capitalize.
 */
const PLACEHOLDER_LABELS = new Set(["activity"]);

function isPlaceholderText(value: string | null | undefined): boolean {
  if (!value) return true;
  const trimmed = value.trim().toLowerCase();
  return trimmed === "" || PLACEHOLDER_LABELS.has(trimmed);
}

const SourceGroupBlock: React.FC<{ group: SourceGroup }> = ({ group }) => {
  const { t } = useTranslation("app");
  const label = labelForSource(group.sourceType, t);
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5">
        <SourceIcon sourceType={group.sourceType} className="h-3.5 w-3.5" />
        <span className="text-[12px] font-medium text-foreground">{label}</span>
        <span className="font-mono text-[11px] text-muted-foreground/70">
          · {formatDurationCompact(group.totalDurationSeconds)}
        </span>
        {group.itemCount > 1 && (
          <span className="font-mono text-[11px] text-muted-foreground/50">
            · {t("timeline.immersive.sourceItemCount", {
              defaultValue: "{{count}} 次",
              count: group.itemCount,
            })}
          </span>
        )}
      </div>
      <ul className="ml-5 flex flex-col gap-1">
        {group.items.map((item) => {
          // Pick the first non-placeholder field. The backend can leave
          // any of these as "" (empty) or "activity" (literal fallback),
          // so we filter both rather than trust truthy-ness alone.
          const candidates = [item.slice_narrative, item.summary, item.label];
          const displayText = candidates.find((c) => !isPlaceholderText(c)) ?? "";
          return (
            <li
              key={item.block_id}
              className={cn(
                "grid grid-cols-[92px_1fr] items-baseline gap-3 text-[13px]",
                "text-foreground/85",
              )}
            >
              <span className="font-mono text-[11px] text-muted-foreground/70">
                {formatTimeRange(item.time_start, item.time_end)}
              </span>
              {displayText ? (
                <span className="leading-snug">{displayText}</span>
              ) : (
                <span
                  className="leading-snug text-muted-foreground/40"
                  aria-label={t("timeline.immersive.noSourceLabel", { defaultValue: "无标签" })}
                >
                  —
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
};
