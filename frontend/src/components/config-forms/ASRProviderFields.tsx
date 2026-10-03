import { useTranslation } from 'react-i18next';
import type { LLMProviderASRConfig } from '@/api/modules/config';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';

export function ASRProviderFields({ value, onChange }: { value: LLMProviderASRConfig; onChange: (value: LLMProviderASRConfig) => void }) {
  const { t } = useTranslation('app');
  return <fieldset className="space-y-3 rounded-lg bg-muted/30 p-4">
    <legend className="text-sm font-semibold">{t('asr.providerTitle')}</legend>
    <label className="flex items-center justify-between gap-3 text-sm">{t('asr.providerEnabled')}
      <Switch checked={value.enabled} onCheckedChange={(enabled) => onChange({ ...value, enabled })} />
    </label>
    {value.enabled && <>
      <p className="text-xs text-muted-foreground">{t('asr.providerHint')}</p>
      <label className="flex flex-col gap-2 text-sm">{t('asr.model')}
        <Input value={value.model ?? ''} onChange={(event) => onChange({ ...value, model: event.target.value })} />
      </label>
      <details className="space-y-3 text-sm">
        <summary className="cursor-pointer">{t('asr.connectionOverrides')}</summary>
        <div className="grid gap-3 pt-3 sm:grid-cols-2">
          <label className="flex flex-col gap-2">{t('asr.endpoint')}<Input value={value.base_url ?? ''} onChange={(event) => onChange({ ...value, base_url: event.target.value })} /></label>
          <label className="flex flex-col gap-2">{t('asr.apiKey')}<Input type="password" autoComplete="off" value={value.api_key ?? ''} onChange={(event) => onChange({ ...value, api_key: event.target.value })} /></label>
          <label className="flex flex-col gap-2">{t('tts.timeout')}<Input type="number" min={5} max={180} step={1} value={value.timeout} onChange={(event) => onChange({ ...value, timeout: Number(event.target.value) })} /></label>
        </div>
      </details>
    </>}
  </fieldset>;
}
