import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Image, MapPin, X } from 'lucide-react';
import { toast } from 'sonner';

import {
  manualEntriesApi,
  type ManualEntry,
  type MoodValence,
} from '@/api/modules/manualEntries';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Button } from '@/components/ui/button';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
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

/** Same palette as MoodCalendar — keep the semantic mapping consistent. */
const MOOD_FILL: Record<MoodValence, string> = {
  warm: '#c9a878',
  bright: '#d4b886',
  neutral: '#a8a08a',
  cool: '#7a8898',
  tense: '#b87a78',
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

export const QuickEntrySheet: React.FC<QuickEntrySheetProps> = ({
  open,
  onClose,
  existingEntry,
  onSaved,
  initialLocationLabel,
}) => {
  const { t } = useTranslation('app');
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const [body, setBody] = useState('');
  const [attachments, setAttachments] = useState<AttachmentDraft[]>([]);
  const [mood, setMood] = useState<MoodValence | null>(null);
  const [timeShift, setTimeShift] = useState<TimeShift>({ kind: 'now' });
  const [timePickerOpen, setTimePickerOpen] = useState(false);
  const [location, setLocation] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Pre-fill in edit mode; reset on open/close
  useEffect(() => {
    if (!open) return;
    if (existingEntry) {
      setBody(existingEntry.body);
      setMood(existingEntry.mood);
      setAttachments(existingEntry.attachments.map((ref) => ({
        draftId: nextDraftId(),
        assetRef: ref,
        previewUrl: resolveTimelineAssetUrl(ref) ?? '',
        status: 'ready' as const,
      })));
      setTimeShift({ kind: 'custom', eventAt: existingEntry.event_at });
      setLocation(existingEntry.location_label);
    } else {
      setBody('');
      setAttachments([]);
      setMood(null);
      setTimeShift({ kind: 'now' });
      setLocation(initialLocationLabel ?? null);
    }
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

  const uploadFile = useCallback(async (file: File) => {
    if (file.size > MAX_UPLOAD_BYTES) {
      toast.error(
        t('timeline.manualEntry.errors.imageTooLarge', {
          defaultValue: `图片超过 ${MAX_UPLOAD_MB}MB 上限`,
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

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items || items.length === 0) return;
    const imageItems: File[] = [];
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.kind === 'file' && it.type.startsWith('image/')) {
        const file = it.getAsFile();
        if (file) imageItems.push(file);
      }
    }
    if (imageItems.length > 0) {
      // Pasting an image — suppress the default text-paste of any
      // accompanying clipboard text (Finder often pastes a filename too).
      e.preventDefault();
      imageItems.forEach((f) => void uploadFile(f));
    }
  }, [uploadFile]);

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
    const payload = {
      body: body.trim(),
      event_at: shiftToEventAt(timeShift),
      mood,
      location_label: location,
      attachment_refs: refs,
    };
    try {
      const result = existingEntry
        ? await manualEntriesApi.update(existingEntry.entry_id, {
            body: payload.body,
            event_at: payload.event_at,
            mood: payload.mood ?? '',
            attachment_refs: payload.attachment_refs,
          })
        : await manualEntriesApi.create(payload);
      toast.success(
        t('timeline.manualEntry.savedToast', { defaultValue: '已记录' }),
      );
      onSaved?.(result);
      onClose();
    } catch (err: any) {
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
    canSave, attachments, body, timeShift, mood, location, existingEntry,
    onClose, onSaved, t,
  ]);

  // Cmd/Ctrl+Enter saves from inside the textarea.
  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      void handleSave();
    }
  }, [handleSave]);

  return (
    <Sheet open={open} onOpenChange={(next) => { if (!next) onClose(); }}>
      <SheetContent
        side="bottom"
        className={cn(
          // Override the variant's `inset-x-0 bottom-0` so the sheet is a
          // floating centered card instead of a full-bleed bottom strip.
          // tailwind-merge resolves the conflicting position utilities to
          // the last value (this className wins).
          'left-1/2 right-auto -translate-x-1/2',
          'bottom-6 w-[calc(100%-2rem)] max-w-2xl',
          'rounded-2xl border border-border/70',
        )}
      >
        <SheetHeader className="border-b border-border/40 pb-3">
          <SheetTitle className="text-base font-medium">
            {existingEntry
              ? t('timeline.manualEntry.editTitle', { defaultValue: '编辑记录' })
              : t('timeline.manualEntry.createTitle', { defaultValue: '写下…' })}
          </SheetTitle>
        </SheetHeader>

        <div className="space-y-3 px-6 pb-5 pt-3">
          {/* Body textarea */}
          <textarea
            ref={textareaRef}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={handleKeyDown}
            placeholder={t('timeline.manualEntry.placeholder', {
              defaultValue: '写下…（⌘+V 粘贴图片，⌘+Enter 保存）',
            })}
            autoFocus
            className="min-h-[96px] w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-sm leading-6"
          />

          {/* Attachments */}
          <div>
            <div className="flex flex-wrap items-center gap-2">
              {attachments.map((a) => (
                <div
                  key={a.draftId}
                  className={cn(
                    'group relative h-16 w-16 overflow-hidden rounded-md border',
                    a.status === 'uploading' && 'opacity-60',
                    a.status === 'error' && 'border-red-400',
                  )}
                >
                  {a.previewUrl ? (
                    <img
                      src={a.previewUrl}
                      alt="attachment"
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
                    className="absolute right-0.5 top-0.5 rounded-full bg-black/60 p-0.5 text-white opacity-0 transition-opacity group-hover:opacity-100"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex h-16 w-16 items-center justify-center rounded-md border border-dashed border-border text-muted-foreground hover:bg-foreground/[0.03]"
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

          {/* Mood pills */}
          <div className="flex items-center gap-2">
            <span className="text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
              {t('timeline.manualEntry.moodLabel', { defaultValue: '心情' })}
            </span>
            {MOODS.map((m) => {
              const isSelected = mood === m;
              const fill = MOOD_FILL[m];
              return (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMood(isSelected ? null : m)}
                  aria-label={m}
                  aria-pressed={isSelected ? 'true' : 'false'}
                  title={m}
                  className={cn(
                    'h-5 w-5 rounded-full border transition-all',
                    isSelected
                      ? 'ring-2 ring-foreground/40'
                      : 'opacity-60 hover:opacity-100',
                  )}
                  style={{
                    // Always tinted so the user can recognize each valence
                    // by color; selected version is full saturation + ring.
                    backgroundColor: isSelected ? fill : `${fill}55`,
                    borderColor: isSelected ? fill : `${fill}aa`,
                  }}
                />
              );
            })}
            {mood ? (
              <button
                type="button"
                onClick={() => setMood(null)}
                aria-label="clear mood"
                className="ml-1 text-xs text-muted-foreground hover:text-foreground"
              >
                ✕
              </button>
            ) : null}
          </div>

          {/* Time shift + location row */}
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <div className="relative">
              <button
                type="button"
                onClick={() => setTimePickerOpen((v) => !v)}
                className="flex items-center gap-1 rounded-md border border-border/60 px-2 py-1 hover:bg-foreground/[0.03]"
              >
                🕐 {shiftLabel(timeShift, t)} ▾
              </button>
              {timePickerOpen && (
                <div className="absolute left-0 top-full z-10 mt-1 w-32 overflow-hidden rounded-md border border-border bg-background shadow-lg">
                  {TIME_SHIFT_PRESETS.map((preset) => (
                    <button
                      key={preset.id}
                      type="button"
                      onClick={() => {
                        if (preset.id === 'custom') {
                          const v = window.prompt(
                            t('timeline.manualEntry.customTimePrompt', {
                              defaultValue: '输入时间 (YYYY-MM-DD HH:MM)',
                            }),
                          );
                          if (v) {
                            const parsed = new Date(v);
                            if (!isNaN(parsed.getTime())) {
                              setTimeShift({ kind: 'custom', eventAt: Math.floor(parsed.getTime() / 1000) });
                            }
                          }
                        } else if (preset.id === 'minus-hour') {
                          setTimeShift({ kind: 'minus-hour', hours: 1 });
                        } else {
                          setTimeShift({ kind: preset.id } as TimeShift);
                        }
                        setTimePickerOpen(false);
                      }}
                      className="block w-full px-2 py-1.5 text-left text-xs hover:bg-foreground/5"
                    >
                      {t(preset.labelKey, { defaultValue: preset.defaultLabel })}
                    </button>
                  ))}
                </div>
              )}
            </div>

            {location ? (
              <span className="flex items-center gap-1 rounded-md border border-border/60 px-2 py-1">
                <MapPin className="h-3 w-3" />
                {location}
                <button
                  type="button"
                  onClick={() => setLocation(null)}
                  aria-label="clear location"
                  className="ml-0.5 hover:text-foreground"
                >
                  ✕
                </button>
              </span>
            ) : null}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-2 border-t border-border/40 pt-3">
            <Button variant="ghost" size="sm" onClick={onClose} disabled={saving}>
              {t('timeline.manualEntry.cancel', { defaultValue: '取消' })}
            </Button>
            <Button variant="default" size="sm" disabled={!canSave} onClick={handleSave}>
              {saving ? (
                <LoadingSpinner className="mr-1.5 h-3.5 w-3.5" />
              ) : null}
              {t('timeline.manualEntry.save', { defaultValue: '保存' })}
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
};
