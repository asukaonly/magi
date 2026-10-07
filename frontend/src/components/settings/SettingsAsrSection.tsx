import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { asrApi, asrErrorCode, type ASRModel } from '@/api/modules/asr';
import type { SystemConfig } from '@/api/modules/config';
import { getRuntimeConfig } from '@/runtime/config';
import { SettingsSectionShell } from './SettingsSectionPrimitives';
import { LabeledSelectField } from './form-fields';
import { Download, Trash2 } from 'lucide-react';
import { LoadingSpinner } from '@/components/ui/loading-spinner';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';

interface Props {
  draftConfig: SystemConfig;
  patchDraftConfig: (update: (draft: SystemConfig) => void) => void;
  onConfigureProviders: () => void;
}
export function SettingsAsrSection({ draftConfig, patchDraftConfig, onConfigureProviders }: Props) {
  const { t } = useTranslation('app');
  const [models, setModels] = useState<ASRModel[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<{ id: string; code: string } | null>(null);
  const [loaded, setLoaded] = useState(false);
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
        if (!abort.signal.aborted && version === modelRequestVersion.current) { setModels(value); setError(null); setLoaded(true); }
      } catch (reason) { if (!abort.signal.aborted && version === modelRequestVersion.current) setError(asrErrorCode(reason)); }
      if (!abort.signal.aborted && downloading) timer = setTimeout(() => { void load(); }, 1500);
    };
    void load();
    return () => { abort.abort(); if (timer) clearTimeout(timer); };
  }, [downloading]);
  const act = async (model: ASRModel, action: 'download' | 'cancel' | 'delete') => {
    modelRequestVersion.current += 1;
    setBusy(true); setActionError(null);
    try {
      const value = await asrApi.modelAction(model.id, action);
      modelRequestVersion.current += 1;
      if (mounted.current) setModels(current => current.map(item => item.id === value.id ? value : item));
    }
    catch (reason) { if (mounted.current) setActionError({ id: model.id, code: asrErrorCode(reason) }); }
    finally { if (mounted.current) setBusy(false); }
  };
  const families = [...new Set(models.map(model => model.family))].map(family => {
    const variants = models.filter(model => model.family === family);
    // Preserve an installed selection; new downloads use the catalog's first variant.
    return variants.find(model => model.id === settings.local_model_id && model.state === 'ready')
      ?? variants.find(model => model.state === 'downloading')
      ?? variants.find(model => model.state === 'ready')
      ?? variants[0];
  });
  const isRemoteConnection = getRuntimeConfig().mode === 'remote';
  const providers = Object.entries(draftConfig.llm.providers)
    .filter(([, item]) => item.enabled && item.services.asr.enabled);
  return <SettingsSectionShell className="space-y-5">
    <LabeledSelectField label={t('asr.mode')} value={settings.mode}
      options={[{ value: 'local', label: t(isRemoteConnection ? 'asr.serverModel' : 'asr.local') }, { value: 'remote', label: t('asr.remote') }]}
      onChange={(mode) => {
        if (mode === 'local' || mode === 'remote') patchDraftConfig(draft => {
          draft.speech.asr.mode = mode;
          if (mode === 'local') draft.speech.asr.language = 'auto';
        });
      }} />
    {error && <p role="alert" className="text-sm text-destructive">{t(`asr.errors.${error}`, { defaultValue: t('asr.errors.request_failed') })}</p>}
    {settings.mode === 'remote' ? <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <LabeledSelectField label={t('asr.provider')} value={settings.provider_id}
          options={[{ value: '', label: t('asr.selectProvider') }, ...providers.map(([id, item]) => ({ value: id, label: item.display_name }))]}
          onChange={(id) => patchDraftConfig(draft => { draft.speech.asr.provider_id = id; })} />
        <LabeledSelectField label={t('asr.language')} value={settings.language}
          options={(['auto', 'zh', 'en'] as const).map(language => ({ value: language, label: t(`asr.languages.${language}`) }))}
          onChange={(language) => {
            if (language === 'auto' || language === 'zh' || language === 'en') patchDraftConfig(draft => { draft.speech.asr.language = language; });
          }} />
      </div>
      {provider && <p className="text-sm text-muted-foreground">{t('asr.configuredModel', { model: provider.services.asr.model || t('asr.modelNotConfigured') })}</p>}
      {providers.length === 0 && <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
        <span>{t('asr.noProviders')}</span>
        <Button variant="outline" size="sm" onClick={onConfigureProviders}>{t('asr.addProvider')}</Button>
      </div>}
    </div> : <fieldset className="min-w-0 space-y-2">
      <legend className="mb-2 text-sm font-semibold">{t('asr.selectedModel')}</legend>
      {!loaded && !error && <div role="status" className="flex items-center gap-2 py-3 text-sm text-muted-foreground"><LoadingSpinner />{t('settings.loadingConfig')}</div>}
      {families.map(model => {
        const selected = model.id === settings.local_model_id;
        const title = t(`asr.families.${model.family}.name`);
        const problem = actionError?.id === model.id ? actionError.code : model.error;
        return <div key={model.family} role="group" aria-label={title}
          className={cn('rounded-lg border px-4 py-3', selected ? 'border-primary/40 bg-primary/[0.035]' : 'border-border/60')}>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <label className={cn('flex min-w-0 flex-1 items-center gap-3 py-1', model.state === 'ready' && 'cursor-pointer')}>
              <input type="radio" name="asr-model" checked={selected} disabled={busy || model.state !== 'ready'}
                className="h-4 w-4 shrink-0 accent-primary focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
                aria-label={title} onChange={() => patchDraftConfig(draft => { draft.speech.asr.local_model_id = model.id; })} />
              <span className="min-w-0 space-y-1">
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold">
                  {title}{model.recommended && <span className="text-xs font-normal text-primary">{t('asr.recommended')}</span>}
                </span>
                <span className="block text-xs leading-5 text-muted-foreground">{t(`asr.families.${model.family}.languages`)} · {t('asr.modelSize', { size: Math.round(model.size_bytes / 1048576) })}</span>
              </span>
            </label>
            <div className="ml-auto flex items-center gap-2">
              <span role="status" className="text-xs text-muted-foreground">
                {t(`asr.modelStates.${model.state}`)}{model.state === 'downloading' ? ` ${model.progress.toFixed(0)}%` : ''}
              </span>
              {model.state === 'downloading'
                ? <Button size="sm" variant="ghost" disabled={busy} onClick={() => { void act(model, 'cancel'); }}>{t('asr.cancel')}</Button>
                : model.state === 'ready'
                  ? <Button size="icon" variant="ghost" disabled={busy} aria-label={t('asr.delete')} title={t('asr.delete')}
                    onClick={() => { void act(model, 'delete'); }}><Trash2 className="h-4 w-4" /></Button>
                  : <Button size="sm" variant="outline" disabled={busy || downloading} onClick={() => { void act(model, 'download'); }}>
                    <Download className="mr-2 h-4 w-4" />{t('asr.download')}
                  </Button>}
            </div>
          </div>
          {problem && <p role="alert" className="mt-2 text-sm text-destructive">{t(`asr.errors.${problem}`, { defaultValue: t('asr.errors.request_failed') })}</p>}
        </div>;
      })}
    </fieldset>}
  </SettingsSectionShell>;
}
