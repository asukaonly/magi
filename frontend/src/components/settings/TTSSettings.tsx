import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ttsApi, type TTSConfiguration, type TTSModelChoice, type TTSModelStatus, type TTSSettings as Settings } from '@/api/modules/tts';
import { useTTS } from '@/hooks/useTTS';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Download, Play, Save, Trash2 } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { LabeledSelectField, NumberField } from './form-fields';
import { TTSPlaybackControls } from '@/components/chat/TTSPlaybackControls';
import { SettingsSectionShell } from './SettingsSectionPrimitives';
import { getRuntimeConfig, subscribeRuntimeReset } from '@/runtime/config';

const keyOf = (model: TTSModelChoice) => JSON.stringify([model.engine, model.provider_id, model.model_id]);
const withStatus = (config: TTSConfiguration | null, status: TTSModelStatus) => config ? {
  ...config, models: config.models.map((model) => model.engine === 'local' && model.model_id === status.model_id ? { ...model, status } : model),
} : null;

export function TTSSettings({ onConfigureProviders }: { onConfigureProviders: () => void }) {
  const { t } = useTranslation('app');
  const { controller, state } = useTTS('settings-tts');
  const [config, setConfig] = useState<TTSConfiguration | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [error, setError] = useState(false);
  const [pending, setPending] = useState(false);
  const [editedText, setEditedText] = useState<string | null>(null);
  const text = editedText ?? t('tts.sample');
  const generation = useRef(0);
  useEffect(() => {
    let alive = true;
    const reset = subscribeRuntimeReset(() => { alive = false; generation.current += 1; setConfig(null); setDraft(null); });
    void ttsApi.settings().then((value) => { if (alive) { setConfig(value); setDraft(value.settings); } }).catch(() => { if (alive) setError(true); });
    return () => { alive = false; generation.current += 1; reset(); };
  }, []);
  const downloadingIds = config?.models.filter((model) => model.status?.state === 'downloading').map((model) => model.model_id).join('|') ?? '';
  useEffect(() => {
    if (!downloadingIds) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const results = await Promise.allSettled(downloadingIds.split('|').map((id) => ttsApi.model(id)));
      if (!alive) return;
      for (const result of results) {
        if (result.status === 'fulfilled') setConfig((current) => withStatus(current, result.value));
        else setError(true);
      }
      timer = setTimeout(() => { void poll(); }, 1000);
    };
    timer = setTimeout(() => { void poll(); }, 1000);
    return () => { alive = false; clearTimeout(timer); };
  }, [downloadingIds]);
  const save = async () => {
    if (!config || !draft) return;
    const owner = generation.current;
    setPending(true); setError(false); controller.stop();
    try {
      const value = await ttsApi.save(draft, config.revision);
      if (owner === generation.current) { setConfig(value); setDraft(value.settings); }
    } catch { if (owner === generation.current) setError(true); }
    finally { if (owner === generation.current) setPending(false); }
  };
  const resourceAction = async (modelId: string, action: 'download' | 'cancelDownload' | 'deleteModel') => {
    const owner = generation.current;
    setPending(true); setError(false);
    try {
      const status = await ttsApi[action](modelId);
      if (owner === generation.current) setConfig((current) => withStatus(current, status));
    } catch { if (owner === generation.current) setError(true); }
    finally { if (owner === generation.current) setPending(false); }
  };
  const selected = config?.models.find((model) => model.engine === draft?.engine && (model.engine === 'local'
    ? model.model_id === draft.local_model
    : model.provider_id === draft.provider_id && (model.custom_model || model.model_id === draft.remote_model)));
  const choose = (key: string) => {
    const model = config?.models.find((item) => keyOf(item) === key);
    if (!draft || !model) return;
    controller.stop();
    if (model.engine === 'local') {
      if (model.model_id !== 'kokoro-multi-lang-v1_0' && model.model_id !== 'vits-melo-tts-zh_en') return;
      const voice = model.voices.find((item) => item.id === 'zf_xiaobei') ?? model.voices[0];
      setDraft({ ...draft, engine: 'local', local_model: model.model_id, local_voice: voice?.id ?? '', local_speed: 1, instructions: '', emotion: '' });
    } else {
      setDraft({ ...draft, engine: 'remote', provider_id: model.provider_id, remote_model: model.model_id,
        remote_voice: model.voices[0]?.id ?? '', remote_speed: 1, instructions: '', emotion: '' });
    }
  };
  const change = (value: Partial<Settings>) => { if (draft) { controller.stop(); setDraft({ ...draft, ...value }); } };
  const dirty = JSON.stringify(draft) !== JSON.stringify(config?.settings);
  const active = ['generating', 'playing', 'paused'].includes(state.phase);
  const local = draft?.engine === 'local';
  const status = selected?.status;
  const downloading = status?.state === 'downloading';
  const voice = (local ? draft?.local_voice : draft?.remote_voice) ?? '';
  const speed = (local ? draft?.local_speed : draft?.remote_speed) ?? 1;
  const customVoice = selected?.custom_voice && !selected.voices.some((item) => item.id === voice);
  const valid = selected && voice.trim() && (local || draft?.remote_model.trim()) && Number.isFinite(speed)
    && (selected.speed_min === null || speed >= selected.speed_min) && (selected.speed_max === null || speed <= selected.speed_max);
  const previewUnavailable = !valid || (local && (!status?.runtime_available || status.state !== 'ready'));
  const localLabel = t(getRuntimeConfig().mode === 'remote' ? 'asr.serverModel' : 'tts.local');
  const labelOf = (model: TTSModelChoice) => `${model.name || t('tts.customModel')} · ${model.engine === 'local' ? localLabel : model.provider_name}`;
  const voiceLabel = (item: TTSModelChoice['voices'][number]) => {
    if (selected?.engine === 'remote') return t(`tts.voiceNames.${item.id}`, { defaultValue: item.name || item.id });
    return t('tts.voiceLabel', { name: t(`tts.voiceNames.${item.id}`, { defaultValue: item.name || item.id.slice(3) }),
      language: t(`asr.languages.${item.language}`), gender: t(item.id[1] === 'f' ? 'tts.female' : 'tts.male') });
  };
  return <SettingsSectionShell className="space-y-5">
    {error && <p role="alert" className="text-sm text-destructive">{t('tts.settingsFailed')}</p>}
    {!config && !error && <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><LoadingSpinner />{t('settings.loadingConfig')}</div>}
    {config && draft && <fieldset disabled={pending} className="min-w-0 space-y-5">
      <LabeledSelectField label={t('tts.model')} value={selected ? keyOf(selected) : ''} disabled={pending} searchable
        options={config.models.map((model) => ({ value: keyOf(model), label: labelOf(model), group: model.engine === 'local' ? localLabel : model.provider_name }))} onChange={choose} />
      {!selected && <p role="alert" className="text-sm text-destructive">{t('tts.selectionUnavailable')}</p>}
      {selected?.custom_model && <label className="flex flex-col gap-2 text-sm font-semibold">{t('tts.modelId')}
        <Input value={draft.remote_model} maxLength={200} onChange={(event) => change({ remote_model: event.target.value, remote_voice: '', remote_speed: 1 })} />
      </label>}
      {status && selected && <div className="rounded-lg border border-border/60 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1">
            <p className="text-sm">{t('tts.localSummary', { size: Math.ceil(selected.download_bytes / 1_000_000) })}</p>
            <p className="text-xs text-muted-foreground">{t(draft.local_model === 'vits-melo-tts-zh_en' ? 'tts.meloHint' : 'tts.kokoroHint')}</p>
          </div>
          <div className="flex items-center gap-2">
            <span role="status" className="text-xs text-muted-foreground">{t(`tts.modelState.${status.state}`)}{downloading ? ` ${Math.round(status.progress * 100)}%` : ''}</span>
            {status.state !== 'ready'
              ? <Button size="sm" variant={downloading ? 'ghost' : 'outline'} onClick={() => { void resourceAction(selected.model_id, downloading ? 'cancelDownload' : 'download'); }}>
                {!downloading && <Download className="mr-2 h-4 w-4" />}{t(downloading ? 'tts.cancelDownload' : status.state === 'failed' ? 'tts.retryDownload' : 'tts.download')}
              </Button>
              : <Button size="icon" variant="ghost" disabled={active} aria-label={t('tts.deleteModel')} title={t('tts.deleteModel')}
                onClick={() => { void resourceAction(selected.model_id, 'deleteModel'); }}><Trash2 className="h-4 w-4" /></Button>}
          </div>
        </div>
        {!status.runtime_available && <p role="status" className="mt-2 text-sm text-destructive">{t('tts.errors.runtime_missing')}</p>}
        {status.error && <p role="alert" className="mt-2 text-sm text-destructive">{t('asr.errors.model_download_failed')}</p>}
      </div>}
      {selected && <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          {selected.voices.length === 1 && !selected.custom_voice ? <div className="space-y-2.5">
            <p className="text-sm font-semibold leading-6">{t('tts.voice')}</p><p className="text-sm leading-11">{t('tts.meloVoice')}</p>
          </div> : selected.voices.length > 0 ? <LabeledSelectField label={t('tts.voice')} value={customVoice ? '__custom' : voice} searchable disabled={pending}
            options={[...selected.voices.map((item) => ({ value: item.id, label: voiceLabel(item) })),
              ...(selected.custom_voice ? [{ value: '__custom', label: t('tts.customVoice') }] : [])]}
            onChange={(value) => change(local ? { local_voice: value } : { remote_voice: value === '__custom' ? '' : value })} /> : null}
          {(customVoice || selected.voices.length === 0) && <label className="flex flex-col gap-2 text-sm font-semibold">{t('tts.voiceId')}
            <Input value={voice} maxLength={200} onChange={(event) => change({ remote_voice: event.target.value })} />
            <span className="text-xs font-normal leading-5 text-muted-foreground">{t('tts.voiceIdHint')}</span>
          </label>}
        </div>
        {selected.speed_min !== null && selected.speed_max !== null && <div className="space-y-2">
          <NumberField label={t('tts.speed')} min={selected.speed_min} max={selected.speed_max} step={0.1} value={speed}
            onChange={(value) => change(local ? { local_speed: value } : { remote_speed: value })} />
          <p className="text-xs text-muted-foreground">{speed === 1 ? t('tts.normalSpeed') : t('tts.speedValue', { speed })}</p>
        </div>}
      </div>}
      {selected && (selected.instructions || selected.emotions.length > 0) && <details className="space-y-3 text-sm">
        <summary className="cursor-pointer font-semibold">{t('tts.expression')}</summary>
        {selected.instructions && <label className="flex flex-col gap-2">{t('tts.instructions')}
          <Textarea rows={2} maxLength={2000} value={draft.instructions} onChange={(event) => change({ instructions: event.target.value })} />
        </label>}
        {selected.emotions.length > 0 && <LabeledSelectField label={t('tts.emotion')} value={draft.emotion}
          options={['', ...selected.emotions].map((emotion) => ({ value: emotion, label: t(`tts.emotions.${emotion || 'auto'}`) }))}
          onChange={(emotion) => change({ emotion })} />}
      </details>}
      {!config.models.some((model) => model.engine === 'remote') && <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>{t('tts.noProviders')}</span><Button variant="ghost" size="sm" onClick={onConfigureProviders}>{t('asr.addProvider')}</Button>
      </div>}
      <div className="space-y-3 border-t border-border/60 pt-5">
        <label className="flex flex-col gap-2 text-sm font-semibold">{t('tts.previewText')}
          <Textarea rows={2} maxLength={4096} className="resize-y rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.78)] p-3 font-normal leading-6"
            value={text} onChange={(event) => setEditedText(event.target.value)} />
        </label>
        <p className="text-xs text-muted-foreground">{t(local ? 'tts.previewDraft' : 'tts.previewRemote', { provider: selected?.provider_name })}</p>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button variant="outline" disabled={!text.trim() || pending || active || previewUnavailable}
            onClick={() => { void controller.speak({ kind: 'text', text }, null, 'manual', draft); }}><Play className="mr-2 h-4 w-4" />{t('tts.preview')}</Button>
          <Button disabled={!dirty || pending || !valid} onClick={() => { void save(); }}><Save className="mr-2 h-4 w-4" />{t('tts.save')}</Button>
        </div>
        <TTSPlaybackControls controller={controller} state={state} />
      </div>
    </fieldset>}
  </SettingsSectionShell>;
}
