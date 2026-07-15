import { useState, type ReactNode } from 'react';
import { ChevronDown, Eye } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import type {
  PersonaLayerItem,
  PersonaRegister,
  PersonalityConfig,
  QuietHour,
  SignatureTrigger,
} from '../../api/modules/personas';

const REGISTER_KEYS = ['chat', 'analysis', 'task', 'emotional', 'crisis'] as const;

interface PersonaProfilePanelProps {
  config: PersonalityConfig;
}

interface ProfileSectionProps {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}

function ProfileSection({ title, children, defaultOpen = false }: ProfileSectionProps): JSX.Element {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      className="group border-b border-border/45 last:border-b-0"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 py-4 text-left [&::-webkit-details-marker]:hidden">
        <span className="text-sm font-semibold text-foreground">{title}</span>
        <ChevronDown
          className="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 group-open:rotate-180"
          aria-hidden="true"
        />
      </summary>
      <div className="pb-5">{children}</div>
    </details>
  );
}

function TextField({ label, value }: { label: string; value?: string | null }): JSX.Element | null {
  if (!value?.trim()) return null;
  return (
    <div>
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <p className="mt-1.5 whitespace-pre-wrap text-sm leading-6 text-foreground/90">{value}</p>
    </div>
  );
}

function ListField({ label, values }: { label: string; values?: string[] }): JSX.Element | null {
  const items = (values ?? []).map((value) => String(value).trim()).filter(Boolean);
  if (items.length === 0) return null;
  return (
    <div>
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <ul className="mt-2 space-y-1.5 text-sm leading-6 text-foreground/90">
        {items.map((item, index) => (
          <li key={`${item}-${index}`} className="flex items-start gap-2">
            <span className="mt-[0.65rem] h-1 w-1 shrink-0 rounded-full bg-primary/70" aria-hidden="true" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function formatValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join('、');
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key}: ${String(item)}`)
      .join('；');
  }
  return String(value ?? '');
}

function MappingField({ label, value }: { label: string; value?: Record<string, unknown> }): JSX.Element | null {
  const entries = Object.entries(value ?? {}).filter(([, item]) => item !== '' && item != null);
  if (entries.length === 0) return null;
  return (
    <div>
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <dl className="mt-2 grid gap-x-4 gap-y-2 text-sm sm:grid-cols-[minmax(9rem,auto)_1fr]">
        {entries.map(([key, item]) => (
          <div key={key} className="contents">
            <dt className="text-muted-foreground">{key}</dt>
            <dd className="break-words text-foreground/90">{formatValue(item)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function RegisterPanel({
  name,
  register,
  behaviorLabel,
  examplesLabel,
}: {
  name: string;
  register: PersonaRegister;
  behaviorLabel: string;
  examplesLabel: string;
}): JSX.Element {
  return (
    <div className="border-t border-border/40 py-4 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h4 className="text-sm font-semibold text-foreground">{name}</h4>
        {register.description ? (
          <span className="text-xs text-muted-foreground">{register.description}</span>
        ) : null}
      </div>
      <div className="mt-3 space-y-4">
        <TextField label={behaviorLabel} value={register.behavior} />
        <ListField label={examplesLabel} values={register.examples} />
      </div>
    </div>
  );
}

function TriggerPanel({
  trigger,
  index,
  title,
  activatesWhenLabel,
  behaviorShiftLabel,
  exitBehaviorLabel,
  intensityLabel,
}: {
  trigger: SignatureTrigger;
  index: number;
  title: string;
  activatesWhenLabel: string;
  behaviorShiftLabel: string;
  exitBehaviorLabel: string;
  intensityLabel: string;
}): JSX.Element {
  return (
    <div className="border-t border-border/40 py-4 first:border-t-0 first:pt-0 last:pb-0">
      <h4 className="text-sm font-semibold text-foreground">{title || String(index + 1)}</h4>
      <div className="mt-3 space-y-4">
        <TextField label={activatesWhenLabel} value={trigger.activates_when} />
        <TextField label={behaviorShiftLabel} value={trigger.behavior_shift} />
        <MappingField label={intensityLabel} value={trigger.intensity_levels} />
        <TextField label={exitBehaviorLabel} value={trigger.exit_behavior} />
      </div>
    </div>
  );
}

function QuietHourPanel({
  item,
  index,
  title,
  conditionLabel,
  clampsLabel,
}: {
  item: QuietHour;
  index: number;
  title: string;
  conditionLabel: string;
  clampsLabel: string;
}): JSX.Element {
  return (
    <div className="border-t border-border/40 py-4 first:border-t-0 first:pt-0 last:pb-0">
      <h4 className="text-sm font-semibold text-foreground">{title || String(index + 1)}</h4>
      <div className="mt-3 space-y-4">
        <TextField label={conditionLabel} value={item.condition} />
        <MappingField label={clampsLabel} value={item.clamps} />
      </div>
    </div>
  );
}

function LayerPanel({
  layer,
  index,
  title,
  unlockLabel,
  behaviorLabel,
  modifiersLabel,
}: {
  layer: PersonaLayerItem;
  index: number;
  title: string;
  unlockLabel: string;
  behaviorLabel: string;
  modifiersLabel: string;
}): JSX.Element {
  const { behavior_shifts: behaviorShifts, ...otherModifiers } = layer.modifiers ?? {};
  return (
    <div className="border-t border-border/40 py-4 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h4 className="text-sm font-semibold text-foreground">{title || String(index + 1)}</h4>
        <span className="text-xs text-muted-foreground">{layer.layer_id}</span>
      </div>
      <div className="mt-3 space-y-4">
        <MappingField label={unlockLabel} value={layer.unlock_condition ?? undefined} />
        <ListField label={behaviorLabel} values={behaviorShifts} />
        <MappingField label={modifiersLabel} value={otherModifiers} />
      </div>
    </div>
  );
}

export function PersonaProfilePanel({ config }: PersonaProfilePanelProps): JSX.Element {
  const { t } = useTranslation('onboarding');
  const [layersRevealed, setLayersRevealed] = useState(false);
  const identity = config.identity_core;
  const voice = config.idiolect;
  const deepLayers = (config.persona_layers ?? []).filter((layer) => layer.layer_id !== 'surface');

  return (
    <div
      data-testid="persona-profile-panel"
      className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-border/55 bg-background"
    >
      <header className="border-b border-border/45 bg-muted/20 px-6 py-5">
        <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {t('personaPreview.profile.eyebrow')}
        </div>
        <h3 className="mt-2 text-xl font-semibold tracking-tight text-foreground">{config.name}</h3>
        {config.description ? (
          <p className="mt-1.5 text-sm leading-6 text-muted-foreground">{config.description}</p>
        ) : null}
      </header>

      <div className="px-6 pb-2">
        <ProfileSection title={t('personality.sections.identityCore')} defaultOpen>
          <div className="space-y-5">
            <TextField label={t('personality.fields.identityStatement')} value={identity?.identity_statement} />
            <div className="grid gap-5 md:grid-cols-3">
              <ListField label={t('personality.fields.valuesLoved')} values={identity?.values_loved} />
              <ListField label={t('personality.fields.valuesRejected')} values={identity?.values_rejected} />
              <ListField label={t('personality.fields.attentionBiases')} values={identity?.attention_biases} />
            </div>
          </div>
        </ProfileSection>

        <ProfileSection title={t('personality.sections.idiolect')} defaultOpen>
          <div className="space-y-5">
            <TextField label={t('personality.fields.sentenceStyle')} value={voice?.sentence_style} />
            <div className="grid gap-5 md:grid-cols-3">
              <ListField label={t('personality.fields.vocabAvailable')} values={voice?.vocab_available} />
              <ListField label={t('personality.fields.vocabAvoided')} values={voice?.vocab_avoided} />
              <ListField label={t('personality.fields.structuralQuirks')} values={voice?.structural_quirks} />
            </div>
          </div>
        </ProfileSection>

        <ProfileSection title={t('personality.sections.registers')}>
          {(config.registers ? REGISTER_KEYS.filter((key) => config.registers[key]) : []).map((key) => (
            <RegisterPanel
              key={key}
              name={t(`personality.registers.${key}`)}
              register={config.registers[key]}
              behaviorLabel={t('personality.fields.registerBehavior')}
              examplesLabel={t('personaPreview.profile.examples')}
            />
          ))}
        </ProfileSection>

        <ProfileSection title={t('personality.sections.signatureTriggers')}>
          {(config.signature_triggers ?? []).map((trigger, index) => (
            <TriggerPanel
              key={`${trigger.trigger_id}-${index}`}
              trigger={trigger}
              index={index}
              title={t('personality.fields.triggerCard', { index: index + 1 })}
              activatesWhenLabel={t('personality.fields.activatesWhen')}
              behaviorShiftLabel={t('personality.fields.behaviorShift')}
              exitBehaviorLabel={t('personality.fields.exitBehavior')}
              intensityLabel={t('personality.fields.intensityLevels')}
            />
          ))}
        </ProfileSection>

        <ProfileSection title={t('personality.sections.quietHours')}>
          {(config.quiet_hours ?? []).map((item, index) => (
            <QuietHourPanel
              key={`${item.condition}-${index}`}
              item={item}
              index={index}
              title={t('personality.fields.quietHourCard', { index: index + 1 })}
              conditionLabel={t('personality.fields.quietHourCondition')}
              clampsLabel={t('personality.fields.clamps')}
            />
          ))}
        </ProfileSection>

        {config.appearance_prompt ? (
          <ProfileSection title={t('personality.sections.appearance')}>
            <TextField
              label={t('personality.fields.appearancePrompt')}
              value={config.appearance_prompt}
            />
          </ProfileSection>
        ) : null}

        {deepLayers.length > 0 ? (
          <ProfileSection title={t('personality.sections.personaLayers')}>
            {layersRevealed ? (
              deepLayers.map((layer, index) => (
                <LayerPanel
                  key={`${layer.layer_id}-${index}`}
                  layer={layer}
                  index={index}
                  title={t('personality.fields.layerCard', { index: index + 1 })}
                  unlockLabel={t('personality.fields.unlockCondition')}
                  behaviorLabel={t('personality.fields.behaviorHints')}
                  modifiersLabel={t('personality.fields.layerModifiers')}
                />
              ))
            ) : (
              <div className="flex flex-col items-start gap-3 rounded-lg bg-muted/35 p-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-3">
                  <Eye className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                  <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
                    {t('personality.actions.viewLayersConfirm')}
                  </p>
                </div>
                <button
                  type="button"
                  data-testid="persona-profile-reveal-layers"
                  className="shrink-0 rounded-md border border-border bg-background px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
                  onClick={() => setLayersRevealed(true)}
                >
                  {t('personality.actions.viewLayersReveal')}
                </button>
              </div>
            )}
          </ProfileSection>
        ) : null}
      </div>
    </div>
  );
}
