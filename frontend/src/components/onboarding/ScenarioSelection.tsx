import React from 'react';
import { useTranslation } from 'react-i18next';
import { MessageSquare, Activity, BookOpen, Clock, Check, X } from 'lucide-react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { cn } from '@/lib/utils';

export type ScenarioId = 'chat_assistant' | 'life_monitor' | 'knowledge_partner' | 'default';

/** Whether a scenario should show the sensor selection step. */
export const SCENARIO_NEEDS_SENSORS: Record<ScenarioId, boolean> = {
  chat_assistant: false,
  life_monitor: true,
  knowledge_partner: true,
  default: false,
};

interface ScenarioSelectionProps {
  value: ScenarioId | null;
  onChange: (scenario: ScenarioId) => void;
}

interface ScenarioOption {
  id: ScenarioId;
  icon: React.ElementType;
  labelKey: string;
  descKey: string;
}

interface FeatureItem {
  labelKey: string;
  enabled: boolean;
}

interface ScenarioPersonalityMeta {
  nameKey: string;
  descKey: string;
}

const scenarios: ScenarioOption[] = [
  { id: 'chat_assistant', icon: MessageSquare, labelKey: 'scenario.chatAssistant', descKey: 'scenario.chatAssistantDesc' },
  { id: 'life_monitor', icon: Activity, labelKey: 'scenario.lifeMonitor', descKey: 'scenario.lifeMonitorDesc' },
  { id: 'knowledge_partner', icon: BookOpen, labelKey: 'scenario.knowledgePartner', descKey: 'scenario.knowledgePartnerDesc' },
  { id: 'default', icon: Clock, labelKey: 'scenario.decideLater', descKey: 'scenario.decideLaterDesc' },
];

const SCENARIO_FEATURES: Record<ScenarioId, FeatureItem[]> = {
  chat_assistant: [
    { labelKey: 'scenario.features.conversation', enabled: true },
    { labelKey: 'scenario.features.shortTermMemory', enabled: true },
    { labelKey: 'scenario.features.webTools', enabled: true },
    { labelKey: 'scenario.features.knowledgeExtraction', enabled: false },
    { labelKey: 'scenario.features.temporalSummary', enabled: false },
    { labelKey: 'scenario.features.sensors', enabled: false },
  ],
  life_monitor: [
    { labelKey: 'scenario.features.conversation', enabled: true },
    { labelKey: 'scenario.features.shortTermMemory', enabled: true },
    { labelKey: 'scenario.features.webTools', enabled: true },
    { labelKey: 'scenario.features.knowledgeExtraction', enabled: true },
    { labelKey: 'scenario.features.temporalSummary', enabled: true },
    { labelKey: 'scenario.features.sensors', enabled: true },
  ],
  knowledge_partner: [
    { labelKey: 'scenario.features.conversation', enabled: true },
    { labelKey: 'scenario.features.shortTermMemory', enabled: true },
    { labelKey: 'scenario.features.webTools', enabled: true },
    { labelKey: 'scenario.features.knowledgeExtraction', enabled: true },
    { labelKey: 'scenario.features.temporalSummary', enabled: true },
    { labelKey: 'scenario.features.skillLearning', enabled: true },
    { labelKey: 'scenario.features.sensors', enabled: true },
  ],
  default: [
    { labelKey: 'scenario.features.conversation', enabled: true },
    { labelKey: 'scenario.features.shortTermMemory', enabled: true },
    { labelKey: 'scenario.features.webTools', enabled: true },
    { labelKey: 'scenario.features.knowledgeExtraction', enabled: true },
    { labelKey: 'scenario.features.temporalSummary', enabled: false },
    { labelKey: 'scenario.features.skillLearning', enabled: false },
    { labelKey: 'scenario.features.sensors', enabled: false },
  ],
};

const SCENARIO_PERSONALITIES: Record<ScenarioId, ScenarioPersonalityMeta> = {
  chat_assistant: {
    nameKey: 'scenario.personas.chatAssistant.name',
    descKey: 'scenario.personas.chatAssistant.desc',
  },
  life_monitor: {
    nameKey: 'scenario.personas.lifeMonitor.name',
    descKey: 'scenario.personas.lifeMonitor.desc',
  },
  knowledge_partner: {
    nameKey: 'scenario.personas.knowledgePartner.name',
    descKey: 'scenario.personas.knowledgePartner.desc',
  },
  default: {
    nameKey: 'scenario.personas.default.name',
    descKey: 'scenario.personas.default.desc',
  },
};

export const ScenarioSelection: React.FC<ScenarioSelectionProps> = ({ value, onChange }) => {
  const { t } = useTranslation('onboarding');
  const shouldReduceMotion = useReducedMotion();
  const features = value ? SCENARIO_FEATURES[value] : [];
  const personality = value ? SCENARIO_PERSONALITIES[value] : null;

  return (
    <div className="space-y-5">
      <div>
        <h3 className="mb-1 text-base font-medium">{t('scenario.title')}</h3>
        <p className="mb-3 text-sm text-muted-foreground">{t('scenario.description')}</p>
      </div>

      <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {scenarios.map((scenario) => {
          const Icon = scenario.icon;
          const selected = value === scenario.id;
          const personalityMeta = SCENARIO_PERSONALITIES[scenario.id];

          return (
            <motion.div
              key={scenario.id}
              className="h-full"
              whileHover={shouldReduceMotion ? undefined : { y: -1 }}
              transition={{ duration: shouldReduceMotion ? 0 : 0.15 }}
            >
              <button
                type="button"
                onClick={() => onChange(scenario.id)}
                aria-pressed={selected}
                className={cn(
                  'flex h-full w-full flex-col rounded-lg border bg-background px-3 py-3.5 text-center transition',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
                  selected
                    ? 'border-primary bg-primary/5 shadow-sm'
                    : 'border-border hover:border-primary/40'
                )}
              >
                <div className="flex flex-1 flex-col items-center">
                  <div className="mb-2 flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="text-sm font-semibold">{t(scenario.labelKey)}</div>
                  <p className="mt-0.5 text-xs leading-snug text-muted-foreground">
                    {t(scenario.descKey)}
                  </p>
                </div>
                <div className="mt-auto flex w-full justify-center pt-3">
                  <div className="inline-flex min-h-7 items-center rounded-md border border-border/70 bg-muted/55 px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
                    {t('scenario.personaBadge')}: {t(personalityMeta.nameKey)}
                  </div>
                </div>
              </button>
            </motion.div>
          );
        })}
      </div>

      {/* Feature summary panel */}
      <AnimatePresence mode="wait">
        {value && (
          <motion.div
            key={value}
            initial={shouldReduceMotion ? false : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={shouldReduceMotion ? undefined : { opacity: 0, y: 8 }}
            transition={{ duration: shouldReduceMotion ? 0 : 0.18 }}
            className="rounded-lg border border-border bg-muted/30 p-5"
          >
            {features.length > 0 ? (
              <>
                <p className="mb-3 text-sm font-medium text-foreground">
                  {value === 'default'
                    ? t('scenario.defaultFeatureSummaryTitle')
                    : t('scenario.featureSummaryTitle')}
                </p>
                <div className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
                  {features.map((f) => (
                    <div key={f.labelKey} className="flex items-center gap-2 text-sm">
                      {f.enabled ? (
                        <Check className="h-3.5 w-3.5 shrink-0 text-primary" />
                      ) : (
                        <X className="h-3.5 w-3.5 shrink-0 text-muted-foreground/50" />
                      )}
                      <span className={cn(f.enabled ? 'text-foreground' : 'text-muted-foreground/60')}>
                        {t(f.labelKey)}
                      </span>
                    </div>
                  ))}
                </div>
                {personality ? (
                  <div className="mt-4 rounded-lg border border-border/70 bg-background/80 p-3">
                    <div className="text-xs font-medium uppercase tracking-[0.08em] text-muted-foreground">
                      {t('scenario.personaSummaryTitle')}
                    </div>
                    <div className="mt-1 text-sm font-semibold text-foreground">
                      {t(personality.nameKey)}
                    </div>
                    <p className="mt-1 text-sm leading-5 text-muted-foreground">
                      {t(personality.descKey)}
                    </p>
                  </div>
                ) : null}
                {SCENARIO_NEEDS_SENSORS[value] && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    {t('scenario.sensorHint')}
                  </p>
                )}
                {value === 'default' && (
                  <p className="mt-3 text-xs text-muted-foreground">
                    {t('scenario.defaultHint')}
                  </p>
                )}
              </>
            ) : null}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ScenarioSelection;
