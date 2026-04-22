/**
 * Settings panel for the control plane: global permission mode,
 * plan-approval requirement, session-level override, and saved rules.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import {
  ControlSettingsDTO,
  PermissionMode,
  PermissionRuleDTO,
  clearSessionPermissionRules,
  deletePermissionRule,
  getControlSettings,
  getSessionSettings,
  listPermissionRules,
  updateControlSettings,
  updateSessionSettings,
} from '@/api/modules/control';

const MODES: PermissionMode[] = [
  'default',
  'accept_edits',
  'plan',
  'bypass_permissions',
];

export interface ControlSettingsPanelProps {
  /** Optional active session; enables session override controls. */
  sessionId?: string | null;
}

export function ControlSettingsPanel({
  sessionId,
}: ControlSettingsPanelProps) {
  const { t } = useTranslation('control');
  const [settings, setSettings] = useState<ControlSettingsDTO | null>(null);
  const [override, setOverride] = useState<PermissionMode | null>(null);
  const [planApprovalOverride, setPlanApprovalOverride] = useState<
    boolean | null
  >(null);
  const [rules, setRules] = useState<PermissionRuleDTO[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const base = await getControlSettings();
        if (cancelled) return;
        setSettings(base);
        if (sessionId) {
          const bundle = await getSessionSettings(sessionId);
          if (cancelled) return;
          setOverride(bundle.override?.permission_mode ?? null);
          setPlanApprovalOverride(
            bundle.override?.plan_approval_required ?? null,
          );
        }
        const ruleList = await listPermissionRules({ sessionId });
        if (!cancelled) setRules(ruleList);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    };
    void load();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const saveGlobal = async (next: Partial<ControlSettingsDTO>) => {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateControlSettings(next);
      setSettings(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const saveOverride = async () => {
    if (!sessionId) return;
    setSaving(true);
    setError(null);
    try {
      await updateSessionSettings(sessionId, {
        permission_mode: override,
        plan_approval_required: planApprovalOverride,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const clearOverride = async () => {
    if (!sessionId) return;
    setSaving(true);
    setError(null);
    try {
      await updateSessionSettings(sessionId, { clear: true });
      setOverride(null);
      setPlanApprovalOverride(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const removeRule = async (ruleId: string) => {
    try {
      await deletePermissionRule(ruleId, sessionId ?? null);
      setRules((prev) => prev.filter((r) => r.rule_id !== ruleId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const clearAllSessionRules = async () => {
    if (!sessionId) return;
    try {
      await clearSessionPermissionRules(sessionId);
      setRules((prev) => prev.filter((r) => r.session_id !== sessionId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  if (!settings) return null;

  return (
    <div className="space-y-4" data-testid="control-settings-panel">
      <Card>
        <CardHeader>
          <CardTitle>{t('settings.title')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <div className="mb-1 text-sm font-medium">
              {t('settings.permission_mode')}
            </div>
            <div className="mb-2 text-xs text-muted-foreground">
              {t('settings.permission_mode_description')}
            </div>
            <div className="flex flex-wrap gap-2">
              {MODES.map((m) => (
                <Button
                  key={m}
                  size="sm"
                  variant={
                    settings.permission_mode === m ? 'default' : 'outline'
                  }
                  disabled={saving}
                  onClick={() => void saveGlobal({ permission_mode: m })}
                  data-testid={`mode-${m}`}
                >
                  {t(`settings.mode.${m}`)}
                </Button>
              ))}
            </div>
          </div>
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm font-medium">
                {t('settings.plan_approval_required')}
              </div>
              <div className="text-xs text-muted-foreground">
                {t('settings.plan_approval_description')}
              </div>
            </div>
            <Switch
              checked={settings.plan_approval_required}
              onCheckedChange={(v) =>
                void saveGlobal({ plan_approval_required: v })
              }
              disabled={saving}
              data-testid="plan-approval-switch"
            />
          </div>
          {error && <div className="text-sm text-destructive">{error}</div>}
        </CardContent>
      </Card>

      {sessionId && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {t('settings.session_override')}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-xs text-muted-foreground">
              {t('settings.session_override_description')}
            </div>
            <div className="flex flex-wrap gap-2">
              {MODES.map((m) => (
                <Button
                  key={m}
                  size="sm"
                  variant={override === m ? 'default' : 'outline'}
                  onClick={() => setOverride(override === m ? null : m)}
                  data-testid={`override-${m}`}
                >
                  {t(`settings.mode.${m}`)}
                </Button>
              ))}
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => void saveOverride()}
                disabled={saving}
              >
                {t('settings.save')}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => void clearOverride()}
                disabled={saving}
              >
                {t('settings.clear_override')}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-base">
            {t('settings.rules_title')}
          </CardTitle>
          {sessionId && rules.some((r) => r.session_id === sessionId) && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => void clearAllSessionRules()}
            >
              {t('settings.clear_session_rules')}
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {rules.length === 0 ? (
            <div className="text-sm text-muted-foreground">
              {t('settings.rules_empty')}
            </div>
          ) : (
            <ul className="space-y-2">
              {rules.map((rule) => (
                <li
                  key={rule.rule_id}
                  className="flex items-center justify-between gap-2 rounded border p-2 text-sm"
                  data-testid={`rule-${rule.rule_id}`}
                >
                  <div className="min-w-0 flex-1">
                    <code className="font-mono">{rule.tool}</code>
                    {rule.pattern && (
                      <span className="ml-1 text-muted-foreground">
                        / {rule.pattern}
                      </span>
                    )}
                    <div className="text-xs text-muted-foreground">
                      {rule.outcome} · {rule.scope}
                      {rule.session_id ? ` · ${rule.session_id}` : ''}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void removeRule(rule.rule_id)}
                  >
                    {t('settings.delete_rule')}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
