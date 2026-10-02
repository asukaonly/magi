import { useTranslation } from 'react-i18next';
import type { LLMProviderTTSConfig } from '@/api/modules/config';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';

export function TTSProviderFields({ value, onChange }: { value: LLMProviderTTSConfig; onChange: (value: LLMProviderTTSConfig) => void }) {
  const { t } = useTranslation('app');
  return <fieldset className="space-y-3 rounded-lg bg-muted/30 p-4">
    <legend className="text-sm font-semibold">{t('tts.providerTitle')}</legend>
    <label className="flex items-center justify-between gap-3 text-sm">{t('tts.enabled')}
      <Switch checked={value.enabled} onCheckedChange={(enabled) => onChange({ ...value, enabled, response_format: 'wav' })} />
    </label>
    {value.enabled && <>
      <p className="text-xs text-muted-foreground">{t('tts.providerHint')}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">{t('tts.model')}<Input value={value.model ?? ''} onChange={(e) => onChange({ ...value, model: e.target.value })} /></label>
        <label className="text-sm">{t('tts.voice')}<Input value={value.voice ?? ''} onChange={(e) => onChange({ ...value, voice: e.target.value })} /></label>
        <label className="text-sm">{t('tts.endpoint')}<Input value={value.base_url ?? ''} onChange={(e) => onChange({ ...value, base_url: e.target.value })} /></label>
        <label className="text-sm">{t('tts.apiKey')}<Input type="password" autoComplete="off" value={value.api_key ?? ''} onChange={(e) => onChange({ ...value, api_key: e.target.value })} /></label>
        <label className="text-sm">{t('tts.speed')}<Input type="number" min="0.5" max="2" step="0.1" value={value.speed ?? 1} onChange={(e) => onChange({ ...value, speed: Number(e.target.value) })} /></label>
        <label className="text-sm">{t('tts.timeout')}<Input type="number" min="1" max="180" value={value.timeout ?? 90} onChange={(e) => onChange({ ...value, timeout: Number(e.target.value) })} /></label>
      </div>
    </>}
  </fieldset>;
}
