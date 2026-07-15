import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { motion, useReducedMotion } from 'framer-motion';
import { ChevronDown, Eye } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
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
  sectionId: string;
  title: string;
  children: ReactNode;
  open: boolean;
  onOpenChange: (
    sectionId: string,
    open: boolean,
    section: HTMLElement,
  ) => void;
}

function ProfileSection({
  sectionId,
  title,
  children,
  open,
  onOpenChange,
}: ProfileSectionProps): JSX.Element {
  const sectionRef = useRef<HTMLElement>(null);
  const shouldReduceMotion = useReducedMotion() ?? false;

  return (
    <section
      ref={sectionRef}
      data-testid={`persona-profile-section-${sectionId}`}
      data-state={open ? 'open' : 'closed'}
      className={cn(
        'scroll-mt-3 rounded-xl transition-[background-color,box-shadow] duration-200',
        open
          ? 'bg-background/80 shadow-[0_14px_34px_-32px_hsl(var(--foreground)/0.38)]'
          : 'bg-transparent',
      )}
    >
      <button
        type="button"
        aria-expanded={open}
        className="group flex min-h-12 w-full items-center justify-between gap-4 rounded-xl px-4 py-3.5 text-left transition-colors duration-200 hover:bg-muted/45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/20"
        onClick={() => {
          if (sectionRef.current) {
            onOpenChange(sectionId, !open, sectionRef.current);
          }
        }}
      >
        <span className="text-[0.9375rem] font-semibold text-foreground">{title}</span>
        <ChevronDown
          className={cn(
            'h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200',
            open && 'rotate-180',
          )}
          aria-hidden="true"
        />
      </button>
      {open ? (
        <motion.div
          initial={shouldReduceMotion ? false : { opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: shouldReduceMotion ? 0 : 0.22,
            ease: [0.22, 1, 0.36, 1],
          }}
          className="px-4 pb-7 pt-2"
        >
          {children}
        </motion.div>
      ) : null}
    </section>
  );
}

function TextField({ label, value }: { label: string; value?: string | null }): JSX.Element | null {
  if (!value?.trim()) return null;
  return (
    <div className="max-w-3xl">
      <div className="text-xs font-medium tracking-wide text-muted-foreground">{label}</div>
      <p className="mt-2 whitespace-pre-wrap text-[0.9375rem] leading-7 text-foreground/90">{value}</p>
    </div>
  );
}

function ListField({
  label,
  values,
  className,
}: {
  label: string;
  values?: string[];
  className?: string;
}): JSX.Element | null {
  const items = (values ?? []).map((value) => String(value).trim()).filter(Boolean);
  if (items.length === 0) return null;
  return (
    <div className={className}>
      <div className="text-xs font-medium tracking-wide text-muted-foreground">{label}</div>
      <ul className="mt-2.5 space-y-2 text-[0.9375rem] leading-7 text-foreground/90">
        {items.map((item, index) => (
          <li key={`${item}-${index}`} className="flex items-start gap-2.5">
            <span className="mt-[0.72rem] h-1 w-1 shrink-0 rounded-full bg-primary/65" aria-hidden="true" />
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
    <div className="py-5 first:pt-0 last:pb-0">
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
    <div className="py-5 first:pt-0 last:pb-0">
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
    <div className="py-5 first:pt-0 last:pb-0">
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
    <div className="py-5 first:pt-0 last:pb-0">
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
  const shouldReduceMotion = useReducedMotion() ?? false;
  const [layersRevealed, setLayersRevealed] = useState(false);
  const [openSection, setOpenSection] = useState<string | null>('identity');
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const identity = config.identity_core;
  const voice = config.idiolect;
  const registerKeys = config.registers
    ? REGISTER_KEYS.filter((key) => config.registers[key])
    : [];
  const signatureTriggers = config.signature_triggers ?? [];
  const quietHours = config.quiet_hours ?? [];
  const deepLayers = (config.persona_layers ?? []).filter((layer) => layer.layer_id !== 'surface');

  useEffect(
    () => () => {
      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }
    },
    [],
  );

  const handleSectionOpenChange = useCallback(
    (sectionId: string, open: boolean, section: HTMLElement) => {
      setOpenSection(open ? sectionId : null);
      if (!open) return;

      if (scrollFrameRef.current !== null) {
        window.cancelAnimationFrame(scrollFrameRef.current);
      }
      scrollFrameRef.current = window.requestAnimationFrame(() => {
        scrollFrameRef.current = window.requestAnimationFrame(() => {
          const container = scrollContainerRef.current;
          if (!container) return;
          const containerRect = container.getBoundingClientRect();
          const sectionRect = section.getBoundingClientRect();
          const top = Math.max(
            0,
            container.scrollTop + sectionRect.top - containerRect.top - 12,
          );
          container.scrollTo({
            top,
            behavior: shouldReduceMotion ? 'auto' : 'smooth',
          });
          scrollFrameRef.current = null;
        });
      });
    },
    [shouldReduceMotion],
  );

  return (
    <div
      ref={scrollContainerRef}
      data-testid="persona-profile-panel"
      className="min-h-0 flex-1 overflow-y-auto rounded-xl bg-muted/20"
    >
      <div className="px-7 pb-6 pt-7 sm:px-8">
        <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
          {t('personaPreview.profile.eyebrow')}
        </div>
        <h3 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">{config.name}</h3>
        {config.description ? (
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">{config.description}</p>
        ) : null}
      </div>

      <div className="space-y-1 px-4 pb-8 sm:px-5">
        <ProfileSection
          sectionId="identity"
          title={t('personality.sections.identityCore')}
          open={openSection === 'identity'}
          onOpenChange={handleSectionOpenChange}
        >
          <div className="space-y-7">
            <TextField label={t('personality.fields.identityStatement')} value={identity?.identity_statement} />
            <div className="grid gap-x-10 gap-y-7 lg:grid-cols-2">
              <ListField label={t('personality.fields.valuesLoved')} values={identity?.values_loved} />
              <ListField label={t('personality.fields.valuesRejected')} values={identity?.values_rejected} />
              <ListField
                className="lg:col-span-2"
                label={t('personality.fields.attentionBiases')}
                values={identity?.attention_biases}
              />
            </div>
          </div>
        </ProfileSection>

        <ProfileSection
          sectionId="voice"
          title={t('personality.sections.idiolect')}
          open={openSection === 'voice'}
          onOpenChange={handleSectionOpenChange}
        >
          <div className="space-y-7">
            <TextField label={t('personality.fields.sentenceStyle')} value={voice?.sentence_style} />
            <div className="grid gap-x-10 gap-y-7 lg:grid-cols-2">
              <ListField label={t('personality.fields.vocabAvailable')} values={voice?.vocab_available} />
              <ListField label={t('personality.fields.vocabAvoided')} values={voice?.vocab_avoided} />
              <ListField
                className="lg:col-span-2"
                label={t('personality.fields.structuralQuirks')}
                values={voice?.structural_quirks}
              />
            </div>
          </div>
        </ProfileSection>

        {registerKeys.length > 0 ? (
          <ProfileSection
            sectionId="registers"
            title={t('personality.sections.registers')}
            open={openSection === 'registers'}
            onOpenChange={handleSectionOpenChange}
          >
            {registerKeys.map((key) => (
              <RegisterPanel
                key={key}
                name={t(`personality.registers.${key}`)}
                register={config.registers[key]}
                behaviorLabel={t('personality.fields.registerBehavior')}
                examplesLabel={t('personaPreview.profile.examples')}
              />
            ))}
          </ProfileSection>
        ) : null}

        {signatureTriggers.length > 0 ? (
          <ProfileSection
            sectionId="triggers"
            title={t('personality.sections.signatureTriggers')}
            open={openSection === 'triggers'}
            onOpenChange={handleSectionOpenChange}
          >
            {signatureTriggers.map((trigger, index) => (
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
        ) : null}

        {quietHours.length > 0 ? (
          <ProfileSection
            sectionId="quiet-hours"
            title={t('personality.sections.quietHours')}
            open={openSection === 'quiet-hours'}
            onOpenChange={handleSectionOpenChange}
          >
            {quietHours.map((item, index) => (
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
        ) : null}

        {config.appearance_prompt ? (
          <ProfileSection
            sectionId="appearance"
            title={t('personality.sections.appearance')}
            open={openSection === 'appearance'}
            onOpenChange={handleSectionOpenChange}
          >
            <TextField
              label={t('personality.fields.appearancePrompt')}
              value={config.appearance_prompt}
            />
          </ProfileSection>
        ) : null}

        {deepLayers.length > 0 ? (
          <ProfileSection
            sectionId="layers"
            title={t('personality.sections.personaLayers')}
            open={openSection === 'layers'}
            onOpenChange={handleSectionOpenChange}
          >
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
