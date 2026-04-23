import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, ChevronUp, Loader2 } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import {
  PermissionMode,
  SessionSettingsBundleDTO,
  getSessionSettings,
  updateSessionSettings,
} from '@/api/modules/control';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import {
  CONTROL_PERMISSION_MODES,
  getPermissionModeLabel,
} from './ControlSettingsPanel';

interface SessionSafetyControlProps {
  sessionId: string | null;
  className?: string;
}

function resolvePermissionOverride(
  bundle: SessionSettingsBundleDTO,
  mode: PermissionMode | null,
): PermissionMode | null {
  if (mode === null) {
    return null;
  }
  return mode === bundle.base.permission_mode ? null : mode;
}

function resolvePlanApprovalOverride(
  bundle: SessionSettingsBundleDTO,
  enabled: boolean,
): boolean | null {
  return enabled === bundle.base.plan_approval_required ? null : enabled;
}

export function SessionSafetyControl({
  sessionId,
  className,
}: SessionSafetyControlProps) {
  const { t } = useTranslation('control');
  const [open, setOpen] = useState(false);
  const [bundle, setBundle] = useState<SessionSettingsBundleDTO | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      if (!sessionId) {
        setBundle(null);
        return;
      }
      try {
        const nextBundle = await getSessionSettings(sessionId);
        if (!cancelled) {
          setBundle(nextBundle);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    };

    void load();
    setOpen(false);

    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !panelRef.current?.contains(target)) {
        setOpen(false);
      }
    };

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };

    window.addEventListener('mousedown', handlePointerDown);
    window.addEventListener('keydown', handleEscape);
    return () => {
      window.removeEventListener('mousedown', handlePointerDown);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  const selectedMode = useMemo<PermissionMode>(
    () => bundle?.effective.permission_mode ?? 'high_only',
    [bundle],
  );

  const triggerLabel = getPermissionModeLabel(t, selectedMode);

  const applyOverride = async (payload: {
    permission_mode?: PermissionMode | null;
    plan_approval_required?: boolean | null;
  }) => {
    if (!sessionId) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const nextBundle = await updateSessionSettings(sessionId, payload);
      setBundle(nextBundle);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleModeSelect = async (mode: PermissionMode | null) => {
    if (!bundle) {
      return;
    }
    await applyOverride({
      permission_mode: resolvePermissionOverride(bundle, mode),
      plan_approval_required: bundle.override?.plan_approval_required ?? null,
    });
    setOpen(false);
  };

  const handlePlanApprovalChange = async (checked: boolean) => {
    if (!bundle) {
      return;
    }
    await applyOverride({
      permission_mode: bundle.override?.permission_mode ?? null,
      plan_approval_required: resolvePlanApprovalOverride(bundle, checked),
    });
  };

  const isUsingGlobalMode = bundle?.override?.permission_mode == null;

  return (
    <div ref={rootRef} className={cn('relative', className)}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-label={t('settings.session_trigger')}
        aria-expanded={open}
        aria-controls={open ? 'chat-session-settings-popover' : undefined}
        disabled={!sessionId}
        className="inline-flex h-8 items-center gap-1 rounded-lg px-2.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted/40 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/35 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span>{triggerLabel}</span>
        <ChevronUp className={cn('h-3.5 w-3.5 transition-transform', !open && 'rotate-180')} />
      </button>

      {open ? (
        <div
          id="chat-session-settings-popover"
          ref={panelRef}
          data-testid="chat-session-settings-popover"
          className="absolute bottom-full left-0 z-20 mb-2 w-[300px] rounded-2xl border border-border/70 bg-background/98 p-2 shadow-[0_18px_50px_rgba(15,23,42,0.14)] backdrop-blur"
        >
          <div className="px-2 pb-2 pt-1">
            <div className="text-sm font-semibold text-foreground">
              {t('settings.session_trigger')}
            </div>
            <div className="mt-1 text-xs leading-5 text-muted-foreground">
              {t('settings.session_override_description')}
            </div>
          </div>

          <div className="space-y-1">
            <button
              type="button"
              onClick={() => void handleModeSelect(null)}
              disabled={saving}
              className="flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted/55 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <div>
                <div className="font-medium text-foreground">
                  {t('settings.follow_global')}
                </div>
                <div className="text-xs text-muted-foreground">
                  {getPermissionModeLabel(t, bundle?.base.permission_mode ?? 'high_only')}
                </div>
              </div>
              {isUsingGlobalMode ? <Check className="h-4 w-4 text-primary" /> : null}
            </button>

            {CONTROL_PERMISSION_MODES.map((mode) => {
              const selected = bundle?.effective.permission_mode === mode;
              return (
                <button
                  type="button"
                  key={mode}
                  onClick={() => void handleModeSelect(mode)}
                  disabled={saving}
                  className="flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left text-sm transition-colors hover:bg-muted/55 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <span className="font-medium text-foreground">
                    {getPermissionModeLabel(t, mode)}
                  </span>
                  {selected ? <Check className="h-4 w-4 text-primary" /> : null}
                </button>
              );
            })}
          </div>

          <div className="mt-2 border-t border-border/60 px-3 py-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-foreground">
                  {t('settings.plan_approval_required')}
                </div>
                <div className="mt-1 text-xs leading-5 text-muted-foreground">
                  {t('settings.plan_approval_description')}
                </div>
              </div>
              <Switch
                checked={bundle?.effective.plan_approval_required ?? false}
                onCheckedChange={(checked) => void handlePlanApprovalChange(checked)}
                disabled={saving || !bundle}
                data-testid="session-safety-plan-approval-switch"
              />
            </div>
          </div>

          {saving ? (
            <div className="flex items-center gap-2 px-3 pb-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              {t('settings.applying')}
            </div>
          ) : null}

          {error ? (
            <div className="px-3 pb-2 text-xs text-destructive">{error}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}