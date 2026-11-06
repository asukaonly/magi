import { useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TTSModelChoice, TTSReferenceAudio, TTSSettings } from '@/api/modules/tts';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { LabeledSelectField, NumberField } from './form-fields';

export function TTSVoiceCustomization({ model, draft, references, change, upload, removeReference, pending }: {
  model: TTSModelChoice;
  draft: TTSSettings;
  references: TTSReferenceAudio[];
  change: (value: Partial<TTSSettings>) => void;
  upload: (file: File) => void;
  removeReference: (id: string) => void;
  pending: boolean;
}) {
  const { t } = useTranslation('app');
  const uploadInput = useRef<HTMLInputElement>(null);
  const [name, setName] = useState('');
  const presets = draft.voice_presets.filter((preset) => preset.model_id === draft.local_model);
  const matching = presets.find((preset) => preset.voice === draft.local_voice && preset.speed === draft.local_speed
    && preset.description === draft.voice_description && preset.reference_audio === draft.reference_audio && preset.seed === draft.voice_seed);
  const canSavePreset = name.trim() && draft.voice_presets.length < 32
    && (model.reference_audio !== 'required' || draft.reference_audio);
  return <div className="space-y-4">
    {model.reference_audio !== 'none' && <div className="space-y-2">
      <LabeledSelectField label={t('tts.referenceAudio')} value={draft.reference_audio || '__none'}
        disabled={pending} options={[{ value: '__none', label: t(model.reference_audio === 'required' ? 'tts.selectReference' : 'tts.noReference') },
          ...references.map((reference) => ({ value: reference.id, label: `${reference.name} · ${reference.seconds.toFixed(1)}s` }))]}
        onChange={(value) => change({ reference_audio: value === '__none' ? '' : value })} />
      <p className="text-xs leading-5 text-muted-foreground">{t('tts.referenceHint')}</p>
      <div className="flex flex-wrap items-center gap-3">
        <input ref={uploadInput} type="file" accept=".wav,audio/wav" hidden disabled={pending}
          aria-label={t('tts.uploadReference')}
          onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ''; if (file) upload(file); }} />
        <Button variant="outline" size="sm" disabled={pending} onClick={() => uploadInput.current?.click()}>{t('tts.uploadReference')}</Button>
      </div>
      {references.length > 0 && <details className="space-y-2 text-sm">
        <summary className="cursor-pointer">{t('tts.manageReferences')}</summary>
        {references.map((reference) => <div key={reference.id} className="flex items-center justify-between gap-2">
          <span className="min-w-0 truncate">{reference.name}</span>
          <Button size="sm" variant="ghost" disabled={reference.id === draft.reference_audio || draft.voice_presets.some((preset) => preset.reference_audio === reference.id)}
            onClick={() => removeReference(reference.id)}>{t('tts.deleteReference')}</Button>
        </div>)}
      </details>}
    </div>}
    {model.voice_description && <label className="flex flex-col gap-2 text-sm font-semibold">
      {t('tts.voiceDescription')}
      <Textarea rows={2} maxLength={500} value={draft.voice_description} className="font-normal"
        placeholder={t('tts.voiceDescriptionPlaceholder')} onChange={(event) => change({ voice_description: event.target.value })} />
      <span className="text-xs font-normal leading-5 text-muted-foreground">{t(`tts.voiceDescriptionHints.${draft.local_model}`)}</span>
    </label>}
    <details className="space-y-3 text-sm">
      <summary className="cursor-pointer font-semibold">{t('tts.voicePresets')}</summary>
      <p className="text-xs leading-5 text-muted-foreground">{t('tts.voicePresetsHint')}</p>
      {presets.length > 0 && <div className="flex items-end gap-2">
        <LabeledSelectField className="min-w-0 flex-1" label={t('tts.savedVoice')} value={matching?.id ?? '__current'}
          options={[{ value: '__current', label: t('tts.currentVoice') }, ...presets.map((preset) => ({ value: preset.id, label: preset.name }))]}
          onChange={(id) => { const preset = presets.find((item) => item.id === id); if (preset) change({
            local_voice: preset.voice, local_speed: preset.speed, voice_description: preset.description,
            reference_audio: preset.reference_audio, voice_seed: preset.seed,
          }); }} />
        <Button variant="ghost" disabled={!matching} onClick={() => change({ voice_presets: draft.voice_presets.filter((preset) => preset.id !== matching?.id) })}>{t('tts.removePreset')}</Button>
      </div>}
      {model.seed && <NumberField label={t('tts.voiceSeed')} min={0} max={2147483647} step={1} value={draft.voice_seed}
        onChange={(voice_seed) => change({ voice_seed })} />}
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-0 flex-1 flex-col gap-2">{t('tts.presetName')}
          <Input value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
        </label>
        <Button variant="outline" disabled={!canSavePreset} onClick={() => {
          change({ voice_presets: [...draft.voice_presets, { id: crypto.randomUUID().replace(/-/g, ''), name: name.trim(),
            model_id: draft.local_model, voice: draft.local_voice, speed: draft.local_speed, description: draft.voice_description,
            reference_audio: draft.reference_audio, seed: draft.voice_seed }] }); setName('');
        }}>{t('tts.addPreset')}</Button>
      </div>
    </details>
  </div>;
}
