import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, Clock3, FileText, Image, MapPin, Pencil, Smile, X } from 'lucide-react';
import { toast } from 'sonner';

import {
  manualEntriesApi,
  weatherEmoji,
  type ManualEntry,
  type ManualEntryWeather,
  type MoodValence,
} from '@/api/modules/manualEntries';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { ProtectedImage } from '@/components/media/ProtectedImage';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Calendar } from '@/components/ui/calendar';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { RichTextEditor } from './RichTextEditor';
import { resolveTimelineAssetUrl } from '@/utils/timelineAssetUrl';
import { cn } from '@/lib/utils';

interface QuickEntrySheetProps {
  open: boolean;
  onClose: () => void;
  /** When provided, the sheet opens in edit mode pre-filled with this entry. */
  existingEntry?: ManualEntry | null;
  /** Fired after a successful create or update. */
  onSaved?: (entry: ManualEntry) => void;
  /** Auto-attached location chip (from LocationResolver), if available. */
  initialLocationLabel?: string | null;
}

/** Local state for an image attachment that may still be uploading. */
interface AttachmentDraft {
  /** Stable local id (uuid-ish) so React's key matching is stable across renders. */
  draftId: string;
  /** Server-assigned ref once upload completes. */
  assetRef: string | null;
  /** Object URL for instant preview while uploading. */
  previewUrl: string;
  status: 'uploading' | 'ready' | 'error';
  errorMessage?: string;
}

const MOODS: MoodValence[] = ['warm', 'bright', 'neutral', 'cool', 'tense'];

/** Face emojis communicate valence better than abstract color circles —
 *  people read 😌 / 😊 / 😐 / 😔 / 😣 without needing a legend. */
const MOOD_EMOJI: Record<MoodValence, string> = {
  warm: '😌',
  bright: '😊',
  neutral: '😐',
  cool: '😔',
  tense: '😣',
};

/** Hover/title hint per pill so the meaning isn't completely emoji-bound. */
const MOOD_HINT: Record<MoodValence, { labelKey: string; defaultLabel: string }> = {
  warm: { labelKey: 'timeline.manualEntry.moods.warm', defaultLabel: '舒适 / 放松' },
  bright: { labelKey: 'timeline.manualEntry.moods.bright', defaultLabel: '开朗 / 明亮' },
  neutral: { labelKey: 'timeline.manualEntry.moods.neutral', defaultLabel: '一般' },
  cool: { labelKey: 'timeline.manualEntry.moods.cool', defaultLabel: '低落 / 收敛' },
  tense: { labelKey: 'timeline.manualEntry.moods.tense', defaultLabel: '紧张 / 压力' },
};

const MAX_UPLOAD_MB = 10;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

type TimeShift =
  | { kind: 'now' }
  | { kind: 'minus-hour'; hours: number }
  | { kind: 'this-morning' }
  | { kind: 'last-night' }
  | { kind: 'custom'; eventAt: number };

const TIME_SHIFT_PRESETS: Array<{ id: TimeShift['kind']; labelKey: string; defaultLabel: string }> = [
  { id: 'now', labelKey: 'timeline.manualEntry.timeShift.now', defaultLabel: '刚才' },
  { id: 'minus-hour', labelKey: 'timeline.manualEntry.timeShift.hourAgo', defaultLabel: '1 小时前' },
  { id: 'this-morning', labelKey: 'timeline.manualEntry.timeShift.thisMorning', defaultLabel: '今早' },
  { id: 'last-night', labelKey: 'timeline.manualEntry.timeShift.lastNight', defaultLabel: '昨晚' },
  { id: 'custom', labelKey: 'timeline.manualEntry.timeShift.custom', defaultLabel: '自定义…' },
];

function shiftToEventAt(shift: TimeShift, anchor: Date = new Date()): number {
  switch (shift.kind) {
    case 'now':
      return Math.floor(anchor.getTime() / 1000);
    case 'minus-hour':
      return Math.floor(anchor.getTime() / 1000) - shift.hours * 3600;
    case 'this-morning': {
      const d = new Date(anchor);
      d.setHours(9, 0, 0, 0);
      return Math.floor(d.getTime() / 1000);
    }
    case 'last-night': {
      const d = new Date(anchor);
      d.setDate(d.getDate() - 1);
      d.setHours(22, 0, 0, 0);
      return Math.floor(d.getTime() / 1000);
    }
    case 'custom':
      return shift.eventAt;
  }
}

function shiftLabel(shift: TimeShift, t: (k: string, opts?: any) => string): string {
  const preset = TIME_SHIFT_PRESETS.find((p) => p.id === shift.kind);
  if (!preset) return '';
  if (shift.kind === 'custom') {
    const d = new Date(shift.eventAt * 1000);
    return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  }
  return t(preset.labelKey, { defaultValue: preset.defaultLabel });
}

let _draftCounter = 0;
function nextDraftId(): string {
  _draftCounter += 1;
  return `draft-${Date.now()}-${_draftCounter}`;
}

function nextManualEntryId(): string {
  return `me-${globalThis.crypto.randomUUID()}`;
}

function normalizeLocationHint(value: string | null | undefined): string | null {
  const normalized = value?.trim();
  return normalized ? normalized : null;
}

interface CreateAttempt {
  fingerprint: string;
  entryId: string;
  eventAt: number;
}

function timeShiftFingerprint(shift: TimeShift): string {
  switch (shift.kind) {
    case 'now':
    case 'this-morning':
    case 'last-night':
      return shift.kind;
    case 'minus-hour':
      return `${shift.kind}:${shift.hours}`;
    case 'custom':
      return `${shift.kind}:${shift.eventAt}`;
  }
}

function createDraftFingerprint({
  body,
  bodyDoc,
  mood,
  location,
  attachmentRefs,
  timeShift,
}: {
  body: string;
  bodyDoc: Record<string, unknown> | null;
  mood: MoodValence | null;
  location: string | null;
  attachmentRefs: string[];
  timeShift: TimeShift;
}): string {
  return JSON.stringify({
    body: body.trim(),
    bodyDoc,
    mood,
    location,
    attachmentRefs,
    timeShift: timeShiftFingerprint(timeShift),
  });
}

interface MemoryForgetConflict {
  reason: 'time_range' | 'source_reference' | null;
  sourcePreserved: boolean | null;
  retryAsNew: boolean | null;
}

function getMemoryForgetConflict(error: unknown): MemoryForgetConflict | null {
  if (!error || typeof error !== 'object') return null;
  const candidate = error as {
    code?: unknown;
    details?: unknown;
  };
  const details = candidate.details && typeof candidate.details === 'object'
    ? candidate.details as {
      code?: unknown;
      reason?: unknown;
      source_preserved?: unknown;
      retry_as_new?: unknown;
    }
    : null;
  if (
    candidate.code !== 'manual_entry_memory_forgotten'
    && details?.code !== 'manual_entry_memory_forgotten'
  ) {
    return null;
  }
  return {
    reason: details?.reason === 'time_range' || details?.reason === 'source_reference'
      ? details.reason
      : null,
    sourcePreserved: typeof details?.source_preserved === 'boolean'
      ? details.source_preserved
      : null,
    retryAsNew: typeof details?.retry_as_new === 'boolean'
      ? details.retry_as_new
      : null,
  };
}

/** Editor mode. ``quick`` is a plain <textarea> — the default for new
 *  entries because most captures are short and the toolbar would feel
 *  ceremonial. ``long`` swaps in Tiptap with the full toolbar; entries
 *  with a body_doc on load open here automatically. */
type EditorMode = 'quick' | 'long';

export const QuickEntrySheet: React.FC<QuickEntrySheetProps> = ({
  open,
  onClose,
  existingEntry,
  onSaved,
  initialLocationLabel,
}) => {
  const { t } = useTranslation('app');
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const createAttemptRef = useRef<CreateAttempt | null>(null);
  const editRetryAsNewRef = useRef(false);
  const wasOpenRef = useRef(false);
  const initializedEntryKeyRef = useRef<string | null>(null);
  const locationEditedRef = useRef(false);
  const autoLocationLabelRef = useRef<string | null>(null);

  const [body, setBody] = useState('');
  const [mode, setMode] = useState<EditorMode>('quick');
  /** ProseMirror JSON document — kept in lockstep with `body` (the
   *  plain-text projection) via RichTextEditor's onChange callbacks.
   *  Null until the editor mounts and emits its first onUpdate. */
  const [bodyDoc, setBodyDoc] = useState<Record<string, unknown> | null>(null);
  const [attachments, setAttachments] = useState<AttachmentDraft[]>([]);
  const [mood, setMood] = useState<MoodValence | null>(null);
  const [timeShift, setTimeShift] = useState<TimeShift>({ kind: 'now' });
  /** Single Radix Popover for time selection; Popper handles edge collision
   *  so the calendar can't overflow the sheet boundary. */
  const [timePickerOpen, setTimePickerOpen] = useState(false);
  /** Mood is now a popover-driven chip (same shape as time/location).
   *  The inline 5-pill row took too much horizontal space and looked
   *  asymmetric next to the two other dropdown chips. */
  const [moodPickerOpen, setMoodPickerOpen] = useState(false);
  const [location, setLocation] = useState<string | null>(null);
  /** Inline location input — replaces window.prompt which is silently
   *  swallowed by Radix Sheet's focus trap. */
  const [editingLocation, setEditingLocation] = useState(false);
  /** Auto-resolved weather snapshot shown read-only on existing entries.
   *  Not editable from the sheet — only ✕ to clear (we don't ask the
   *  user "what was the weather?"; if our auto-resolution is wrong, the
   *  right answer is to drop the chip, not to invent one). */
  const [weather, setWeather] = useState<ManualEntryWeather | null>(null);
  const [saving, setSaving] = useState(false);

  // Initialize once per real open or entry switch. A late location resolver
  // update must not reset text the user has already entered.
  useEffect(() => {
    if (!open) {
      wasOpenRef.current = false;
      initializedEntryKeyRef.current = null;
      createAttemptRef.current = null;
      editRetryAsNewRef.current = false;
      return;
    }

    const entryKey = existingEntry ? `edit:${existingEntry.entry_id}` : 'create';
    if (wasOpenRef.current && initializedEntryKeyRef.current === entryKey) {
      return;
    }
    wasOpenRef.current = true;
    initializedEntryKeyRef.current = entryKey;
    createAttemptRef.current = null;
    editRetryAsNewRef.current = false;
    locationEditedRef.current = false;

    if (existingEntry) {
      autoLocationLabelRef.current = null;
      setBody(existingEntry.body);
      setBodyDoc(existingEntry.body_doc ?? null);
      // Entries that were saved with a rich doc open back into long
      // mode — converting them down to a textarea on every open would
      // be lossy and surprising. Plain-body entries stay in quick mode.
      setMode(existingEntry.body_doc ? 'long' : 'quick');
      setMood(existingEntry.mood);
      setAttachments(existingEntry.attachments.map((ref) => ({
        draftId: nextDraftId(),
        assetRef: ref,
        previewUrl: resolveTimelineAssetUrl(ref) ?? '',
        status: 'ready' as const,
      })));
      setTimeShift({ kind: 'custom', eventAt: existingEntry.event_at });
      setLocation(existingEntry.location_label);
      setWeather(existingEntry.weather ?? null);
    } else {
      const initialAutoLocation = normalizeLocationHint(initialLocationLabel);
      autoLocationLabelRef.current = initialAutoLocation;
      setBody('');
      setBodyDoc(null);
      // New entries always start in quick mode. The "📄 转长文" button
      // is the explicit gesture to promote — keeps casual captures
      // casual and rich text intentional.
      setMode('quick');
      setAttachments([]);
      setMood(null);
      setTimeShift({ kind: 'now' });
      setLocation(initialAutoLocation);
      setWeather(null);
    }
    // Reset transient UI state on every open so stale edit flags from
    // a previous session don't leak through.
    setTimePickerOpen(false);
    setMoodPickerOpen(false);
    setEditingLocation(false);
  }, [open, existingEntry, initialLocationLabel]);

  // Apply a location that resolves after the sheet opens without touching the
  // rest of the draft. Once the user edits or clears location, their choice
  // wins over later resolver updates. Freeze automatic enrichment after the
  // first create attempt because an unknown response may already have
  // committed the exact payload represented by createAttemptRef.
  useEffect(() => {
    if (
      !open
      || existingEntry
      || locationEditedRef.current
      || createAttemptRef.current
    ) {
      return;
    }
    const nextAutoLocation = normalizeLocationHint(initialLocationLabel);
    if (!nextAutoLocation) {
      return;
    }
    if (autoLocationLabelRef.current === nextAutoLocation) {
      return;
    }
    autoLocationLabelRef.current = nextAutoLocation;
    setLocation(nextAutoLocation);
  }, [open, existingEntry, initialLocationLabel]);

  // Free object URLs created for upload previews when the sheet closes.
  useEffect(() => {
    if (open) return;
    return () => {
      attachments.forEach((a) => {
        if (a.previewUrl.startsWith('blob:')) URL.revokeObjectURL(a.previewUrl);
      });
    };
  }, [open, attachments]);

  const anyUploading = attachments.some((a) => a.status === 'uploading');
  const hasContent = body.trim().length > 0 || attachments.some((a) => a.status === 'ready');
  const canSave = hasContent && !anyUploading && !saving;
  const moodHint = useCallback(
    (value: MoodValence) => {
      const hint = MOOD_HINT[value];
      return t(hint.labelKey, { defaultValue: hint.defaultLabel });
    },
    [t],
  );

  const uploadFile = useCallback(async (file: File) => {
    if (file.size > MAX_UPLOAD_BYTES) {
      toast.error(
        t('timeline.manualEntry.errors.imageTooLarge', {
          defaultValue: '图片超过 {{maxMb}}MB 上限',
          maxMb: MAX_UPLOAD_MB,
        }),
      );
      return;
    }
    const draftId = nextDraftId();
    const previewUrl = URL.createObjectURL(file);
    setAttachments((prev) => [
      ...prev,
      { draftId, assetRef: null, previewUrl, status: 'uploading' },
    ]);
    try {
      const { asset_ref } = await manualEntriesApi.uploadAsset(file);
      setAttachments((prev) =>
        prev.map((a) =>
          a.draftId === draftId ? { ...a, assetRef: asset_ref, status: 'ready' } : a,
        ),
      );
    } catch (err: any) {
      setAttachments((prev) =>
        prev.map((a) =>
          a.draftId === draftId
            ? { ...a, status: 'error', errorMessage: err?.message || 'upload failed' }
            : a,
        ),
      );
      toast.error(
        t('timeline.manualEntry.errors.uploadFailed', {
          defaultValue: '图片上传失败',
          message: err?.message,
        }),
      );
    }
  }, [t]);

  // (Image paste is now handled inside RichTextEditor — it forwards
  // image clipboard items via onPasteImages → uploadFile.)

  const handleFilePick = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    Array.from(files).forEach((f) => void uploadFile(f));
    e.target.value = ''; // allow picking the same file twice
  }, [uploadFile]);

  const removeAttachment = useCallback((draftId: string) => {
    setAttachments((prev) => {
      const target = prev.find((a) => a.draftId === draftId);
      if (target && target.previewUrl.startsWith('blob:')) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return prev.filter((a) => a.draftId !== draftId);
    });
  }, []);

  const handleSave = useCallback(async () => {
    if (!canSave) return;
    setSaving(true);
    const refs = attachments
      .filter((a) => a.status === 'ready' && a.assetRef)
      .map((a) => a.assetRef!);
    // Only attach body_doc when we actually have one — sending null
    // would pollute quick-mode saves with an explicit empty document.
    // The backend's reader treats absent and null identically (falls
    // back to plain body), so omitting is the cleaner signal.
    const requestedEventAt = shiftToEventAt(timeShift);
    const createAsNew = !existingEntry || editRetryAsNewRef.current;
    let createAttempt: CreateAttempt | null = null;
    if (createAsNew) {
      const fingerprint = createDraftFingerprint({
        body,
        bodyDoc,
        mood,
        location,
        attachmentRefs: refs,
        timeShift,
      });
      createAttempt = createAttemptRef.current;
      if (!createAttempt || createAttempt.fingerprint !== fingerprint) {
        createAttempt = {
          fingerprint,
          entryId: nextManualEntryId(),
          eventAt: requestedEventAt,
        };
        createAttemptRef.current = createAttempt;
      }
    }
    const eventAt = createAttempt?.eventAt ?? requestedEventAt;
    const payload = {
      body: body.trim(),
      event_at: eventAt,
      mood,
      location_label: location,
      attachment_refs: refs,
      ...(bodyDoc ? { body_doc: bodyDoc } : {}),
    };
    try {
      let result: ManualEntry;
      let memoryStatus: 'ready' | 'pending' = 'ready';
      if (existingEntry && !createAsNew) {
        // Use the empty-string-clears convention for the two text
        // fields the backend supports clearing (mood, location_label).
        // For weather we hit a dedicated DELETE endpoint AFTER the
        // primary update — keeps the update body homogeneous and the
        // weather lifecycle separately auditable.
        result = await manualEntriesApi.update(existingEntry.entry_id, {
          body: payload.body,
          // Include the rich-text doc so formatting survives an edit.
          // Same conditional-attach as create — only send when we have
          // a doc; the backend treats absent / null identically.
          ...(bodyDoc ? { body_doc: bodyDoc } : {}),
          event_at: payload.event_at,
          mood: mood ?? '',
          location_label: location ?? '',
          attachment_refs: payload.attachment_refs,
        });
        if (existingEntry.weather && !weather) {
          // User ✕'d the chip → persist the clear and pick up the
          // refreshed entry (with weather=null) for onSaved.
          try {
            result = await manualEntriesApi.clearWeather(existingEntry.entry_id);
          } catch (clearError) {
            if (getMemoryForgetConflict(clearError)) {
              throw clearError;
            }
            // Non-fatal: the primary edit already landed. Worst case
            // the chip reappears on next open; user can try again.
          }
        }
      } else {
        const created = await manualEntriesApi.create({
          entry_id: createAttempt!.entryId,
          ...payload,
        });
        result = created;
        memoryStatus = created.memory_status;
      }
      toast.success(
        memoryStatus === 'pending'
          ? t('timeline.manualEntry.savedPendingToast', {
            defaultValue: '已记录，相关记忆稍后完成',
          })
          : t('timeline.manualEntry.savedToast', { defaultValue: '已记录' }),
      );
      onSaved?.(result);
      onClose();
    } catch (err: any) {
      const memoryForgetConflict = getMemoryForgetConflict(err);
      if (memoryForgetConflict) {
        // A rejected create cannot reuse its governed identity. An edit keeps
        // targeting the original entry when the source survived. Only an
        // explicitly terminalized edit is retried as a new record.
        if (!existingEntry || createAsNew) {
          createAttemptRef.current = null;
        } else if (memoryForgetConflict.retryAsNew === true) {
          editRetryAsNewRef.current = true;
          createAttemptRef.current = null;
        } else if (
          memoryForgetConflict.sourcePreserved === true
          && memoryForgetConflict.retryAsNew === false
        ) {
          editRetryAsNewRef.current = false;
        }
        toast.error(
          memoryForgetConflict.reason === 'source_reference'
            ? t('timeline.manualEntry.errors.forgottenSourceReference', {
              defaultValue: '这条记录已被遗忘，如需保留请另存',
            })
            : t('timeline.manualEntry.errors.forgottenRange', {
              defaultValue: '这个时间段已被遗忘，请调整时间后重新保存',
            }),
        );
        return;
      }
      toast.error(
        t('timeline.manualEntry.errors.saveFailed', {
          defaultValue: '保存失败',
          message: err?.message,
        }),
      );
    } finally {
      setSaving(false);
    }
  }, [
    canSave, attachments, body, bodyDoc, timeShift, mood, location, weather,
    existingEntry, onClose, onSaved, t,
  ]);

  // Quick-mode textarea handlers — Cmd+Enter saves, image clipboard
  // items get routed to the upload pipeline. (Long mode delegates these
  // to RichTextEditor's internal handlers.)
  const handleQuickTextareaPaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      const items = e.clipboardData?.items;
      if (!items || items.length === 0) return;
      const imageFiles: File[] = [];
      for (let i = 0; i < items.length; i++) {
        const it = items[i];
        if (it.kind === 'file' && it.type.startsWith('image/')) {
          const f = it.getAsFile();
          if (f) imageFiles.push(f);
        }
      }
      if (imageFiles.length > 0) {
        e.preventDefault();
        imageFiles.forEach((f) => void uploadFile(f));
      }
    },
    [uploadFile],
  );

  const handleQuickTextareaKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        void handleSave();
      }
    },
    [handleSave],
  );

  /** Promote a quick capture to long mode. The current plain body is
   *  preserved via RichTextEditor's fallbackPlainText — the editor
   *  wraps it in a single paragraph so the user picks up exactly where
   *  they left off, just with formatting available. */
  const switchToLong = useCallback(() => {
    setBodyDoc(null); // force editor to seed from fallbackPlainText
    setMode('long');
  }, []);

  /** Drop back to quick mode. Lossy by definition — formatting that
   *  doesn't survive plain-text flatten is gone. We don't prompt; the
   *  user explicitly clicked. */
  const switchToQuick = useCallback(() => {
    setBodyDoc(null);
    setMode('quick');
  }, []);

  /** Chip row JSX — mood / time / location / weather. Extracted as a
   *  variable so we can render it ABOVE the editor (where the user
   *  wanted it — set the context first, then write). Quick and long
   *  modes both consume the same JSX, so there's exactly one source
   *  of truth for the chip row's behavior + styling. */
  const chipRow = (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      {/* Mood chip */}
      <Popover open={moodPickerOpen} onOpenChange={setMoodPickerOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className="flex h-8 items-center gap-1.5 rounded-md bg-[hsl(var(--app-chrome-surface)/0.72)] px-3 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.34)] transition-colors hover:bg-[hsl(var(--app-chrome-elevated)/0.72)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
            title={
              mood
                ? `${mood} · ${moodHint(mood)}`
                : t('timeline.manualEntry.moodPlaceholderHint', {
                    defaultValue: '选一个心情',
                  })
            }
          >
            {mood ? (
              <span className="text-base leading-none" aria-hidden="true">
                {MOOD_EMOJI[mood]}
              </span>
            ) : (
              <>
                <Smile className="h-3.5 w-3.5 opacity-70" aria-hidden="true" />
                <span>
                  {t('timeline.manualEntry.moodPlaceholder', { defaultValue: '心情' })}
                </span>
              </>
            )}
            <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden="true" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          side="bottom"
          align="start"
          sideOffset={6}
          className="w-auto rounded-lg border-border/40 bg-[hsl(var(--app-chrome-elevated)/0.98)] p-1 shadow-[0_14px_36px_hsl(var(--foreground)/0.12)]"
        >
          <div className="flex items-center gap-0.5">
            {MOODS.map((m) => {
              const isSelected = mood === m;
              const label = moodHint(m);
              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => {
                    // Same toggle semantics as the old inline pills:
                    // clicking the active emoji clears.
                    setMood(isSelected ? null : m);
                    setMoodPickerOpen(false);
                  }}
                  aria-label={label}
                  aria-pressed={isSelected ? 'true' : 'false'}
                  title={label}
                  className={cn(
                    'flex h-9 w-9 items-center justify-center rounded-md text-xl leading-none transition-colors',
                    isSelected
                      ? 'bg-[hsl(var(--primary)/0.12)] text-foreground shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.28)]'
                      : 'opacity-60 hover:bg-foreground/5 hover:opacity-100',
                  )}
                >
                  {MOOD_EMOJI[m]}
                </button>
              );
            })}
          </div>
        </PopoverContent>
      </Popover>

      {/* Time chip */}
      <Popover open={timePickerOpen} onOpenChange={setTimePickerOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className="flex h-8 items-center gap-1.5 rounded-md bg-[hsl(var(--app-chrome-surface)/0.72)] px-3 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.34)] transition-colors hover:bg-[hsl(var(--app-chrome-elevated)/0.72)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
          >
            <Clock3 className="h-3.5 w-3.5 opacity-70" aria-hidden="true" />
            <span>{shiftLabel(timeShift, t)}</span>
            <ChevronDown className="h-3.5 w-3.5 opacity-60" aria-hidden="true" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          side="bottom"
          align="start"
          sideOffset={6}
          className="w-auto overflow-hidden rounded-lg border-border/40 bg-[hsl(var(--app-chrome-elevated)/0.98)] p-0 shadow-[0_14px_36px_hsl(var(--foreground)/0.12)]"
        >
          <div className="flex flex-col p-1">
            {TIME_SHIFT_PRESETS.filter((p) => p.id !== 'custom').map((preset) => {
              const isActive =
                preset.id === timeShift.kind ||
                (preset.id === 'minus-hour' && timeShift.kind === 'minus-hour');
              return (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => {
                    if (preset.id === 'minus-hour') {
                      setTimeShift({ kind: 'minus-hour', hours: 1 });
                    } else {
                      setTimeShift({ kind: preset.id } as TimeShift);
                    }
                    setTimePickerOpen(false);
                  }}
                  className={cn(
                    'w-full rounded px-2 py-1.5 text-left text-xs',
                    isActive
                      ? 'bg-[hsl(var(--primary)/0.12)] text-foreground'
                      : 'text-foreground/80 hover:bg-foreground/5',
                  )}
                >
                  {t(preset.labelKey, { defaultValue: preset.defaultLabel })}
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => {
                setTimeShift({ kind: 'custom', eventAt: shiftToEventAt(timeShift) });
              }}
              className={cn(
                'w-full rounded px-2 py-1.5 text-left text-xs',
                timeShift.kind === 'custom'
                  ? 'bg-[hsl(var(--primary)/0.12)] text-foreground'
                  : 'text-foreground/80 hover:bg-foreground/5',
              )}
            >
              {t('timeline.manualEntry.timeShift.custom', { defaultValue: '自定义…' })}
            </button>
          </div>
          {timeShift.kind === 'custom' ? (
            <>
              <div className="border-t border-border" />
              <Calendar
                mode="single"
                selected={new Date(shiftToEventAt(timeShift) * 1000)}
                onSelect={(date) => {
                  if (!date) return;
                  const current = new Date(shiftToEventAt(timeShift) * 1000);
                  const next = new Date(date);
                  next.setHours(current.getHours(), current.getMinutes(), 0, 0);
                  setTimeShift({ kind: 'custom', eventAt: Math.floor(next.getTime() / 1000) });
                }}
                initialFocus
              />
              <div className="border-t border-border px-3 py-2">
                <div className="mb-1.5 text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                  {t('timeline.manualEntry.hour', { defaultValue: '时' })}
                </div>
                <div className="grid grid-cols-6 gap-1">
                  {Array.from({ length: 24 }, (_, i) => i).map((h) => {
                    const current = new Date(shiftToEventAt(timeShift) * 1000);
                    const isSel = h === current.getHours();
                    return (
                      <button
                        key={h}
                        type="button"
                        onClick={() => {
                          const dt = new Date(shiftToEventAt(timeShift) * 1000);
                          dt.setHours(h, dt.getMinutes(), 0, 0);
                          setTimeShift({ kind: 'custom', eventAt: Math.floor(dt.getTime() / 1000) });
                        }}
                        className={cn(
                          'rounded px-2 py-1 text-xs',
                          isSel
                            ? 'bg-foreground text-background'
                            : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground',
                        )}
                      >
                        {String(h).padStart(2, '0')}
                      </button>
                    );
                  })}
                </div>
                <div className="mb-1.5 mt-2.5 text-[10px] uppercase tracking-[0.15em] text-muted-foreground">
                  {t('timeline.manualEntry.minute', { defaultValue: '分' })}
                </div>
                <div className="grid grid-cols-4 gap-1">
                  {[0, 15, 30, 45].map((mm) => {
                    const current = new Date(shiftToEventAt(timeShift) * 1000);
                    const bucket = Math.floor(current.getMinutes() / 15) * 15;
                    const isSel = mm === bucket;
                    return (
                      <button
                        key={mm}
                        type="button"
                        onClick={() => {
                          const dt = new Date(shiftToEventAt(timeShift) * 1000);
                          dt.setMinutes(mm, 0, 0);
                          setTimeShift({ kind: 'custom', eventAt: Math.floor(dt.getTime() / 1000) });
                        }}
                        className={cn(
                          'rounded px-2 py-1 text-xs',
                          isSel
                            ? 'bg-foreground text-background'
                            : 'text-muted-foreground hover:bg-foreground/5 hover:text-foreground',
                        )}
                      >
                        :{String(mm).padStart(2, '0')}
                      </button>
                    );
                  })}
                </div>
              </div>
            </>
          ) : null}
        </PopoverContent>
      </Popover>

      {/* Location chip */}
      {editingLocation ? (
        <input
          type="text"
          autoFocus
          defaultValue={location ?? ''}
          placeholder={t('timeline.manualEntry.locationPrompt', {
            defaultValue: '输入地点',
          })}
          onBlur={(e) => {
            const v = e.target.value.trim();
            locationEditedRef.current = true;
            setLocation(v ? v : null);
            setEditingLocation(false);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              (e.target as HTMLInputElement).blur();
            } else if (e.key === 'Escape') {
              e.preventDefault();
              setEditingLocation(false);
            }
          }}
          className="h-8 w-36 rounded-md bg-[hsl(var(--app-chrome-surface)/0.72)] px-3 text-xs shadow-[inset_0_0_0_1px_hsl(var(--border)/0.34)] transition-colors placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
        />
      ) : location ? (
        <span className="flex h-8 items-center gap-1.5 rounded-md bg-[hsl(var(--app-chrome-surface)/0.72)] px-3 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.34)]">
          <MapPin className="h-3 w-3" />
          <button
            type="button"
            onClick={() => setEditingLocation(true)}
            className="hover:underline"
            title={t('timeline.manualEntry.editLocation', { defaultValue: '修改地点' })}
          >
            {location}
          </button>
          <button
            type="button"
            onClick={() => {
              locationEditedRef.current = true;
              setLocation(null);
            }}
            aria-label={t('timeline.manualEntry.clearLocation', { defaultValue: '清除地点' })}
            className="ml-0.5 text-muted-foreground hover:text-foreground"
          >
            ✕
          </button>
        </span>
      ) : (
        <button
          type="button"
          onClick={() => setEditingLocation(true)}
          className="flex h-8 items-center gap-1.5 rounded-md bg-[hsl(var(--app-chrome-surface)/0.72)] px-3 text-muted-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.34)] transition-colors hover:bg-[hsl(var(--app-chrome-elevated)/0.72)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
        >
          <MapPin className="h-3 w-3" />
          {t('timeline.manualEntry.addLocation', { defaultValue: '加地点' })}
        </button>
      )}

      {/* Weather chip — read-only auto-resolved snapshot. */}
      {weather && weatherEmoji(weather.code) ? (
        <span
          className="flex h-8 items-center gap-1.5 rounded-md bg-[hsl(var(--app-chrome-surface)/0.72)] px-3 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.34)]"
          title={t('timeline.manualEntry.weatherTitle', {
            defaultValue: '自动获取的天气',
          })}
        >
          <span aria-hidden="true">{weatherEmoji(weather.code)}</span>
          <span className="tabular-nums">{Math.round(weather.temp_c)}°</span>
          <button
            type="button"
            onClick={() => setWeather(null)}
            aria-label={t('timeline.manualEntry.clearWeather', { defaultValue: '清除天气' })}
            className="ml-0.5 text-muted-foreground hover:text-foreground"
          >
            ✕
          </button>
        </span>
      ) : null}
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <DialogContent
        // DialogContent is already centered (left-50% top-50% +
        // translate -50%/-50%). We only override sizing here.
        // Long mode disables click-outside and Escape dismissal —
        // losing a half-written long entry to an accidental click is
        // the exact frustration this whole mode split is trying to
        // avoid. Quick mode keeps the casual behavior.
        onPointerDownOutside={(e) => {
          if (mode === 'long') e.preventDefault();
        }}
        onEscapeKeyDown={(e) => {
          if (mode === 'long') e.preventDefault();
        }}
        overlayClassName="bg-[hsl(var(--foreground)/0.24)] backdrop-blur-[3px]"
        className={cn(
          // Width: Long mode gets noticeably more horizontal room so
          // the editor + toolbar don't feel cramped. Quick mode stays
          // compact so casual capture is a small visual gesture.
          mode === 'long' ? 'max-w-[820px]' : 'max-w-[640px]',
          // Cap height at 90vh and scroll internally so a very tall
          // editor still leaves breathing room and never overflows.
          // No min-height — Dialog sizes to content by default, which
          // is what we want (no more half-empty quick sheet).
          'max-h-[90vh] overflow-y-auto',
          // Tone down DialogContent's default rounded-2xl. The chip row
          // and editor border all sit at rounded-md, so the original
          // 16px container radius read as "stock template". rounded-lg
          // keeps the container distinct without competing with the
          // inner controls. tailwind-merge resolves the conflict in
          // favor of this later value.
          'overflow-hidden rounded-lg border-0 bg-[hsl(var(--app-chrome-elevated)/0.98)] p-0 shadow-[0_28px_80px_hsl(var(--foreground)/0.20)]',
        )}
      >
        {/* Header. The mode toggle sits on the LEFT as a segmented
            control. A single segmented control reads more naturally
            than two asymmetric buttons ("转长文" button vs. "← 简单
            模式" link). The Dialog's ✕ stays in its native top-right
            slot — pr-10 keeps the header content clear of it. */}
        <DialogHeader className="border-b border-border/30 px-5 py-4 pr-12">
          <div className="flex items-center gap-4">
            <DialogTitle className="text-[17px] font-semibold leading-6 text-foreground">
              {existingEntry
                ? t('timeline.manualEntry.editTitle', { defaultValue: '编辑记录' })
                : mode === 'long'
                ? t('timeline.manualEntry.createLongTitle', { defaultValue: '写一篇…' })
                : t('timeline.manualEntry.createTitle', { defaultValue: '写下…' })}
            </DialogTitle>
            <div className="flex-1" />
            {/* Segmented toggle — two equal pills, the active one
                filled. Both labels use the same noun shape so the
                pairing is obvious. */}
            <div
              role="tablist"
              aria-label={t('timeline.manualEntry.modeToggleAria', {
                defaultValue: '编辑模式',
              })}
              className="flex shrink-0 items-center rounded-md bg-[hsl(var(--app-chrome-surface)/0.72)] p-0.5 text-[11px] shadow-[inset_0_0_0_1px_hsl(var(--border)/0.34)]"
            >
              <button
                type="button"
                role="tab"
                aria-selected={mode === 'quick'}
                onClick={switchToQuick}
                className={cn(
                  // Icon + label parallels the long-mode pill so the
                  // pair reads as a balanced segmented control instead
                  // of a text-only side and an icon-bearing side.
                  'flex h-7 items-center gap-1 rounded px-2.5 transition-colors',
                  mode === 'quick'
                    ? 'bg-[hsl(var(--app-chrome-elevated))] text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <Pencil className="h-3 w-3" />
                {t('timeline.manualEntry.modeQuick', { defaultValue: '简单' })}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === 'long'}
                onClick={switchToLong}
                className={cn(
                  'flex h-7 items-center gap-1 rounded px-2.5 transition-colors',
                  mode === 'long'
                    ? 'bg-[hsl(var(--app-chrome-elevated))] text-foreground shadow-sm'
                    : 'text-muted-foreground hover:text-foreground',
                )}
              >
                <FileText className="h-3 w-3" />
                {t('timeline.manualEntry.modeLong', { defaultValue: '长文' })}
              </button>
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-4 px-5 pb-5 pt-4">
          {/* Chip row goes ABOVE the editor — the user sets the context
              (mood / time / place) first, then writes. Pre-extracted
              into the chipRow constant; same JSX, just one render
              location. */}
          {chipRow}

          {/* Body editor — mode-switched. Quick is a plain textarea (the
              default; matches the casual capture brief). Long mounts
              Tiptap with the formatting toolbar. The plain-text body
              stays in `body` in both paths so the save path is
              identical. */}
          {mode === 'long' ? (
            <RichTextEditor
              value={bodyDoc}
              fallbackPlainText={body}
              onChange={setBodyDoc}
              onChangeText={setBody}
              onPasteImages={(files) => files.forEach((f) => void uploadFile(f))}
              onSubmitShortcut={() => void handleSave()}
              placeholder={t('timeline.manualEntry.placeholderLong', {
                defaultValue: '写下…（⌘+V 粘贴图片，⌘+Enter 保存）',
              })}
              autoFocus
              // Generous writing surface — ~14 rows at 24px line-height.
              // The whole sheet caps at 90vh and scrolls if needed, so
              // this won't push the footer off screen on small windows.
              minHeightPx={360}
            />
          ) : (
            <textarea
              ref={textareaRef}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              onPaste={handleQuickTextareaPaste}
              onKeyDown={handleQuickTextareaKeyDown}
              placeholder={t('timeline.manualEntry.placeholder', {
                defaultValue: '写下…（⌘+V 粘贴图片，⌘+Enter 保存）',
              })}
              autoFocus
              className="min-h-[112px] w-full resize-y rounded-md bg-[hsl(var(--app-chrome-surface)/0.58)] px-3.5 py-3 text-sm leading-6 text-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.36)] transition-[box-shadow,background-color] placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
            />
          )}

          {/* Attachments */}
          <div>
            <div className="flex flex-wrap items-center gap-2">
              {attachments.map((a) => (
                <div
                  key={a.draftId}
                  className={cn(
                    'group relative h-16 w-16 overflow-hidden rounded-md bg-[hsl(var(--app-chrome-surface)/0.68)] shadow-[inset_0_0_0_1px_hsl(var(--border)/0.36)]',
                    a.status === 'uploading' && 'opacity-60',
                    a.status === 'error' && 'shadow-[inset_0_0_0_1px_hsl(var(--destructive)/0.5)]',
                  )}
                >
                  {a.previewUrl ? (
                    <ProtectedImage
                      src={a.previewUrl}
                      alt={t('timeline.manualEntry.attachmentAlt', { defaultValue: '附件图片' })}
                      className="h-full w-full object-cover"
                    />
                  ) : null}
                  {a.status === 'uploading' && (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <LoadingSpinner className="h-4 w-4 text-white drop-shadow" />
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={() => removeAttachment(a.draftId)}
                    title={t('timeline.manualEntry.removeImage', { defaultValue: '移除' })}
                    className="absolute right-1 top-1 rounded-full bg-foreground/70 p-0.5 text-background opacity-0 transition-opacity group-hover:opacity-100"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex h-16 w-16 items-center justify-center rounded-md bg-[hsl(var(--app-chrome-surface)/0.58)] text-muted-foreground shadow-[inset_0_0_0_1px_hsl(var(--border)/0.36)] transition-colors hover:bg-[hsl(var(--app-chrome-elevated)/0.74)] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
                title={t('timeline.manualEntry.addImage', { defaultValue: '添加图片' })}
              >
                <Image className="h-5 w-5" />
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                multiple
                onChange={handleFilePick}
                className="hidden"
              />
            </div>
          </div>


          {/* Footer */}
          <div className="flex items-center justify-end gap-2 border-t border-border/30 pt-4">
            <Button variant="ghost" size="sm" onClick={onClose} disabled={saving} className="px-4">
              {t('timeline.manualEntry.cancel', { defaultValue: '取消' })}
            </Button>
            <Button variant="default" size="sm" disabled={!canSave} onClick={handleSave} className="px-4">
              {saving ? (
                <LoadingSpinner className="mr-1.5 h-3.5 w-3.5" />
              ) : null}
              {t('timeline.manualEntry.save', { defaultValue: '保存' })}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};
