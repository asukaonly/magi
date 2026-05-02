import React from 'react';
import { Plus, Trash2, Upload } from 'lucide-react';
import { AutoResizeTextarea } from '@/components/ui/auto-resize-textarea';
import { Button } from '@/components/ui/button';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import type {
  PersonaLayerItem,
  PersonaRegister,
  PersonalityConfig,
  QuietHour,
  SignatureTrigger,
} from '@/api/modules/personas';
import { formatPersonaValidationIssues, validatePersonalityConfig } from '@/utils/personaValidation';

interface PersonalityDetailEditorProps {
  config: PersonalityConfig;
  patch: (fn: (draft: PersonalityConfig) => void) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
  onAvatarUpload?: (event: React.ChangeEvent<HTMLInputElement>) => void;
  uploadingAvatar?: boolean;
  avatarFilename?: string;
}

type EditorMode = 'quick' | 'expert';

const REGISTER_KEYS = ['chat', 'analysis', 'task', 'emotional', 'crisis'] as const;

const toLines = (items: string[] = []): string => items.join('\n');

const parseLines = (value: string): string[] =>
  value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);

const mappingToLines = (value: Record<string, unknown> = {}): string =>
  Object.entries(value)
    .map(([key, item]) => `${key}: ${String(item)}`)
    .join('\n');

const linesToMapping = (value: string): Record<string, string> => {
  const result: Record<string, string> = {};
  for (const line of parseLines(value)) {
    const separator = line.indexOf(':');
    if (separator <= 0) continue;
    const key = line.slice(0, separator).trim();
    const item = line.slice(separator + 1).trim();
    if (key) result[key] = item;
  }
  return result;
};

const normalizeTrigger = (item: Partial<SignatureTrigger> = {}): SignatureTrigger => ({
  trigger_id: item.trigger_id || '',
  activates_when: item.activates_when || '',
  behavior_shift: item.behavior_shift || '',
  intensity_levels: item.intensity_levels || {},
  exit_behavior: item.exit_behavior || '',
});

const normalizeQuietHour = (item: Partial<QuietHour> = {}): QuietHour => ({
  condition: item.condition || '',
  clamps: item.clamps || {},
});

const normalizeLayer = (item: Partial<PersonaLayerItem> = {}): PersonaLayerItem => ({
  layer_id: item.layer_id || '',
  unlock_condition: item.unlock_condition ?? null,
  modifiers: item.modifiers || {},
});

const normalizeRegister = (item?: Partial<PersonaRegister>): PersonaRegister => ({
  description: item?.description || '',
  behavior: item?.behavior || '',
  examples: item?.examples || [],
});

const Section: React.FC<{
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}> = ({ title, defaultOpen = true, children }) => (
  <Collapsible className="space-y-1" defaultOpen={defaultOpen}>
    <CollapsibleTrigger className="rounded-md px-2 py-1.5 text-sm font-medium hover:bg-muted">
      {title}
    </CollapsibleTrigger>
    <CollapsibleContent className="pt-2">{children}</CollapsibleContent>
  </Collapsible>
);

const PersonalityDetailEditor: React.FC<PersonalityDetailEditorProps> = ({
  config,
  patch,
  t,
  onAvatarUpload,
  uploadingAvatar = false,
  avatarFilename,
}) => {
  const [mode, setMode] = React.useState<EditorMode>('quick');
  const validation = React.useMemo(() => validatePersonalityConfig(config), [config]);
  const missingFields = formatPersonaValidationIssues(validation.minimumIssues, t);
  const expertFields = formatPersonaValidationIssues(validation.expertIssues, t);

  const updateRegister = (key: (typeof REGISTER_KEYS)[number], next: PersonaRegister) => {
    patch((draft) => {
      draft.registers[key] = next;
    });
  };

  const renderBasicProfile = (defaultOpen = true) => (
    <Section title={t('personality.sections.basicProfile')} defaultOpen={defaultOpen}>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.name')}</span>
          <Input value={config.name} onChange={(event) => patch((draft) => { draft.name = event.target.value; })} />
        </label>
        <label className="space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.description')}</span>
          <Input value={config.description} onChange={(event) => patch((draft) => { draft.description = event.target.value; })} />
        </label>
        {onAvatarUpload && (
          <label className="space-y-1.5 md:col-span-2">
            <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.avatar')}</span>
            <div className="flex flex-wrap items-center gap-2">
              <input
                id="personality-detail-avatar-upload"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={onAvatarUpload}
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={uploadingAvatar}
                onClick={() => document.getElementById('personality-detail-avatar-upload')?.click()}
              >
                <Upload className="h-4 w-4" />
                {uploadingAvatar ? t('personality.actions.uploadingAvatar') : t('personality.actions.uploadAvatar')}
              </Button>
              <span className="text-xs text-muted-foreground">{avatarFilename || t('personality.noAvatar')}</span>
            </div>
          </label>
        )}
      </div>
    </Section>
  );

  const renderQuickIdentity = () => (
    <Section title={t('personality.sections.identityCore')}>
      <div className="grid gap-3">
        <label className="space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.identityStatement')}</span>
          <AutoResizeTextarea
            value={config.identity_core.identity_statement}
            minHeight={112}
            className="w-full"
            onChange={(event) => patch((draft) => { draft.identity_core.identity_statement = event.target.value; })}
          />
        </label>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.valuesLoved')}</span>
            <AutoResizeTextarea
              value={toLines(config.identity_core.values_loved)}
              className="w-full"
              onChange={(event) => patch((draft) => { draft.identity_core.values_loved = parseLines(event.target.value); })}
            />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.valuesRejected')}</span>
            <AutoResizeTextarea
              value={toLines(config.identity_core.values_rejected)}
              className="w-full"
              onChange={(event) => patch((draft) => { draft.identity_core.values_rejected = parseLines(event.target.value); })}
            />
          </label>
        </div>
      </div>
    </Section>
  );

  const renderIdentityCore = (defaultOpen = true) => (
    <Section title={t('personality.sections.identityCore')} defaultOpen={defaultOpen}>
      <div className="grid gap-3">
        <label className="space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.identityStatement')}</span>
          <AutoResizeTextarea
            value={config.identity_core.identity_statement}
            minHeight={120}
            className="w-full"
            onChange={(event) => patch((draft) => { draft.identity_core.identity_statement = event.target.value; })}
          />
        </label>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.valuesLoved')}</span>
            <AutoResizeTextarea
              value={toLines(config.identity_core.values_loved)}
              className="w-full"
              onChange={(event) => patch((draft) => { draft.identity_core.values_loved = parseLines(event.target.value); })}
            />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.valuesRejected')}</span>
            <AutoResizeTextarea
              value={toLines(config.identity_core.values_rejected)}
              className="w-full"
              onChange={(event) => patch((draft) => { draft.identity_core.values_rejected = parseLines(event.target.value); })}
            />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.attentionBiases')}</span>
            <AutoResizeTextarea
              value={toLines(config.identity_core.attention_biases)}
              className="w-full"
              onChange={(event) => patch((draft) => { draft.identity_core.attention_biases = parseLines(event.target.value); })}
            />
          </label>
        </div>
      </div>
    </Section>
  );

  const renderQuickVoice = () => {
    const chatRegister = normalizeRegister(config.registers.chat);
    return (
      <Section title={t('personality.sections.idiolect')}>
        <div className="grid gap-3">
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.sentenceStyle')}</span>
            <AutoResizeTextarea
              value={config.idiolect.sentence_style}
              className="w-full"
              onChange={(event) => patch((draft) => { draft.idiolect.sentence_style = event.target.value; })}
            />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.chatBehavior')}</span>
            <AutoResizeTextarea
              value={chatRegister.behavior}
              minHeight={88}
              className="w-full"
              onChange={(event) => updateRegister('chat', { ...chatRegister, behavior: event.target.value })}
            />
          </label>
        </div>
      </Section>
    );
  };

  const renderIdiolect = (defaultOpen = true) => (
    <Section title={t('personality.sections.idiolect')} defaultOpen={defaultOpen}>
      <div className="grid gap-3">
        <label className="space-y-1.5">
          <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.sentenceStyle')}</span>
          <AutoResizeTextarea
            value={config.idiolect.sentence_style}
            className="w-full"
            onChange={(event) => patch((draft) => { draft.idiolect.sentence_style = event.target.value; })}
          />
        </label>
        <div className="grid gap-3 md:grid-cols-3">
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.vocabAvailable')}</span>
            <AutoResizeTextarea value={toLines(config.idiolect.vocab_available)} onChange={(event) => patch((draft) => { draft.idiolect.vocab_available = parseLines(event.target.value); })} />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.vocabAvoided')}</span>
            <AutoResizeTextarea value={toLines(config.idiolect.vocab_avoided)} onChange={(event) => patch((draft) => { draft.idiolect.vocab_avoided = parseLines(event.target.value); })} />
          </label>
          <label className="space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">{t('personality.fields.structuralQuirks')}</span>
            <AutoResizeTextarea value={toLines(config.idiolect.structural_quirks)} onChange={(event) => patch((draft) => { draft.idiolect.structural_quirks = parseLines(event.target.value); })} />
          </label>
        </div>
      </div>
    </Section>
  );

  const renderRegisterEditor = (key: (typeof REGISTER_KEYS)[number]) => {
    const register = normalizeRegister(config.registers[key]);
    return (
      <div key={key} className="rounded-md border border-border/70 p-2">
        <div className="mb-2 text-xs font-medium text-muted-foreground">{t(`personality.registers.${key}`)}</div>
        <div className="grid gap-2">
          <Input
            value={register.description}
            placeholder={t('personality.fields.registerDescription')}
            onChange={(event) => updateRegister(key, { ...register, description: event.target.value })}
          />
          <AutoResizeTextarea
            value={register.behavior}
            minHeight={76}
            placeholder={t('personality.fields.registerBehavior')}
            onChange={(event) => updateRegister(key, { ...register, behavior: event.target.value })}
          />
          <AutoResizeTextarea
            value={toLines(register.examples)}
            minHeight={76}
            placeholder={t('personality.fields.registerExamples')}
            onChange={(event) => updateRegister(key, { ...register, examples: parseLines(event.target.value) })}
          />
        </div>
      </div>
    );
  };

  const renderRegisters = (keys: readonly (typeof REGISTER_KEYS)[number][], defaultOpen = true) => (
    <Section title={t('personality.sections.registers')} defaultOpen={defaultOpen}>
      <div className="space-y-3">{keys.map(renderRegisterEditor)}</div>
    </Section>
  );

  const renderTriggers = (expert: boolean, defaultOpen = true) => (
    <Section title={t('personality.sections.signatureTriggers')} defaultOpen={defaultOpen}>
      <div className="space-y-3">
        {config.signature_triggers.map((item, index) => (
          <div key={index} className="rounded-md border border-border/70 p-2">
            <div className="grid gap-2">
              <Input value={item.trigger_id} placeholder={t('personality.fields.triggerId')} onChange={(event) => patch((draft) => { draft.signature_triggers[index] = normalizeTrigger({ ...item, trigger_id: event.target.value }); })} />
              <Input value={item.activates_when} placeholder={t('personality.fields.activatesWhen')} onChange={(event) => patch((draft) => { draft.signature_triggers[index] = normalizeTrigger({ ...item, activates_when: event.target.value }); })} />
              <AutoResizeTextarea value={item.behavior_shift} minHeight={76} placeholder={t('personality.fields.behaviorShift')} onChange={(event) => patch((draft) => { draft.signature_triggers[index] = normalizeTrigger({ ...item, behavior_shift: event.target.value }); })} />
              {expert && (
                <>
                  <AutoResizeTextarea value={mappingToLines(item.intensity_levels)} placeholder={t('personality.fields.intensityLevels')} onChange={(event) => patch((draft) => { draft.signature_triggers[index] = normalizeTrigger({ ...item, intensity_levels: linesToMapping(event.target.value) }); })} />
                  <Input value={item.exit_behavior} placeholder={t('personality.fields.exitBehavior')} onChange={(event) => patch((draft) => { draft.signature_triggers[index] = normalizeTrigger({ ...item, exit_behavior: event.target.value }); })} />
                </>
              )}
              <div className="flex justify-end">
                <Button type="button" variant="outline" size="sm" disabled={config.signature_triggers.length === 1} onClick={() => patch((draft) => { if (draft.signature_triggers.length > 1) draft.signature_triggers.splice(index, 1); })}>
                  <Trash2 className="h-4 w-4" />
                  {t('personality.actions.removeTrigger')}
                </Button>
              </div>
            </div>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={() => patch((draft) => { draft.signature_triggers.push(normalizeTrigger()); })}>
          <Plus className="h-4 w-4" />
          {t('personality.actions.addTrigger')}
        </Button>
      </div>
    </Section>
  );

  const renderQuietHours = (defaultOpen = true) => (
    <Section title={t('personality.sections.quietHours')} defaultOpen={defaultOpen}>
      <div className="space-y-3">
        {config.quiet_hours.map((item, index) => (
          <div key={index} className="rounded-md border border-border/70 p-2">
            <div className="grid gap-2">
              <Input value={item.condition} placeholder={t('personality.fields.quietHourCondition')} onChange={(event) => patch((draft) => { draft.quiet_hours[index] = normalizeQuietHour({ ...item, condition: event.target.value }); })} />
              <AutoResizeTextarea value={mappingToLines(item.clamps)} placeholder={t('personality.fields.clamps')} onChange={(event) => patch((draft) => { draft.quiet_hours[index] = normalizeQuietHour({ ...item, clamps: linesToMapping(event.target.value) }); })} />
              <div className="flex justify-end">
                <Button type="button" variant="outline" size="sm" onClick={() => patch((draft) => { draft.quiet_hours.splice(index, 1); })}>
                  <Trash2 className="h-4 w-4" />
                  {t('personality.actions.removeQuietHour')}
                </Button>
              </div>
            </div>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={() => patch((draft) => { draft.quiet_hours.push(normalizeQuietHour()); })}>
          <Plus className="h-4 w-4" />
          {t('personality.actions.addQuietHour')}
        </Button>
      </div>
    </Section>
  );

  const renderAppearance = () => (
    <Section title={t('personality.sections.appearance')} defaultOpen={false}>
      <AutoResizeTextarea value={config.appearance_prompt} className="w-full" onChange={(event) => patch((draft) => { draft.appearance_prompt = event.target.value; })} />
    </Section>
  );

  const renderLayers = () => (
    <Section title={t('personality.sections.personaLayers')} defaultOpen={false}>
      <div className="space-y-3">
        {(config.persona_layers || []).map((item, index) => (
          <div key={index} className="rounded-md border border-border/70 p-2">
            <div className="grid gap-2">
              <Input value={item.layer_id} placeholder={t('personality.fields.layerId')} onChange={(event) => patch((draft) => { draft.persona_layers[index] = normalizeLayer({ ...item, layer_id: event.target.value }); })} />
              <AutoResizeTextarea value={mappingToLines(item.unlock_condition || {})} placeholder={t('personality.fields.unlockCondition')} onChange={(event) => patch((draft) => { draft.persona_layers[index] = normalizeLayer({ ...item, unlock_condition: linesToMapping(event.target.value) }); })} />
              <AutoResizeTextarea value={mappingToLines(item.modifiers)} placeholder={t('personality.fields.layerModifiers')} onChange={(event) => patch((draft) => { draft.persona_layers[index] = normalizeLayer({ ...item, modifiers: linesToMapping(event.target.value) }); })} />
              <div className="flex justify-end">
                <Button type="button" variant="outline" size="sm" disabled={item.layer_id === 'surface'} onClick={() => patch((draft) => { draft.persona_layers.splice(index, 1); })}>
                  <Trash2 className="h-4 w-4" />
                  {t('personality.actions.removeLayer')}
                </Button>
              </div>
            </div>
          </div>
        ))}
        <Button type="button" variant="outline" size="sm" onClick={() => patch((draft) => { draft.persona_layers.push(normalizeLayer({ layer_id: 'crack' })); })}>
          <Plus className="h-4 w-4" />
          {t('personality.actions.addLayer')}
        </Button>
      </div>
    </Section>
  );

  const validationMessage = (() => {
    if (mode !== 'expert') return '';
    if (!validation.isMinimumReady) {
      return t('personality.validation.missing', { fields: missingFields.join(', ') });
    }
    if (!validation.isExpertReady) {
      return t('personality.validation.expertMissing', { fields: expertFields.join(', ') });
    }
    return '';
  })();

  return (
    <div className="space-y-3 pr-1">
      {validationMessage ? (
        <div className="rounded-md border border-border/70 bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
          {validationMessage}
        </div>
      ) : null}

      <Tabs value={mode} onValueChange={(value) => setMode(value as EditorMode)}>
        <TabsList className="grid w-full grid-cols-2 sm:w-auto">
          <TabsTrigger value="quick">{t('personality.editorModes.quick')}</TabsTrigger>
          <TabsTrigger value="expert">{t('personality.editorModes.expert')}</TabsTrigger>
        </TabsList>

        <TabsContent value="quick" className="mt-3 space-y-1">
          {renderBasicProfile()}
          {renderQuickIdentity()}
          {renderQuickVoice()}
        </TabsContent>

        <TabsContent value="expert" className="mt-3 space-y-1">
          {renderBasicProfile()}
          {renderIdentityCore(false)}
          {renderIdiolect(false)}
          {renderRegisters(REGISTER_KEYS, false)}
          {renderTriggers(true, false)}
          {renderQuietHours(false)}
          {renderAppearance()}
          {renderLayers()}
        </TabsContent>
      </Tabs>
    </div>
  );
};

export default PersonalityDetailEditor;
