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
import { ModelDownloadProgress } from './ModelDownloadProgress';
import { TTSVoiceCustomization } from './TTSVoiceCustomization';
import { getRuntimeConfig, subscribeRuntimeReset } from '@/runtime/config';

const keyOf = (model: TTSModelChoice) => JSON.stringify([model.engine, model.provider_id, model.model_id]);
const withStatus = (config: TTSConfiguration | null, status: TTSModelStatus) => config ? {
  ...config, models: config.models.map((model) => model.engine === 'local' && model.model_id === status.model_id ? { ...model, status } : model),
} : null;

const directoryKey = (draft: Settings) => JSON.stringify([draft.local_model, draft.local_model_path, draft.local_codec_path]);
const isLocalModel = (value: string): value is Settings['local_model'] => ['voxcpm2-8bit', 'moss-tts-nano', 'qwen3-tts-customvoice-8bit', 'moss-tts-local-1.5-4bit', 'kokoro-multi-lang-v1_0', 'vits-melo-tts-zh_en'].includes(value);
function failureKey(failure: unknown): string {
  const message = failure && typeof failure === 'object' && 'message' in failure ? failure.message : '';
  return typeof message === 'string' && ['model_directory_invalid', 'model_missing', 'model_checksum_failed', 'reference_audio_invalid', 'reference_audio_full', 'reference_audio_busy', 'reference_audio_missing', 'config_conflict'].includes(message) ? `errors.${message}` : 'settingsFailed';
}

export function TTSSettings({ onConfigureProviders }: { onConfigureProviders: () => void }) {
  const { t } = useTranslation('app');
  const { controller, state } = useTTS('settings-tts');
  const [config, setConfig] = useState<TTSConfiguration | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [error, setError] = useState('');
  const [directory, setDirectory] = useState<{ key: string; status: TTSModelStatus } | null>(null);
  const [pending, setPending] = useState(false);
  const [editedText, setEditedText] = useState<string | null>(null);
  const text = editedText ?? t('tts.sample');
  const generation = useRef(0);
  const modelGeneration = useRef(0);
  useEffect(() => {
    let alive = true;
    const reset = subscribeRuntimeReset(() => { alive = false; generation.current += 1; setConfig(null); setDraft(null); });
    void ttsApi.settings().then(async (value) => { if (alive) {
      setConfig(value); setDraft(value.settings);
      if (value.settings.local_model_path) {
        const status = await ttsApi.inspectDirectory({ model_id: value.settings.local_model, path: value.settings.local_model_path, codec_path: value.settings.local_codec_path });
        if (alive) setDirectory({ key: directoryKey(value.settings), status });
      }
    } }).catch(() => { if (alive) setError('settingsFailed'); });
    return () => { alive = false; generation.current += 1; reset(); };
  }, []);
  const downloadingIds = config?.models.filter((model) => model.status?.state === 'downloading').map((model) => model.model_id).join('|') ?? '';
  useEffect(() => {
    if (!downloadingIds) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      const owner = modelGeneration.current;
      const results = await Promise.allSettled(downloadingIds.split('|').map((id) => ttsApi.model(id)));
      if (!alive) return;
      if (owner === modelGeneration.current) {
        for (const result of results) {
          if (result.status === 'fulfilled') setConfig((current) => withStatus(current, result.value));
          else setError('settingsFailed');
        }
      }
      timer = setTimeout(() => { void poll(); }, 750);
    };
    void poll();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [downloadingIds]);
  const save = async () => {
    if (!config || !draft) return;
    const owner = generation.current;
    setPending(true); setError(''); controller.stop();
    try {
      const value = await ttsApi.save(draft, config.revision);
      if (owner === generation.current) { setConfig(value); setDraft(value.settings); }
    } catch (failure) { if (owner === generation.current) setError(failureKey(failure)); }
    finally { if (owner === generation.current) setPending(false); }
  };
  const resourceAction = async (modelId: string, action: 'download' | 'cancelDownload' | 'deleteModel') => {
    modelGeneration.current += 1;
    const owner = generation.current;
    setPending(true); setError('');
    try {
      const status = await ttsApi[action](modelId);
      modelGeneration.current += 1;
      if (owner === generation.current) setConfig((current) => withStatus(current, status));
    } catch (failure) { if (owner === generation.current) setError(failureKey(failure)); }
    finally { if (owner === generation.current) setPending(false); }
  };
  const selected = config?.models.find((model) => model.engine === draft?.engine && (model.engine === 'local'
    ? model.model_id === draft.local_model
    : model.provider_id === draft.provider_id && (model.custom_model || model.model_id === draft.remote_model)));
  const choose = (key: string) => {
    const model = config?.models.find((item) => keyOf(item) === key);
    if (!draft || !model || pending) return;
    controller.stop();
    if (model.engine === 'local') {
      if (!isLocalModel(model.model_id)) return;
      const voice = model.voices.find((item) => item.id === 'zf_xiaobei') ?? model.voices[0];
      setDraft({ ...draft, engine: 'local', local_model: model.model_id, local_voice: voice?.id ?? '', local_speed: 1, local_model_path: '', local_codec_path: '', reference_audio: '', voice_description: '', voice_seed: 42, instructions: '', emotion: '' });
    } else {
      setDraft({ ...draft, engine: 'remote', provider_id: model.provider_id, remote_model: model.model_id,
        remote_voice: model.voices[0]?.id ?? '', remote_speed: 1, instructions: '', emotion: '' });
    }
  };
  const change = (value: Partial<Settings>) => { if (draft && !pending) { controller.stop(); setDraft({ ...draft, ...value }); } };
  const inspectDirectory = async () => {
    if (!draft) return;
    const owner = generation.current;
    const key = directoryKey(draft);
    setPending(true); setError('');
    try {
      const status = await ttsApi.inspectDirectory({ model_id: draft.local_model, path: draft.local_model_path, codec_path: draft.local_codec_path });
      if (owner === generation.current) setDirectory({ key, status });
    } catch (failure) { if (owner === generation.current) setError(failureKey(failure)); }
    finally { if (owner === generation.current) setPending(false); }
  };
  const uploadReference = async (file: File) => {
    if (!draft) return;
    if (file.size > 2 * 1024 * 1024) { setError('errors.reference_audio_invalid'); return; }
    const owner = generation.current;
    setPending(true); setError(''); controller.stop();
    try {
      const reference = await ttsApi.uploadReference(file);
      if (owner === generation.current) {
        setConfig((current) => current ? { ...current, reference_audio: [...current.reference_audio.filter((item) => item.id !== reference.id), reference] } : null);
        setDraft((current) => current ? { ...current, reference_audio: reference.id } : null);
      }
    } catch (failure) { if (owner === generation.current) setError(failureKey(failure)); }
    finally { if (owner === generation.current) setPending(false); }
  };
  const deleteReference = async (id: string) => {
    const owner = generation.current;
    setPending(true); setError(''); controller.stop();
    try {
      await ttsApi.deleteReference(id);
      if (owner === generation.current) {
        setConfig((current) => current ? { ...current, reference_audio: current.reference_audio.filter((item) => item.id !== id) } : null);
        setDraft((current) => current?.reference_audio === id ? { ...current, reference_audio: '' } : current);
      }
    } catch (failure) { if (owner === generation.current) setError(failureKey(failure)); }
    finally { if (owner === generation.current) setPending(false); }
  };
  const dirty = JSON.stringify(draft) !== JSON.stringify(config?.settings);
  const active = ['generating', 'playing', 'paused'].includes(state.phase);
  const local = draft?.engine === 'local';
  const external = local && !!draft?.local_model_path;
  const status = external ? directory?.key === directoryKey(draft) ? directory.status : undefined : selected?.status;
  const downloading = status?.state === 'downloading';
  const voice = (local ? draft?.local_voice : draft?.remote_voice) ?? '';
  const speed = (local ? draft?.local_speed : draft?.remote_speed) ?? 1;
  const customVoice = selected?.custom_voice && !selected.voices.some((item) => item.id === voice);
  const valid = selected && (voice.trim() || (local && selected.voices.length === 0))
    && (selected.reference_audio !== 'required' || draft?.reference_audio) && (local || draft?.remote_model.trim()) && Number.isFinite(speed)
    && (selected.speed_min === null || speed >= selected.speed_min) && (selected.speed_max === null || speed <= selected.speed_max);
  const previewUnavailable = !valid || (local && (!status?.runtime_available || status.state !== 'ready'));
  const localLabel = t(getRuntimeConfig().mode === 'remote' ? 'asr.serverModel' : 'tts.local');
  const labelOf = (model: TTSModelChoice) => `${model.name || t('tts.customModel')} · ${model.engine === 'local' ? localLabel : model.provider_name}`;
  const voiceLabel = (item: TTSModelChoice['voices'][number]) => {
    if (selected?.engine === 'remote' || draft?.local_model !== 'kokoro-multi-lang-v1_0') return t(`tts.voiceNames.${item.id}`, { defaultValue: item.name || item.id });
    return t('tts.voiceLabel', { name: t(`tts.voiceNames.${item.id}`, { defaultValue: item.name || item.id.slice(3) }),
      language: t(`asr.languages.${item.language}`), gender: t(item.id[1] === 'f' ? 'tts.female' : 'tts.male') });
  };
  return <SettingsSectionShell className="space-y-5">
    {error && <p role="alert" className="text-sm text-destructive">{t(`tts.${error}`)}</p>}
    {!config && !error && <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><LoadingSpinner />{t('settings.loadingConfig')}</div>}
    {config && draft && <fieldset disabled={pending} className="min-w-0 space-y-5">
      <LabeledSelectField label={t('tts.model')} value={selected ? keyOf(selected) : ''} disabled={pending} searchable
        options={config.models.map((model) => ({ value: keyOf(model), label: labelOf(model), group: model.engine === 'local' ? t(model.recommended ? 'tts.recommendedModels' : 'tts.moreModels') : model.provider_name }))} onChange={choose} />
      {!selected && <p role="alert" className="text-sm text-destructive">{t('tts.selectionUnavailable')}</p>}
      {selected?.custom_model && <label className="flex flex-col gap-2 text-sm font-semibold">{t('tts.modelId')}
        <Input value={draft.remote_model} maxLength={200} onChange={(event) => change({ remote_model: event.target.value, remote_voice: '', remote_speed: 1 })} />
      </label>}
      {selected?.engine === 'local' && <div className="rounded-lg border border-border/60 px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1">
            <p className="text-sm">{t('tts.modelSize', { size: Math.ceil(selected.download_bytes / 1_000_000) })}</p>
            <p className="text-xs text-muted-foreground">{t(`tts.modelHints.${draft.local_model}`)}</p>
          </div>
          <div className="flex items-center gap-2">
            {status && !downloading && (!status.download || status.state === 'ready') && <span role="status" className="text-xs text-muted-foreground">{t(external && status.state === 'ready' ? 'tts.directoryValid' : `tts.modelState.${status.state}`)}</span>}
            {!external && status && (status.state !== 'ready'
              ? <Button size="sm" variant={downloading ? 'ghost' : 'outline'} onClick={() => { void resourceAction(selected.model_id, downloading ? 'cancelDownload' : 'download'); }}>
                {!downloading && <Download className="mr-2 h-4 w-4" />}{t(downloading ? 'tts.cancelDownload' : status.state === 'failed' || status.state === 'cancelled' ? 'modelDownload.resume' : 'tts.download')}
              </Button>
              : <Button size="icon" variant="ghost" disabled={active} aria-label={t('tts.deleteModel')} title={t('tts.deleteModel')}
                onClick={() => { void resourceAction(selected.model_id, 'deleteModel'); }}><Trash2 className="h-4 w-4" /></Button>)}
          </div>
        </div>
        <ModelDownloadProgress progress={status?.download ?? null} active={!!downloading} />
        {!selected.status?.runtime_available && <p role="status" className="mt-2 text-sm text-destructive">{t(selected.runtime === 'mlx' ? 'tts.mlxRuntimeHint' : 'tts.errors.runtime_missing')}</p>}
        {status?.error && !status.download && <p role="alert" className="mt-2 text-sm text-destructive">{t('asr.errors.model_download_failed')}</p>}
      </div>}
      {local && selected && <details className="space-y-3 rounded-lg border border-border/60 px-4 py-3" open={external || undefined}>
        <summary className="cursor-pointer text-sm font-semibold">{t('tts.useDirectory')}</summary>
        <p className="text-xs leading-5 text-muted-foreground">{t('tts.directoryHint')}</p>
        <label className="flex flex-col gap-2 text-sm">{t('tts.modelDirectory')}
          <Input value={draft.local_model_path} maxLength={4096} placeholder="/path/to/model"
            onChange={(event) => change({ local_model_path: event.target.value })} />
        </label>
        {selected.companion_model && <label className="flex flex-col gap-2 text-sm">{t('tts.codecDirectory')}
          <Input value={draft.local_codec_path} maxLength={4096} placeholder="/path/to/audio-tokenizer"
            onChange={(event) => change({ local_codec_path: event.target.value })} />
        </label>}
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="outline" size="sm" disabled={!external} onClick={() => { void inspectDirectory(); }}>{t('tts.validateDirectory')}</Button>
          {external && <Button variant="ghost" size="sm" onClick={() => change({ local_model_path: '', local_codec_path: '' })}>{t('tts.useManagedModel')}</Button>}
          {external && status?.state === 'ready' && <span role="status" className="text-xs text-muted-foreground">{t('tts.directoryValid')}</span>}
        </div>
      </details>}
      {selected && <div className="grid gap-4 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <div className="space-y-3">
          {selected.voices.length === 1 && !selected.custom_voice ? <div className="space-y-2.5">
            <p className="text-sm font-semibold leading-6">{t('tts.voice')}</p><p className="text-sm leading-11">{t('tts.meloVoice')}</p>
          </div> : selected.voices.length > 0 ? <LabeledSelectField label={t('tts.voice')} value={customVoice ? '__custom' : voice} searchable disabled={pending}
            options={[...selected.voices.map((item) => ({ value: item.id, label: voiceLabel(item) })),
              ...(selected.custom_voice ? [{ value: '__custom', label: t('tts.customVoice') }] : [])]}
            onChange={(value) => change(local ? { local_voice: value } : { remote_voice: value === '__custom' ? '' : value })} /> : null}
          {(customVoice || (!local && selected.voices.length === 0)) && <label className="flex flex-col gap-2 text-sm font-semibold">{t('tts.voiceId')}
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
      {local && selected && <TTSVoiceCustomization model={selected} draft={draft} references={config.reference_audio}
        change={change} pending={pending} upload={(file) => { void uploadReference(file); }} removeReference={(id) => { void deleteReference(id); }} />}
      {selected && (selected.instructions || selected.emotions.length > 0) && <details className="space-y-3 text-sm">
        <summary className="cursor-pointer font-semibold">{t('tts.expression')}</summary>
        {selected.instructions && <label className="flex flex-col gap-2">{t('tts.instructions')}
          <Textarea rows={2} maxLength={2000} value={draft.instructions} onChange={(event) => change({ instructions: event.target.value })} />
        </label>}
        {selected.emotions.length > 0 && <LabeledSelectField label={t('tts.emotion')} value={draft.emotion}
          options={['', ...selected.emotions].map((emotion) => ({ value: emotion, label: t(`tts.emotions.${emotion || 'auto'}`) }))}
          onChange={(emotion) => change({ emotion })} />}
      </details>}
      <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>{t('tts.connectServiceHint')}</span><Button variant="ghost" size="sm" onClick={onConfigureProviders}>{t('tts.connectService')}</Button>
      </div>
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
