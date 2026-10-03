import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { asrApi, asrErrorCode, type ASRModel } from '@/api/modules/asr';
import type { SystemConfig } from '@/api/modules/config';
import { getRuntimeConfig } from '@/runtime/config';
import { SettingsGroup, SettingsSectionShell, SettingsSwitchRow } from './SettingsSectionPrimitives';
import { LabeledSelectField } from './form-fields';
import { AudioDeviceTest } from './AudioDeviceTest';
import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface Props { draftConfig: SystemConfig; patchDraftConfig: (update: (draft: SystemConfig) => void) => void }
export function SettingsAsrSection({ draftConfig, patchDraftConfig }: Props) {
  const { t } = useTranslation('app');
  const [models, setModels] = useState<ASRModel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);
  const modelRequestVersion = useRef(0);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [busy, setBusy] = useState(false);
  const settings = draftConfig.speech.asr;
  const provider = draftConfig.llm.providers[settings.provider_id];
  const downloading = models.some(model => model.state === 'downloading');
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      const version = modelRequestVersion.current;
      try {
        const value = await asrApi.models(abort.signal);
        if (!abort.signal.aborted && version === modelRequestVersion.current) { setModels(value); setError(null); }
      } catch (reason) { if (!abort.signal.aborted && version === modelRequestVersion.current) setError(asrErrorCode(reason)); }
      if (!abort.signal.aborted && downloading) timer = setTimeout(() => { void load(); }, 1500);
    };
    void load();
    return () => { abort.abort(); if (timer) clearTimeout(timer); };
  }, [downloading]);
  const act = async (model: ASRModel, action: 'download' | 'cancel' | 'delete') => {
    modelRequestVersion.current += 1;
    setBusy(true); setError(null);
    try {
      const value = await asrApi.modelAction(model.id, action);
      modelRequestVersion.current += 1;
      if (mounted.current) setModels(current => current.map(item => item.id === value.id ? value : item));
    }
    catch (reason) { if (mounted.current) setError(asrErrorCode(reason)); }
    finally { if (mounted.current) setBusy(false); }
  };
  const updateService = (field: 'model' | 'base_url' | 'api_key', value: string) => {
    patchDraftConfig(draft => {
      const selected = draft.llm.providers[draft.speech.asr.provider_id];
      if (selected) { selected.services.asr[field] = value; selected.services.asr.enabled = true; }
    });
  };
  return <SettingsSectionShell>
    <SettingsGroup title={t('asr.setupTitle')}>
      <SettingsSwitchRow title={t('asr.enabled')} description={t('asr.description')} ariaLabel={t('asr.enabled')}
        checked={settings.enabled} onCheckedChange={(enabled) => patchDraftConfig(draft => { draft.speech.asr.enabled = enabled; })} />
      <LabeledSelectField label={t('asr.mode')} value={settings.mode}
        options={[{ value: 'local', label: t('asr.local') }, { value: 'remote', label: t('asr.remote') }]}
        onChange={(mode) => {
          if (mode === 'local' || mode === 'remote') patchDraftConfig(draft => {
            draft.speech.asr.mode = mode;
            if (mode === 'local') draft.speech.asr.language = 'auto';
          });
        }} />
      <p className="text-sm leading-6 text-muted-foreground">{settings.mode === 'remote'
        ? t('asr.remoteLocation', { provider: provider?.display_name || t('asr.selectProvider') })
        : t(getRuntimeConfig().mode === 'remote' ? 'asr.remoteCenterLocation' : 'asr.localLocation')}</p>
      {error && <p role="alert" className="text-sm text-destructive">{t(`asr.errors.${error}`, { defaultValue: t('asr.errors.request_failed') })}</p>}
    </SettingsGroup>
    {settings.mode === 'remote' ? <SettingsGroup title={t('asr.provider')} description={t('asr.providerHelp')}>
      <LabeledSelectField label={t('asr.provider')} value={settings.provider_id}
        options={[{ value: '', label: t('asr.selectProvider') }, ...Object.entries(draftConfig.llm.providers)
          .map(([id, item]) => ({ value: id, label: item.display_name, disabled: !item.enabled }))]}
        onChange={(id) => patchDraftConfig(draft => {
          draft.speech.asr.provider_id = id;
          const selected = draft.llm.providers[id];
          if (selected) selected.services.asr.enabled = true;
        })} />
      <div className="grid gap-5 sm:grid-cols-2">
        {provider && <label className="flex flex-col gap-2.5 text-sm font-semibold leading-6">
          {t('asr.model')}<Input className="h-11 rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.78)] px-4 font-normal"
            value={provider.services.asr.model ?? ''} onChange={event => updateService('model', event.target.value)} />
        </label>}
        <LabeledSelectField label={t('asr.language')} value={settings.language}
          options={(['auto', 'zh', 'en'] as const).map(language => ({ value: language, label: t(`asr.languages.${language}`) }))}
          onChange={(language) => {
            if (language === 'auto' || language === 'zh' || language === 'en') patchDraftConfig(draft => { draft.speech.asr.language = language; });
          }} />
      </div>
      {provider && <details className="rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.48)] p-4">
        <summary className="cursor-pointer rounded-sm text-sm font-medium focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring">{t('asr.connectionOverrides')}</summary>
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          <label className="flex flex-col gap-2.5 text-sm leading-6">{t('asr.endpoint')}
            <Input className="h-11 rounded-lg" value={provider.services.asr.base_url ?? ''} placeholder={provider.base_url}
              onChange={event => updateService('base_url', event.target.value)} />
          </label>
          <label className="flex flex-col gap-2.5 text-sm leading-6">{t('asr.apiKey')}
            <Input className="h-11 rounded-lg" type="password" autoComplete="new-password" value={provider.services.asr.api_key ?? ''}
              onChange={event => updateService('api_key', event.target.value)} />
          </label>
        </div>
      </details>}
    </SettingsGroup> : <SettingsGroup title={t('asr.localModel')}>
      <LabeledSelectField label={t('asr.selectedModel')} value={settings.local_model_id}
        options={[
          ...(!models.some(model => model.id === settings.local_model_id)
            ? [{ value: settings.local_model_id, label: settings.local_model_id, disabled: true }] : []),
          ...models.map(model => ({ value: model.id, label: model.label, disabled: model.state !== 'ready' })),
        ]}
        onChange={(id) => {
          if (models.some(model => model.id === id && model.state === 'ready')) {
            patchDraftConfig(draft => { draft.speech.asr.local_model_id = id; });
          }
        }} />
      <p className="text-xs leading-6 text-muted-foreground">{t('asr.modelChoiceHelp')}</p>
      {models.map(model => <div key={model.id} role="group" aria-label={model.label} className="space-y-4 rounded-lg bg-[hsl(var(--settings-shell-elevated)/0.48)] p-5 shadow-[inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.2)]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1">
            <p className="text-sm font-semibold">{model.label}</p>
            <p className="text-xs leading-5 text-muted-foreground">{t('asr.modelSize', { size: Math.round(model.size_bytes / 1048576) })}</p>
          </div>
          <span role="status" className="rounded-md bg-muted px-2.5 py-1 text-xs text-muted-foreground">
            {t(`asr.modelStates.${model.state}`)}{model.state === 'downloading' ? ` ${model.progress.toFixed(0)}%` : ''}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" disabled={busy || downloading || model.state === 'ready'} onClick={() => { void act(model, 'download'); }}>
            <Download className="mr-2 h-4 w-4" />{t('asr.download')}
          </Button>
          {model.state === 'downloading' && <Button variant="ghost" disabled={busy} onClick={() => { void act(model, 'cancel'); }}>{t('asr.cancel')}</Button>}
          {model.state === 'ready' && <Button variant="ghost" disabled={busy || (settings.enabled && model.id === settings.local_model_id)} onClick={() => { void act(model, 'delete'); }}>{t('asr.delete')}</Button>}
        </div>
        <details className="text-xs leading-6 text-muted-foreground">
          <summary className="cursor-pointer rounded-sm focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring">{t('asr.modelDetails')}</summary>
          <p className="mt-2">{t('asr.experimental')}</p>
          <div className="mt-2 flex flex-wrap gap-4">
            <a href={model.license_url} target="_blank" rel="noreferrer" className="underline underline-offset-4">{t('asr.license')}</a>
            <a href={model.source_url} target="_blank" rel="noreferrer" className="underline underline-offset-4">{t('asr.source')}</a>
          </div>
        </details>
        {model.error && <p role="alert" className="text-sm text-destructive">{t(`asr.errors.${model.error}`, { defaultValue: t('asr.errors.request_failed') })}</p>}
      </div>)}
      <p className="text-xs leading-6 text-muted-foreground">{t('asr.deleteHelp')}</p>
    </SettingsGroup>}
    <p className="text-sm leading-6 text-muted-foreground">{t('asr.saveFirst')}</p>
    <AudioDeviceTest />
  </SettingsSectionShell>;
}
