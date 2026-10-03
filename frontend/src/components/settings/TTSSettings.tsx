import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ttsApi, type TTSConfiguration, type TTSSettings as Settings } from '@/api/modules/tts';
import type { SystemConfig } from '@/api/modules/config';
import { useTTS } from '@/hooks/useTTS';
import { setAutomaticSpeech, useAutomaticSpeech } from '@/hooks/useAutomaticSpeech';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { CircleAlert, Download, Loader2, Play, Save } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { LabeledSelectField, NumberField } from './form-fields';
import { TTSPlaybackControls } from '@/components/chat/TTSPlaybackControls';
import { SettingsGroup, SettingsSectionShell, SettingsSwitchRow } from './SettingsSectionPrimitives';
import { subscribeRuntimeReset } from '@/runtime/config';

export function TTSSettings({ providers, onConfigureProviders }: {
  providers: SystemConfig['llm']['providers'];
  onConfigureProviders: () => void;
}) {
  const { t } = useTranslation('app');
  const { controller, state } = useTTS('settings-tts');
  const automatic = useAutomaticSpeech();
  const [preferenceError, setPreferenceError] = useState(false);
  const [config, setConfig] = useState<TTSConfiguration | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [error, setError] = useState(false);
  const [pending, setPending] = useState(false);
  const [text, setText] = useState(() => t('tts.sample'));
  const generation = useRef(0);
  useEffect(() => {
    let alive = true;
    const reset = subscribeRuntimeReset(() => { alive = false; generation.current += 1; setConfig(null); setDraft(null); });
    void ttsApi.settings().then((value) => { if (alive) { setConfig(value); setDraft(value.settings); } }).catch(() => { if (alive) setError(true); });
    return () => { alive = false; generation.current += 1; reset(); };
  }, []);
  const downloading = config?.model.state === 'downloading';
  useEffect(() => {
    if (!downloading) return;
    let alive = true;
    const timer = setInterval(() => {
      void ttsApi.model().then((model) => { if (alive) setConfig((current) => current ? { ...current, model } : null); }).catch(() => { if (alive) setError(true); });
    }, 1000);
    return () => { alive = false; clearInterval(timer); };
  }, [downloading]);
  const save = async () => {
    if (!config || !draft) return;
    const owner = generation.current;
    setPending(true); setError(false); controller.stop();
    try { const value = await ttsApi.save(draft, config.revision); if (owner === generation.current) { setConfig(value); setDraft(value.settings); } }
    catch { if (owner === generation.current) setError(true); }
    finally { if (owner === generation.current) setPending(false); }
  };
  const download = async (cancel: boolean) => {
    const owner = generation.current;
    setPending(true); setError(false);
    try {
      const model = cancel ? await ttsApi.cancelDownload() : await ttsApi.download();
      if (owner === generation.current) setConfig((current) => current ? { ...current, model } : null);
    } catch { if (owner === generation.current) setError(true); } finally { if (owner === generation.current) setPending(false); }
  };
  const remove = async () => {
    const owner = generation.current;
    setPending(true); setError(false);
    try {
      const model = await ttsApi.deleteModel();
      if (owner === generation.current) setConfig((current) => current ? { ...current, model } : null);
    } catch { if (owner === generation.current) setError(true); } finally { if (owner === generation.current) setPending(false); }
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(config?.settings);
  const active = ['generating', 'playing', 'paused'].includes(state.phase);
  const localUnavailable = draft?.engine === 'local' && (!config?.model.runtime_available || config.model.state !== 'ready');
  return <SettingsSectionShell>
    <SettingsGroup title={t('tts.behaviorTitle')}>
      <SettingsSwitchRow title={t('tts.automatic')} description={t('tts.automaticDescription')}
        ariaLabel={t('tts.automatic')} checked={automatic} onCheckedChange={(enabled) => {
          try { setAutomaticSpeech(enabled); setPreferenceError(false); }
          catch { setPreferenceError(true); }
        }} />
      {preferenceError && <p role="alert" className="text-sm text-destructive">{t('tts.preferenceSaveFailed')}</p>}
    </SettingsGroup>
    <SettingsGroup title={t('tts.setupTitle')} description={t('tts.description')}>
      {error && <p role="alert" className="text-sm text-destructive">{t('tts.settingsFailed')}</p>}
      {!config && !error && <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <LoadingSpinner />{t('settings.loadingConfig')}
      </div>}
      {config && draft && <LabeledSelectField label={t('tts.engine')} value={draft.engine} disabled={pending}
        options={[{ value: 'local', label: t('tts.local') }, { value: 'remote', label: t('tts.remote') }]}
        onChange={(engine) => { if (engine === 'local' || engine === 'remote') setDraft({ ...draft, engine }); }} />}
    </SettingsGroup>
    {config && draft && <>
      {draft.engine === 'local' ? <SettingsGroup title={t('tts.localModel')}>
        <div className="space-y-4 rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.48)] p-5 shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.2)]">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-1">
              <p className="text-sm font-semibold">Kokoro v1.0</p>
              <p className="text-xs leading-5 text-muted-foreground">{t('tts.modelSummary')}</p>
            </div>
            <span role="status" className="rounded-md bg-muted px-2.5 py-1 text-xs text-muted-foreground">
              {t(`tts.modelState.${config.model.state}`)}{downloading ? ` ${Math.round(config.model.progress * 100)}%` : ''}
            </span>
          </div>
          {!config.model.runtime_available && <p role="status" className="flex items-start gap-2 text-sm leading-6 text-foreground/85"><CircleAlert className="mt-1 h-4 w-4 shrink-0" />{t('tts.errors.runtime_missing')}</p>}
          <div className="flex flex-wrap gap-2">
            {config.model.state !== 'ready' && <Button variant="outline" disabled={pending} onClick={() => { void download(downloading); }}>
              {downloading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
              {downloading ? t('tts.cancelDownload') : t('tts.download')}
            </Button>}
            {config.model.state === 'ready' && <Button variant="outline" disabled={pending} onClick={() => { void remove(); }}>{t('tts.deleteModel')}</Button>}
          </div>
          <details className="text-xs leading-6 text-muted-foreground">
            <summary className="cursor-pointer rounded-sm focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring">{t('tts.modelDetails')}</summary>
            <p className="mt-2">{t('tts.modelNotice')}</p>
            {!config.model.runtime_available && <p className="mt-2">{t('tts.runtimeHelp')}</p>}
          </details>
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          <LabeledSelectField label={t('tts.voice')} value={draft.local_voice} searchable disabled={pending}
            options={config.local_voices.map((voice) => ({ value: voice.id, label: `${voice.id} · ${t(`asr.languages.${voice.language}`)}` }))}
            onChange={(local_voice) => setDraft({ ...draft, local_voice })} />
          <NumberField label={t('tts.speed')} min={0.5} max={2} step={0.1} value={draft.local_speed}
            onChange={(local_speed) => setDraft({ ...draft, local_speed })} />
        </div>
      </SettingsGroup> : <SettingsGroup title={t('tts.provider')} description={t('tts.remoteHint')}>
        <LabeledSelectField label={t('tts.provider')} value={draft.provider_id ?? ''} disabled={pending}
          options={[{ value: '', label: t('tts.chooseProvider') }, ...Object.entries(providers)
            .filter(([, value]) => value.enabled && value.services.tts.enabled)
            .map(([id, value]) => ({ value: id, label: value.display_name }))]}
          onChange={(provider_id) => setDraft({ ...draft, provider_id: provider_id || null })} />
        <Button variant="outline" onClick={onConfigureProviders}>{t('tts.configureProvider')}</Button>
        {config.model.state === 'ready' && config.settings.engine === 'remote' && <Button variant="ghost" disabled={pending} onClick={() => { void remove(); }}>{t('tts.deleteModel')}</Button>}
      </SettingsGroup>}
      <div className="flex flex-wrap items-center gap-3">
        <Button disabled={!dirty || pending} onClick={() => { void save(); }}><Save className="mr-2 h-4 w-4" />{t('tts.save')}</Button>
        <p role="status" className="text-xs text-muted-foreground">{dirty ? t('tts.saveBeforePreview') : t('tts.saved')}</p>
      </div>
      <SettingsGroup title={t('tts.previewTitle')} description={t('tts.previewHint')}>
        <label className="flex flex-col gap-2.5 text-sm font-semibold">
          {t('tts.previewText')}
          <Textarea rows={3} maxLength={4096} className="resize-y rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.78)] p-4 font-normal leading-6"
            value={text} onChange={(event) => setText(event.target.value)} />
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" disabled={dirty || !text.trim() || pending || active || localUnavailable}
            onClick={() => { void controller.speak({ kind: 'text', text }); }}><Play className="mr-2 h-4 w-4" />{t('tts.preview')}</Button>
          <p className="text-xs text-muted-foreground">{t('tts.syntheticNotice')}</p>
        </div>
        <TTSPlaybackControls controller={controller} state={state} />
      </SettingsGroup>
    </>}
  </SettingsSectionShell>;
}
