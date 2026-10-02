import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { asrApi, asrErrorCode, type ASRModel } from '@/api/modules/asr';
import type { SystemConfig } from '@/api/modules/config';
import { getRuntimeConfig } from '@/runtime/config';
import { SettingsGroup } from './SettingsSectionPrimitives';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';

interface Props { draftConfig: SystemConfig; patchDraftConfig: (update: (draft: SystemConfig) => void) => void }
export function SettingsAsrSection({ draftConfig, patchDraftConfig }: Props) {
  const { t } = useTranslation('app');
  const [models, setModels] = useState<ASRModel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [busy, setBusy] = useState(false);
  const settings = draftConfig.speech.asr;
  const provider = draftConfig.llm.providers[settings.provider_id];
  const downloading = models.some(model => model.state === 'downloading');
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const value = await asrApi.models(abort.signal);
        if (!abort.signal.aborted) { setModels(value); }
      } catch (reason) { if (!abort.signal.aborted) setError(asrErrorCode(reason)); }
      if (!abort.signal.aborted && downloading) timer = setTimeout(() => { void load(); }, 1500);
    };
    void load();
    return () => { abort.abort(); if (timer) clearTimeout(timer); };
  }, [downloading]);
  const act = async (model: ASRModel, action: 'download' | 'cancel' | 'delete') => {
    setBusy(true); setError(null);
    try { const value = await asrApi.modelAction(model.id, action); if (mounted.current) setModels([value]); }
    catch (reason) { if (mounted.current) setError(asrErrorCode(reason)); }
    finally { if (mounted.current) setBusy(false); }
  };
  const updateService = (field: 'model' | 'base_url' | 'api_key', value: string) => {
    patchDraftConfig(draft => {
      const selected = draft.llm.providers[draft.speech.asr.provider_id];
      if (selected) { selected.services.asr[field] = value; selected.services.asr.enabled = true; }
    });
  };
  const selectClass = 'h-10 w-full rounded-md border border-input bg-background px-3 text-sm';
  return <div className="space-y-6">
    <SettingsGroup title={t('asr.title')} description={t('asr.description')}>
      <div className="space-y-4">
        <label className="flex items-center justify-between gap-4"><span>{t('asr.enabled')}</span><Switch checked={settings.enabled} onCheckedChange={value => patchDraftConfig(draft => { draft.speech.asr.enabled = value; })} /></label>
        <label className="block space-y-1"><span className="text-sm">{t('asr.mode')}</span>
          <select value={settings.mode} className={selectClass} onChange={event => {
            const mode = event.target.value;
            if (mode === 'local' || mode === 'remote') patchDraftConfig(draft => { draft.speech.asr.mode = mode; if (mode === 'local') draft.speech.asr.language = 'auto'; });
          }}><option value="local">{t('asr.local')}</option><option value="remote">{t('asr.remote')}</option></select></label>
        <p className="text-sm text-muted-foreground">{settings.mode === 'remote' ? t('asr.remoteLocation', { provider: provider?.display_name || t('asr.selectProvider') })
          : t(getRuntimeConfig().mode === 'remote' ? 'asr.remoteCenterLocation' : 'asr.localLocation')}</p>
        {settings.mode === 'remote' && <div className="space-y-4">
          <label className="block space-y-1"><span className="text-sm">{t('asr.provider')}</span><select className={selectClass} value={settings.provider_id} onChange={event => {
            const id = event.target.value;
            patchDraftConfig(draft => { draft.speech.asr.provider_id = id; const selected = draft.llm.providers[id]; if (selected) selected.services.asr.enabled = true; });
          }}><option value="">{t('asr.selectProvider')}</option>{Object.entries(draftConfig.llm.providers).map(([id, item]) => <option key={id} value={id} disabled={!item.enabled}>{item.display_name}</option>)}</select></label>
          <p className="text-xs text-muted-foreground">{t('asr.providerHelp')}</p>
          {provider && <>
            <label className="block space-y-1"><span className="text-sm">{t('asr.model')}</span><Input value={provider.services.asr.model ?? ''} onChange={event => updateService('model', event.target.value)} /></label>
            <label className="block space-y-1"><span className="text-sm">{t('asr.endpoint')}</span><Input value={provider.services.asr.base_url ?? ''} placeholder={provider.base_url} onChange={event => updateService('base_url', event.target.value)} /></label>
            <label className="block space-y-1"><span className="text-sm">{t('asr.apiKey')}</span><Input type="password" autoComplete="new-password" value={provider.services.asr.api_key ?? ''} onChange={event => updateService('api_key', event.target.value)} /></label>
          </>}
          <label className="block space-y-1"><span className="text-sm">{t('asr.language')}</span><select className={selectClass} value={settings.language} onChange={event => {
            const language = event.target.value;
            if (language === 'auto' || language === 'zh' || language === 'en') patchDraftConfig(draft => { draft.speech.asr.language = language; });
          }}>{(['auto', 'zh', 'en'] as const).map(language => <option key={language} value={language}>{t(`asr.languages.${language}`)}</option>)}</select></label>
        </div>}
        <p className="text-xs text-muted-foreground">{t('asr.saveFirst')}</p>
      </div>
    </SettingsGroup>
    {settings.mode === 'local' && <SettingsGroup title={t('asr.localModel')} description={t('asr.experimental')}>
      <div className="space-y-3">
        {models.map(model => <div key={model.id} className="space-y-2">
          <p className="text-sm font-medium">{model.label} · {Math.round(model.size_bytes / 1048576)} MB</p>
          <p role="status" className="text-xs">{t(`asr.modelStates.${model.state}`)}{model.state === 'downloading' ? ` ${model.progress.toFixed(0)}%` : ''}</p>
          <div className="flex gap-3 text-xs"><a href={model.license_url} target="_blank" rel="noreferrer" className="underline">{t('asr.license')}</a><a href={model.source_url} target="_blank" rel="noreferrer" className="underline">{t('asr.source')}</a></div>
          <div className="flex gap-2">
            <Button variant="outline" disabled={busy || downloading || model.state === 'ready'} onClick={() => { void act(model, 'download'); }}>{t('asr.download')}</Button>
            {model.state === 'downloading' && <Button variant="ghost" disabled={busy} onClick={() => { void act(model, 'cancel'); }}>{t('asr.cancel')}</Button>}
            {model.state === 'ready' && <Button variant="ghost" disabled={busy} onClick={() => { void act(model, 'delete'); }}>{t('asr.delete')}</Button>}
          </div>
          {model.error && <p role="alert" className="text-xs text-destructive">{t(`asr.errors.${model.error}`, { defaultValue: t('asr.errors.request_failed') })}</p>}
        </div>)}
        {error && <p role="alert" className="text-sm text-destructive">{t(`asr.errors.${error}`, { defaultValue: t('asr.errors.request_failed') })}</p>}
      </div>
    </SettingsGroup>}
  </div>;
}
