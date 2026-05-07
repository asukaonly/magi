import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, RefreshCw, X } from 'lucide-react';

import {
  codeAgentApi,
  type CodeAgentSettings,
  type CodeAgentSettingsPatch,
  type ProbeResult,
} from '@/api/modules/codeAgent';
import {
  SettingsGroup,
  SettingsSectionShell,
  SettingsSwitchRow,
} from '@/components/settings/SettingsSectionPrimitives';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useConversationStore } from '@/stores/conversation-store';

type AdapterName = 'claude_code' | 'codex';

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
    <SettingsSectionShell>
      {error && (
        <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}

      <SettingsGroup
        title={t('settings.codeAgent.titleEnable')}
        description={t('settings.codeAgent.subtitle')}
      >
        <SettingsSwitchRow
          title={t('settings.codeAgent.enableTitle')}
          description={t('settings.codeAgent.enableDesc')}
          ariaLabel={t('settings.codeAgent.enableTitle')}
          checked={settings.enabled}
          onCheckedChange={(checked) => persistUserPatch({ enabled: checked })}
        />
      </SettingsGroup>

      <SettingsGroup
        title={t('settings.codeAgent.defaultAdapter')}
        description={t('settings.codeAgent.defaultAdapterDesc')}
      >
        <div className="flex gap-2">
          {(['claude_code', 'codex'] as AdapterName[]).map((name) => (
            <Button
              key={name}
              type="button"
              variant={settings.default_adapter === name ? 'default' : 'outline'}
              size="sm"
              onClick={() => persistUserPatch({ default_adapter: name })}
            >
              {ADAPTER_LABELS[name]}
            </Button>
          ))}
        </div>
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
            className="inline-flex items-center gap-1"
          >
            {rescanning ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            {t('settings.codeAgent.rescan')}
          </Button>
        </div>
        <div className="space-y-3">
          {(['claude_code', 'codex'] as AdapterName[]).map((name) => (
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
                className="flex items-center justify-between gap-2 rounded-md bg-muted/40 px-3 py-1.5 text-xs"
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
              className="h-8 text-xs"
            />
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!forbidPathDraft.trim()}
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
              className="h-8 w-32 text-xs"
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
    <div className="rounded-md border border-[hsl(var(--border)/0.6)] bg-card/40 p-3 space-y-2">
      <div className="flex items-center gap-2">
        <Badge variant={installed ? 'default' : 'outline'}>
          {installed ? t('settings.codeAgent.installed') : t('settings.codeAgent.notInstalled')}
        </Badge>
        <span className="font-medium text-sm">{ADAPTER_LABELS[name]}</span>
        {probe.version && (
          <span className="text-xs text-muted-foreground">{probe.version}</span>
        )}
      </div>
      {probe.binary_path && (
        <div className="text-xs text-muted-foreground font-mono">
          {probe.binary_path}
        </div>
      )}
      {probe.error && (
        <div className="text-xs text-destructive">{probe.error}</div>
      )}

      <div className="grid gap-2 pt-1">
        <div>
          <label className="text-xs font-medium text-muted-foreground">
            {t('settings.codeAgent.binaryPathOverride')}
          </label>
          <Input
            value={adapterSettings.binary_path}
            onChange={(e) => updateBinaryPath(e.target.value)}
            placeholder={t('settings.codeAgent.binaryPathOverridePlaceholder')}
            className="h-8 text-xs font-mono"
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
            className="h-8 text-xs"
          />
        </div>
      </div>
    </div>
  );
}

export default CodeAgentSection;
