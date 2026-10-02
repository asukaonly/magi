import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ttsApi, type TTSConfiguration, type TTSSettings as Settings } from '@/api/modules/tts';
import type { SystemConfig } from '@/api/modules/config';
import { useTTS } from '@/hooks/useTTS';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { TTSPlaybackControls } from '@/components/chat/TTSPlaybackControls';
import { SettingsGroup } from './SettingsSectionPrimitives';
import { subscribeRuntimeReset } from '@/runtime/config';

export function TTSSettings({ providers }: { providers: SystemConfig['llm']['providers'] }) {
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
  return <SettingsGroup title={t('tts.title')} description={t('tts.description')}>
    <div className="space-y-4">
      {error && <p role="alert" className="text-sm text-destructive">{t('tts.settingsFailed')}</p>}
      {config && draft && <>
        <label className="block text-sm">{t('tts.engine')}
          <select className="mt-1 w-full rounded border bg-background p-2" value={draft.engine}
            onChange={(event) => setDraft({ ...draft, engine: event.target.value === 'remote' ? 'remote' : 'local' })}>
            <option value="local">{t('tts.local')}</option><option value="remote">{t('tts.remote')}</option>
          </select>
        </label>
        {draft.engine === 'local' ? <>
          <p className="text-sm">Kokoro v1.0 · {t(`tts.modelState.${config.model.state}`)} {downloading ? `${Math.round(config.model.progress * 100)}%` : ''}</p>
          {!config.model.runtime_available && <p className="text-sm text-destructive">{t('tts.errors.runtime_missing')}</p>}
          <p className="text-xs text-muted-foreground">{t('tts.modelNotice')}</p>
          {config.model.state !== 'ready' && <Button variant="outline" disabled={pending} onClick={() => { void download(downloading); }}>
            {downloading ? t('tts.cancelDownload') : t('tts.download')}
          </Button>}
          {config.model.state === 'ready' && <Button variant="outline" disabled={pending} onClick={() => { void remove(); }}>{t('tts.deleteModel')}</Button>}
          <label className="block text-sm">{t('tts.voice')}
            <select className="mt-1 w-full rounded border bg-background p-2" value={draft.local_voice}
              onChange={(event) => setDraft({ ...draft, local_voice: event.target.value })}>
              {config.local_voices.map((voice) => <option key={voice.id} value={voice.id}>{voice.id} · {voice.language}</option>)}
            </select>
          </label>
          <label className="block text-sm">{t('tts.speed')}<Input type="number" min="0.5" max="2" step="0.1" value={draft.local_speed}
            onChange={(event) => setDraft({ ...draft, local_speed: Number(event.target.value) })} /></label>
        </> : <>
          <label className="block text-sm">{t('tts.provider')}
            <select className="mt-1 w-full rounded border bg-background p-2" value={draft.provider_id ?? ''}
              onChange={(event) => setDraft({ ...draft, provider_id: event.target.value || null })}>
              <option value="">{t('tts.chooseProvider')}</option>
              {Object.entries(providers).filter(([, value]) => value.enabled && value.services.tts.enabled).map(([id, value]) => <option key={id} value={id}>{value.display_name}</option>)}
            </select>
          </label>
          <p className="text-xs text-muted-foreground">{t('tts.remoteHint')}</p>
          {config.model.state === 'ready' && config.settings.engine === 'remote' && <Button variant="outline" disabled={pending} onClick={() => { void remove(); }}>{t('tts.deleteModel')}</Button>}
        </>}
        <Button disabled={!dirty || pending} onClick={() => { void save(); }}>{t('tts.save')}</Button>
        <label className="block text-sm">{t('tts.previewText')}<Input maxLength={4096} value={text} onChange={(event) => setText(event.target.value)} /></label>
        <Button variant="outline" disabled={dirty || !text.trim() || pending}
          onClick={() => { void controller.speak({ kind: 'text', text }); }}>{t('tts.preview')}</Button>
        <p className="text-xs text-muted-foreground">{t('tts.syntheticNotice')}</p>
        <TTSPlaybackControls controller={controller} state={state} />
      </>}
    </div>
  </SettingsGroup>;
}
