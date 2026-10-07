import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ttsApi, type TTSConfiguration, type TTSSettings as Settings } from '@/api/modules/tts';
import type { SystemConfig } from '@/api/modules/config';
import { useTTS } from '@/hooks/useTTS';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Download, Play, Save, Trash2 } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { LabeledSelectField, NumberField } from './form-fields';
import { TTSPlaybackControls } from '@/components/chat/TTSPlaybackControls';
import { SettingsSectionShell } from './SettingsSectionPrimitives';
import { getRuntimeConfig, subscribeRuntimeReset } from '@/runtime/config';

export function TTSSettings({ providers, onConfigureProviders }: {
  providers: SystemConfig['llm']['providers'];
  onConfigureProviders: () => void;
}) {
  const { t } = useTranslation('app');
  const { controller, state } = useTTS('settings-tts');
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
    if (!config || !draft) return false;
    const owner = generation.current;
    setPending(true); setError(false); controller.stop();
    try {
      const value = await ttsApi.save(draft, config.revision);
      if (owner !== generation.current) return false;
      setConfig(value); setDraft(value.settings);
      return true;
    }
    catch { if (owner === generation.current) setError(true); return false; }
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
  const isRemoteConnection = getRuntimeConfig().mode === 'remote';
  const localUnavailable = draft?.engine === 'local' && (!config?.model.runtime_available || config.model.state !== 'ready');
  const providersWithSpeech = Object.entries(providers).filter(([, value]) => value.enabled && value.services.tts.enabled);
  const provider = providers[draft?.provider_id ?? ''];
  const remoteUnavailable = draft?.engine === 'remote' && (!provider?.enabled || !provider.services.tts.enabled);
  const preview = async () => {
    if (draft) await controller.speak({ kind: 'text', text }, null, 'manual', draft);
  };
  return <SettingsSectionShell className="space-y-5">
    {error && <p role="alert" className="text-sm text-destructive">{t('tts.settingsFailed')}</p>}
    {!config && !error && <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
      <LoadingSpinner />{t('settings.loadingConfig')}
    </div>}
    {config && draft && <fieldset disabled={pending} className="min-w-0 space-y-5">
      <LabeledSelectField label={t('tts.engine')} value={draft.engine} disabled={pending}
        options={[{ value: 'local', label: t(isRemoteConnection ? 'asr.serverModel' : 'tts.local') }, { value: 'remote', label: t('tts.remote') }]}
        onChange={(engine) => { if (engine === 'local' || engine === 'remote') setDraft({ ...draft, engine }); }} />
      {draft.engine === 'local' ? <div className="space-y-4">
        <div className="rounded-lg border border-border/60 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="space-y-1">
              <p className="text-sm font-semibold">Kokoro</p>
              <p className="text-xs leading-5 text-muted-foreground">{t('tts.modelSummary')}</p>
            </div>
            <div className="flex items-center gap-2">
              <span role="status" className="text-xs text-muted-foreground">
                {t(`tts.modelState.${config.model.state}`)}{downloading ? ` ${Math.round(config.model.progress * 100)}%` : ''}
              </span>
              {config.model.state !== 'ready'
                ? <Button size="sm" variant={downloading ? 'ghost' : 'outline'} disabled={pending} onClick={() => { void download(downloading); }}>
                  {!downloading && <Download className="mr-2 h-4 w-4" />}
                  {downloading ? t('tts.cancelDownload') : t('tts.download')}
                </Button>
                : <Button size="icon" variant="ghost" disabled={pending} aria-label={t('tts.deleteModel')} title={t('tts.deleteModel')}
                  onClick={() => { void remove(); }}><Trash2 className="h-4 w-4" /></Button>}
            </div>
          </div>
          {!config.model.runtime_available && <p role="status" className="mt-2 text-sm text-destructive">{t('tts.errors.runtime_missing')}</p>}
          {config.model.error && <p role="alert" className="mt-2 text-sm text-destructive">{t('asr.errors.model_download_failed')}</p>}
        </div>
        <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <LabeledSelectField label={t('tts.voice')} value={draft.local_voice} searchable disabled={pending}
            options={config.local_voices.map((voice) => {
              const name = voice.id.slice(3);
              return { value: voice.id, label: t('tts.voiceLabel', {
                name: t(`tts.voiceNames.${voice.id}`, { defaultValue: name.charAt(0).toUpperCase() + name.slice(1) }),
                language: t(`asr.languages.${voice.language}`),
                gender: t(voice.id[1] === 'f' ? 'tts.female' : 'tts.male'),
              }) };
            })}
            onChange={(local_voice) => setDraft({ ...draft, local_voice })} />
          <NumberField label={t('tts.speed')} min={0.5} max={2} step={0.1} value={draft.local_speed}
            onChange={(local_speed) => setDraft({ ...draft, local_speed })} />
        </div>
      </div> : <div className="space-y-3">
        <LabeledSelectField label={t('tts.provider')} value={draft.provider_id ?? ''} disabled={pending}
          options={[{ value: '', label: t('tts.chooseProvider') }, ...providersWithSpeech.map(([id, value]) => ({ value: id, label: value.display_name }))]}
          onChange={(provider_id) => setDraft({ ...draft, provider_id: provider_id || null })} />
        {provider && <p className="text-sm text-muted-foreground">{provider.services.tts.model} · {provider.services.tts.voice}</p>}
        {providersWithSpeech.length === 0 && <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          <span>{t('tts.noProviders')}</span>
          <Button variant="outline" size="sm" onClick={onConfigureProviders}>{t('asr.addProvider')}</Button>
        </div>}
      </div>}
      <div className="space-y-3 border-t border-border/60 pt-5">
        <label className="flex flex-col gap-2 text-sm font-semibold">
          {t('tts.previewText')}
          <Textarea rows={2} maxLength={4096} className="resize-y rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.78)] p-3 font-normal leading-6"
            value={text} onChange={(event) => setText(event.target.value)} />
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" disabled={!text.trim() || pending || active || localUnavailable || remoteUnavailable}
            onClick={() => { void preview(); }}><Play className="mr-2 h-4 w-4" />{t('tts.preview')}</Button>
          <Button disabled={!dirty || pending} onClick={() => { void save(); }}><Save className="mr-2 h-4 w-4" />{t('tts.save')}</Button>
        </div>
      </div>
    </fieldset>}
    <TTSPlaybackControls controller={controller} state={state} />
  </SettingsSectionShell>;
}
