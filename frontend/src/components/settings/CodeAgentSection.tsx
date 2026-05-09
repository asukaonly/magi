import { useEffect, useMemo, useState } from 'react';
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
import { useConversationStore } from '@/stores/conversation-store';

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

  const workspace = useConversationStore((state) => {
    const id = state.currentSessionId;
    if (!id) return null;
    const session = state.sessionsById[id];
    return session?.workspace_path ?? null;
  });

  const [settings, setSettings] = useState<CodeAgentSettings | null>(null);
  const [probeMap, setProbeMap] = useState<Record<AdapterName, ProbeResult> | null>(null);
  const [loading, setLoading] = useState(true);
  const [rescanning, setRescanning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [forbidPathDraft, setForbidPathDraft] = useState('');

  const defaultAdapterOptions = useMemo(
    () =>
      DEFAULT_ADAPTERS.map((name) => ({
        value: name,
        label: name === 'auto' ? t('settings.codeAgent.adapterAuto') : ADAPTER_LABELS[name],
      })),
    [t],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [probe, settingsResp] = await Promise.all([
          codeAgentApi.probe(false),
          codeAgentApi.getSettings(workspace),
        ]);
        if (cancelled) return;
        setProbeMap(probe.results);
        setSettings(settingsResp.settings);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [workspace]);

  const onRescan = async () => {
    setRescanning(true);
    try {
      const out = await codeAgentApi.rescan();
      setProbeMap(out.results);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setRescanning(false);
    }
  };

  const persistUserPatch = async (patch: CodeAgentSettingsPatch) => {
    setSaving(true);
    try {
      const out = await codeAgentApi.patchSettings('user', patch, workspace);
      setSettings(out.settings);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading || !settings || !probeMap) {
    return (
      <div className="flex items-center gap-2 px-6 py-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        {t('settings.codeAgent.loading')}
      </div>
    );
  }

  return (
    <SettingsSectionShell className="space-y-0">
      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <SettingsSwitchRow
        title={t('settings.codeAgent.enableTitle')}
        description={t('settings.codeAgent.enableDesc')}
        ariaLabel={t('settings.codeAgent.enableTitle')}
        checked={settings.enabled}
        onCheckedChange={(checked) => persistUserPatch({ enabled: checked })}
      />

      <SettingsSwitchRow
        title={t('settings.codeAgent.autoApply')}
        description={t('settings.codeAgent.autoApplyDesc')}
        ariaLabel={t('settings.codeAgent.autoApply')}
        checked={settings.auto_apply}
        onCheckedChange={(checked) => persistUserPatch({ auto_apply: checked })}
      />

      <SettingsGroup
        title={t('settings.codeAgent.defaultAdapter')}
        description={t('settings.codeAgent.defaultAdapterDesc')}
      >
        <SelectField
          value={settings.default_adapter}
          onChange={(value) => persistUserPatch({ default_adapter: value as DefaultAdapterName })}
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
            onClick={onRescan}
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
              onPatch={persistUserPatch}
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
          onCheckedChange={(checked) =>
            persistUserPatch({ constraints: { forbid_git_commit: checked } })
          }
        />
        <SettingsSwitchRow
          title={t('settings.codeAgent.blockGitPush')}
          description={t('settings.codeAgent.blockGitPushDesc')}
          ariaLabel={t('settings.codeAgent.blockGitPush')}
          checked={settings.constraints.forbid_git_push}
          onCheckedChange={(checked) =>
            persistUserPatch({ constraints: { forbid_git_push: checked } })
          }
        />

        <div className="space-y-2 pt-2">
          <label className="text-sm font-medium text-foreground">
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
                  onClick={() =>
                    persistUserPatch({
                      constraints: {
                        forbid_paths: settings.constraints.forbid_paths.filter(
                          (item) => item !== p,
                        ),
                      },
                    })
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
              value={forbidPathDraft}
              onChange={(e) => setForbidPathDraft(e.target.value)}
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
                persistUserPatch({
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
          <label className="text-sm font-medium text-foreground">
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
              value={settings.constraints.default_timeout_s}
              onChange={(e) => {
                const v = Number(e.target.value);
                if (Number.isFinite(v) && v >= 60 && v <= 3600) {
                  persistUserPatch({ constraints: { default_timeout_s: v } });
                }
              }}
              className={`${SETTINGS_INPUT_CLASS} w-32`}
            />
            <span className="text-xs text-muted-foreground">{t('settings.codeAgent.seconds')}</span>
          </div>
        </div>
      </SettingsGroup>

      {saving && (
        <div className="text-xs text-muted-foreground">{t('settings.codeAgent.saving')}</div>
      )}
    </SettingsSectionShell>
  );
}

interface ProbeCardProps {
  name: AdapterName;
  probe: ProbeResult;
  settings: CodeAgentSettings;
  onPatch: (patch: CodeAgentSettingsPatch) => Promise<void>;
  t: ReturnType<typeof useTranslation>['t'];
}

function ProbeCard({ name, probe, settings, onPatch, t }: ProbeCardProps): JSX.Element {
  const adapterSettings = name === 'claude_code' ? settings.claude_code : settings.codex;
  const installed = probe.installed && !probe.error;
  const binaryPathValue = adapterSettings.binary_path || probe.binary_path || '';

  const updateBinaryPath = async (value: string) => {
    if (name === 'claude_code') {
      await onPatch({ claude_code: { binary_path: value } });
    } else {
      await onPatch({ codex: { binary_path: value } });
    }
  };
  const updateModel = async (value: string) => {
    if (name === 'claude_code') {
      await onPatch({ claude_code: { default_model: value } });
    } else {
      await onPatch({ codex: { default_model: value } });
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
          <label className="text-xs font-medium text-muted-foreground">
            {t('settings.codeAgent.binaryPathOverride')}
          </label>
          <Input
            value={binaryPathValue}
            onChange={(e) => updateBinaryPath(e.target.value)}
            placeholder={t('settings.codeAgent.binaryPathOverridePlaceholder')}
            className={SETTINGS_MONO_INPUT_CLASS}
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground">
            {t('settings.codeAgent.defaultModel')}
          </label>
          <Input
            value={adapterSettings.default_model}
            onChange={(e) => updateModel(e.target.value)}
            placeholder={t('settings.codeAgent.defaultModelPlaceholder')}
            className={SETTINGS_INPUT_CLASS}
          />
        </div>
      </div>
    </div>
  );
}

export default CodeAgentSection;
