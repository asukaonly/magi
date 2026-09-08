import { asEventHandler } from '@/utils/as-event-handler';
import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, RefreshCw, X } from 'lucide-react';

import {
  codeAgentApi,
  type AdapterName,
  type CodeAgentSettings,
  type CodeAgentSettingsPatch,
  type DefaultAdapterName,
  type ProbeResult,
} from '@/api/modules/codeAgent';
import { SelectField } from '@/components/config-forms/fields';
import {
  SettingsGroup,
  SettingsSectionShell,
  SettingsSwitchRow,
} from '@/components/settings/SettingsSectionPrimitives';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCenterRefresh } from '@/hooks/useCenterRefresh';

const CLI_ADAPTERS: AdapterName[] = ['claude_code', 'codex'];
const DEFAULT_ADAPTERS: DefaultAdapterName[] = ['auto', ...CLI_ADAPTERS];

const SETTINGS_INPUT_CLASS =
  'h-9 rounded-sm border-[hsl(var(--settings-subnav-border)/0.68)] bg-[hsl(var(--settings-shell-elevated)/0.34)] px-3 text-sm shadow-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--settings-nav-active-foreground)/0.16)] focus-visible:ring-offset-0';
const SETTINGS_MONO_INPUT_CLASS = `${SETTINGS_INPUT_CLASS} font-mono text-xs`;

const ADAPTER_LABELS: Record<AdapterName, string> = {
  claude_code: 'Claude Code',
  codex: 'Codex',
};


export function CodeAgentSection(): JSX.Element {
  const { t } = useTranslation('app');

  const [settings, setSettings] = useState<CodeAgentSettings | null>(null);
  const [probeMap, setProbeMap] = useState<Record<AdapterName, ProbeResult> | null>(null);
  const [loading, setLoading] = useState(true);
  const [rescanning, setRescanning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forbidPathDraft, setForbidPathDraft] = useState('');
  const [timeoutDraft, setTimeoutDraft] = useState('');
  const [savedSettings, setSavedSettings] = useState<CodeAgentSettings | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [saved, setSaved] = useState(false);
  const requestGeneration = useRef(0);
  const savePending = useRef(false);
  const rescanPending = useRef(false);
  const savedRevision = useRef<string | null>(null);
  const refreshGeneration = useRef(0);
  const [conflict, setConflict] = useState(false);
  const hasDraft = useRef(false);
  const timeout = timeoutDraft.trim() ? Number(timeoutDraft) : Number.NaN;
  const timeoutValid = Number.isInteger(timeout) && timeout >= 60 && timeout <= 3600;
  const dirty = JSON.stringify(settings) !== JSON.stringify(savedSettings)
    || timeoutDraft !== String(savedSettings?.constraints.default_timeout_s ?? '');
  hasDraft.current = dirty || Boolean(forbidPathDraft.trim());

  const defaultAdapterOptions = useMemo(
    () =>
      DEFAULT_ADAPTERS.map((name) => ({
        value: name,
        label: name === 'auto' ? t('settings.codeAgent.adapterAuto') : ADAPTER_LABELS[name],
      })),
    [t],
  );

  useEffect(() => {
    const generation = ++requestGeneration.current;
    void (async () => {
      setLoading(true);
      try {
        const [probe, settingsResp] = await Promise.all([
          codeAgentApi.probe(false),
          codeAgentApi.getSettings(null),
        ]);
        if (generation !== requestGeneration.current) return;
        savedRevision.current = settingsResp.revision;
        refreshGeneration.current += 1;
        setProbeMap(probe.results);
        setSettings(settingsResp.settings);
        setSavedSettings(settingsResp.settings);
        setTimeoutDraft(String(settingsResp.settings.constraints.default_timeout_s));
        setForbidPathDraft('');
        setConflict(false);
        setError(null);
      } catch (err) {
        if (generation === requestGeneration.current) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (generation === requestGeneration.current) setLoading(false);
      }
    })();
    return () => {
      requestGeneration.current += 1;
    };
  }, [loadAttempt]);

  useCenterRefresh(async () => {
    if (savePending.current) return;
    const generation = requestGeneration.current;
    const read = ++refreshGeneration.current;
    const baseline = savedRevision.current;
    const [snapshot, probe] = await Promise.all([codeAgentApi.getSettings(null), codeAgentApi.probe(false)]);
    if (generation !== requestGeneration.current || read !== refreshGeneration.current || savePending.current) return;
    if (!rescanPending.current) setProbeMap(probe.results);
    if (hasDraft.current || savedRevision.current !== baseline) return;
    savedRevision.current = snapshot.revision;
    setSettings(snapshot.settings);
    setSavedSettings(snapshot.settings);
    setTimeoutDraft(String(snapshot.settings.constraints.default_timeout_s));
  }, !loading);

  const onRescan = async () => {
    if (rescanPending.current) return;
    rescanPending.current = true;
    refreshGeneration.current += 1;
    const generation = requestGeneration.current;
    setRescanning(true);
    try {
      const out = await codeAgentApi.rescan();
      if (generation === requestGeneration.current) setProbeMap(out.results);
    } catch (err) {
      if (generation === requestGeneration.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      rescanPending.current = false;
      refreshGeneration.current += 1;
      if (generation === requestGeneration.current) setRescanning(false);
    }
  };

  const updateDraft = (patch: CodeAgentSettingsPatch) => {
    hasDraft.current = true;
    setSaved(false);
    setSettings((previous) => previous ? {
      ...previous, ...patch,
      claude_code: { ...previous.claude_code, ...patch.claude_code },
      codex: { ...previous.codex, ...patch.codex },
      constraints: { ...previous.constraints, ...patch.constraints },
    } : previous);
  };

  const saveSettings = async () => {
    if (!settings || !timeoutValid || savePending.current || !savedRevision.current || conflict) return;
    savePending.current = true;
    refreshGeneration.current += 1;
    const generation = requestGeneration.current;
    setSaving(true);
    setSaved(false);
    try {
      const out = await codeAgentApi.patchSettings('user', {
        ...settings, constraints: { ...settings.constraints, default_timeout_s: timeout },
      }, null, savedRevision.current);
      if (generation !== requestGeneration.current) return;
      savedRevision.current = out.revision;
      refreshGeneration.current += 1;
      setSettings(out.settings);
      setSavedSettings(out.settings);
      setTimeoutDraft(String(out.settings.constraints.default_timeout_s));
      setError(null);
      setSaved(true);
    } catch (err) {
      if (generation === requestGeneration.current) {
        const stale = err != null && typeof err === 'object' && 'status' in err && err.status === 409;
        setConflict(stale);
        setError(stale ? t('settings.centerConflict') : err instanceof Error ? err.message : String(err));
      }
    } finally {
      savePending.current = false;
      if (generation === requestGeneration.current) setSaving(false);
    }
  };

  if (loading) {
    return <div role="status" className="flex items-center gap-2 px-6 py-8 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />{t('settings.codeAgent.loading')}
    </div>;
  }
  if (!settings || !probeMap) {
    return <div className="space-y-3 px-6 py-8">
      <p role="alert">{t('settings.codeAgent.loadFailed')}{error ? `: ${error}` : ''}</p>
      <Button onClick={() => setLoadAttempt((attempt) => attempt + 1)}>{t('common.retry')}</Button>
    </div>;
  }

  return (
    <SettingsSectionShell className="space-y-0">
      {error && (
        <div role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
          <Button variant="outline" disabled={saving} onClick={() => setLoadAttempt((attempt) => attempt + 1)}>{t('settings.reloadCenterConfig')}</Button>
        </div>
      )}

      <p className="text-xs text-muted-foreground">{t('settings.codeAgent.userScope')}</p>
      <fieldset disabled={saving} className="min-w-0 space-y-8 border-0 p-0">
      <SettingsSwitchRow
        title={t('settings.codeAgent.enableTitle')}
        description={t('settings.codeAgent.enableDesc')}
        ariaLabel={t('settings.codeAgent.enableTitle')}
        checked={settings.enabled}
        onCheckedChange={asEventHandler((checked) => updateDraft({ enabled: checked }))}
      />

      <SettingsSwitchRow
        title={t('settings.codeAgent.autoApply')}
        description={t('settings.codeAgent.autoApplyDesc')}
        ariaLabel={t('settings.codeAgent.autoApply')}
        checked={settings.auto_apply}
        onCheckedChange={asEventHandler((checked) => updateDraft({ auto_apply: checked }))}
      />

      <SettingsGroup
        title={t('settings.codeAgent.defaultAdapter')}
        description={t('settings.codeAgent.defaultAdapterDesc')}
      >
        <SelectField
          value={settings.default_adapter}
          onChange={asEventHandler((value) => updateDraft({ default_adapter: value === 'auto' || value === 'claude_code' || value === 'codex' ? value : settings.default_adapter }))}
          options={defaultAdapterOptions}
          allowEmpty={false}
          ariaLabel={t('settings.codeAgent.defaultAdapter')}
          triggerClassName={`${SETTINGS_INPUT_CLASS} max-w-sm justify-between`}
          menuClassName="rounded-sm border-[hsl(var(--settings-subnav-border)/0.68)] bg-[hsl(var(--settings-shell-elevated))] shadow-[0_10px_20px_rgba(15,23,42,0.06)]"
        />
      </SettingsGroup>

      <SettingsGroup
        title={t('settings.codeAgent.detectedTools')}
        description={t('settings.codeAgent.detectedToolsDesc')}
      >
        <div className="flex justify-end">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={asEventHandler(onRescan)}
            disabled={rescanning}
            className="inline-flex h-9 items-center gap-1 rounded-sm border-[hsl(var(--settings-subnav-border)/0.72)] bg-transparent shadow-none hover:bg-[hsl(var(--settings-shell-elevated)/0.42)]"
          >
            {rescanning ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            {t('settings.codeAgent.rescan')}
          </Button>
        </div>
        <div className="overflow-hidden rounded-sm border border-[hsl(var(--settings-subnav-border)/0.68)] bg-[hsl(var(--settings-shell-elevated)/0.2)]">
          {CLI_ADAPTERS.map((name) => (
            <ProbeCard
              key={name}
              name={name}
              probe={probeMap[name]}
              settings={settings}
              onPatch={updateDraft}
              t={t}
            />
          ))}
        </div>
      </SettingsGroup>

      <SettingsGroup
        title={t('settings.codeAgent.constraints')}
        description={t('settings.codeAgent.constraintsDesc')}
      >
        <SettingsSwitchRow
          title={t('settings.codeAgent.blockGitCommit')}
          description={t('settings.codeAgent.blockGitCommitDesc')}
          ariaLabel={t('settings.codeAgent.blockGitCommit')}
          checked={settings.constraints.forbid_git_commit}
          onCheckedChange={asEventHandler((checked) =>
            updateDraft({ constraints: { forbid_git_commit: checked } }))
          }
        />
        <SettingsSwitchRow
          title={t('settings.codeAgent.blockGitPush')}
          description={t('settings.codeAgent.blockGitPushDesc')}
          ariaLabel={t('settings.codeAgent.blockGitPush')}
          checked={settings.constraints.forbid_git_push}
          onCheckedChange={asEventHandler((checked) =>
            updateDraft({ constraints: { forbid_git_push: checked } }))
          }
        />

        <div className="space-y-2 pt-2">
          <label htmlFor="code-agent-forbidden-path" className="text-sm font-medium text-foreground">
            {t('settings.codeAgent.forbidPaths')}
          </label>
          <p className="text-xs leading-6 text-muted-foreground">
            {t('settings.codeAgent.forbidPathsDesc')}
          </p>
          <ul className="space-y-1.5">
            {settings.constraints.forbid_paths.map((p) => (
              <li
                key={p}
                className="flex items-center justify-between gap-2 rounded-sm bg-[hsl(var(--settings-shell-elevated)/0.46)] px-3 py-1.5 text-xs"
              >
                <code className="font-mono">{p}</code>
                <button
                  type="button"
                  aria-label={t('settings.codeAgent.removePath', { path: p })}
                  className="text-muted-foreground hover:text-foreground"
                  onClick={asEventHandler(() =>
                    updateDraft({
                      constraints: {
                        forbid_paths: settings.constraints.forbid_paths.filter(
                          (item) => item !== p,
                        ),
                      },
                    }))
                  }
                >
                  <X className="h-3 w-3" />
                </button>
              </li>
            ))}
            {settings.constraints.forbid_paths.length === 0 && (
              <li className="text-xs text-muted-foreground">
                {t('settings.codeAgent.forbidPathsEmpty')}
              </li>
            )}
          </ul>
          <div className="flex gap-2">
            <Input
              id="code-agent-forbidden-path"
              value={forbidPathDraft}
              onChange={(e) => { hasDraft.current = true; setForbidPathDraft(e.target.value); }}
              placeholder={t('settings.codeAgent.forbidPathsPlaceholder')}
              className={SETTINGS_INPUT_CLASS}
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!forbidPathDraft.trim()}
              className="h-9 rounded-sm border-[hsl(var(--settings-subnav-border)/0.72)] bg-transparent shadow-none hover:bg-[hsl(var(--settings-shell-elevated)/0.42)]"
              onClick={() => {
                const value = forbidPathDraft.trim();
                if (!value) return;
                if (settings.constraints.forbid_paths.includes(value)) {
                  setForbidPathDraft('');
                  return;
                }
                updateDraft({
                  constraints: {
                    forbid_paths: [...settings.constraints.forbid_paths, value],
                  },
                });
                setForbidPathDraft('');
              }}
            >
              {t('settings.codeAgent.addPath')}
            </Button>
          </div>
        </div>

        <div className="space-y-2 pt-2">
          <label htmlFor="code-agent-timeout" className="text-sm font-medium text-foreground">
            {t('settings.codeAgent.defaultTimeout')}
          </label>
          <p className="text-xs leading-6 text-muted-foreground">
            {t('settings.codeAgent.defaultTimeoutDesc')}
          </p>
          <div className="flex items-center gap-2">
            <Input
              type="number"
              min={60}
              max={3600}
              id="code-agent-timeout"
              step={1}
              value={timeoutDraft}
              aria-invalid={!timeoutValid}
              aria-describedby={!timeoutValid ? 'code-agent-timeout-error' : undefined}
              onChange={(e) => { hasDraft.current = true; setTimeoutDraft(e.target.value); setSaved(false); }}
              className={`${SETTINGS_INPUT_CLASS} w-32`}
            />
            <span className="text-xs text-muted-foreground">{t('settings.codeAgent.seconds')}</span>
          </div>
        </div>
      </SettingsGroup>

      </fieldset>
      {!timeoutValid && <p id="code-agent-timeout-error" role="alert" className="text-sm text-destructive">{t('settings.codeAgent.invalidTimeout')}</p>}
      <div className="flex items-center gap-3 pt-4">
        <Button disabled={saving || conflict || !dirty || !timeoutValid} onClick={asEventHandler(saveSettings)}>
          {t(saving ? 'settings.codeAgent.saving' : 'common.save')}
        </Button>
        {saved && <p role="status">{t('settings.codeAgent.saved')}</p>}
        {dirty && <p className="text-xs text-muted-foreground">{t('settings.codeAgent.unsaved')}</p>}
      </div>
    </SettingsSectionShell>
  );
}

interface ProbeCardProps {
  name: AdapterName;
  probe: ProbeResult;
  settings: CodeAgentSettings;
  onPatch: (patch: CodeAgentSettingsPatch) => void;
  t: ReturnType<typeof useTranslation>['t'];
}

function ProbeCard({ name, probe, settings, onPatch, t }: ProbeCardProps): JSX.Element {
  const adapterSettings = name === 'claude_code' ? settings.claude_code : settings.codex;
  const installed = probe.installed && !probe.error;
  const binaryPathValue = adapterSettings.binary_path;

  const updateBinaryPath = (value: string) => {
    if (name === 'claude_code') {
      onPatch({ claude_code: { binary_path: value } });
    } else {
      onPatch({ codex: { binary_path: value } });
    }
  };
  const updateModel = (value: string) => {
    if (name === 'claude_code') {
      onPatch({ claude_code: { default_model: value } });
    } else {
      onPatch({ codex: { default_model: value } });
    }
  };

  return (
    <div className="space-y-3 border-b border-[hsl(var(--settings-subnav-border)/0.48)] px-3 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={installed ? 'default' : 'outline'} className="rounded-sm px-2 py-0.5 font-medium">
          {installed ? t('settings.codeAgent.installed') : t('settings.codeAgent.notInstalled')}
        </Badge>
        <span className="text-sm font-medium text-foreground">{ADAPTER_LABELS[name]}</span>
        {probe.version ? <span className="text-xs text-muted-foreground">{probe.version}</span> : null}
      </div>
      {probe.error && (
        <div className="text-xs text-destructive">{probe.error}</div>
      )}

      <div className="grid gap-3 md:grid-cols-[minmax(0,1.35fr)_minmax(0,0.9fr)]">
        <div>
          <label htmlFor={`code-agent-${name}-binary`} className="text-xs font-medium text-muted-foreground">
            {t('settings.codeAgent.binaryPathOverride')}
          </label>
          <Input
            id={`code-agent-${name}-binary`}
            value={binaryPathValue}
            onChange={asEventHandler((e) => updateBinaryPath(e.target.value))}
            placeholder={probe.binary_path || t('settings.codeAgent.binaryPathOverridePlaceholder')}
            className={SETTINGS_MONO_INPUT_CLASS}
          />
        </div>
        <div>
          <label htmlFor={`code-agent-${name}-model`} className="text-xs font-medium text-muted-foreground">
            {t('settings.codeAgent.defaultModel')}
          </label>
          <Input
            id={`code-agent-${name}-model`}
            value={adapterSettings.default_model}
            onChange={asEventHandler((e) => updateModel(e.target.value))}
            placeholder={t('settings.codeAgent.defaultModelPlaceholder')}
            className={SETTINGS_INPUT_CLASS}
          />
        </div>
      </div>
    </div>
  );
}

export default CodeAgentSection;
