import React from 'react';
import { useTranslation } from 'react-i18next';
import { MessageSquare, Activity, BookOpen, Clock } from 'lucide-react';
import { motion, useReducedMotion } from 'framer-motion';
import { cn } from '@/lib/utils';

export type ScenarioId = 'chat_assistant' | 'life_monitor' | 'knowledge_partner' | 'default';

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

const scenarios: ScenarioOption[] = [
  { id: 'chat_assistant', icon: MessageSquare, labelKey: 'scenario.chatAssistant', descKey: 'scenario.chatAssistantDesc' },
  { id: 'life_monitor', icon: Activity, labelKey: 'scenario.lifeMonitor', descKey: 'scenario.lifeMonitorDesc' },
  { id: 'knowledge_partner', icon: BookOpen, labelKey: 'scenario.knowledgePartner', descKey: 'scenario.knowledgePartnerDesc' },
  { id: 'default', icon: Clock, labelKey: 'scenario.decideLater', descKey: 'scenario.decideLaterDesc' },
];

export const ScenarioSelection: React.FC<ScenarioSelectionProps> = ({ value, onChange }) => {
  const { t } = useTranslation('onboarding');
  const shouldReduceMotion = useReducedMotion();

  return (
    <div className="space-y-6">
      <div>
        <h3 className="mb-1 text-base font-medium">{t('scenario.title')}</h3>
        <p className="mb-4 text-sm text-muted-foreground">{t('scenario.description')}</p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {scenarios.map((scenario) => {
          const Icon = scenario.icon;
          const selected = value === scenario.id;

          return (
            <motion.div
              key={scenario.id}
              whileHover={shouldReduceMotion ? undefined : { y: -2 }}
              transition={{ duration: shouldReduceMotion ? 0 : 0.15 }}
            >
              <button
                type="button"
                onClick={() => onChange(scenario.id)}
                aria-pressed={selected}
                className={cn(
                  'flex w-full flex-col rounded-xl border bg-background p-5 text-left transition',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
                  selected
                    ? 'border-primary bg-primary/5 shadow-sm'
                    : 'border-border hover:border-primary/40'
                )}
              >
                <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="h-5 w-5" />
                </div>
                <div className="text-base font-semibold">{t(scenario.labelKey)}</div>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                  {t(scenario.descKey)}
                </p>
              </button>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
};

export default ScenarioSelection;
