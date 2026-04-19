import React from 'react';
import { useTranslation } from 'react-i18next';
import { Lightbulb, BookOpen, GraduationCap } from 'lucide-react';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { cn } from '@/lib/utils';

interface MemoryLayerDef {
  layer: 'l2' | 'l3' | 'l4';
  icon: React.ElementType;
  labelKey: string;
  descKey: string;
}

const layerDefs: MemoryLayerDef[] = [
  { layer: 'l2', icon: Lightbulb, labelKey: 'settings.memory.fields.enable_l2.label', descKey: 'settings.memory.fields.enable_l2.description' },
  { layer: 'l3', icon: BookOpen, labelKey: 'settings.memory.fields.enable_l3.label', descKey: 'settings.memory.fields.enable_l3.description' },
  { layer: 'l4', icon: GraduationCap, labelKey: 'settings.memory.fields.enable_l4.label', descKey: 'settings.memory.fields.enable_l4.description' },
];

export const MemoryForm: React.FC = () => {
  const { t } = useTranslation('app');

  return (
    <Form.Item noStyle shouldUpdate>
      {({
        getFieldValue,
        setFieldValue,
      }: {
        getFieldValue: (name: any) => any;
        setFieldValue: (name: any, value: any) => void;
      }) => {
        const memory = getFieldValue(['memory']) || {};
        const l1Enabled = (memory.l1 || {}).enabled !== false;

        const isLayerEnabled = (layer: 'l2' | 'l3' | 'l4') =>
          l1Enabled && (memory[layer] || {}).enabled !== false;

        const handleLayerToggle = (layer: 'l2' | 'l3' | 'l4') => {
          const current = isLayerEnabled(layer);
          setFieldValue(['memory'], {
            ...memory,
            [layer]: {
              ...(memory[layer] || {}),
              enabled: !current,
            },
          });
        };

        return (
          <div className="space-y-6">
            <div>
              <h3 className="mb-1 text-base font-medium">{t('settings.memory.form.title')}</h3>
              <p className="mb-1 text-sm text-muted-foreground">{t('settings.memory.form.description')}</p>
              <p className="text-xs text-muted-foreground/70">{t('settings.memory.form.onboardingHint')}</p>
            </div>

            <div className="space-y-3">
              {layerDefs.map((def) => {
                const enabled = isLayerEnabled(def.layer);
                const Icon = def.icon;
                return (
                  <div
                    key={def.layer}
                    className={cn(
                      'flex items-center gap-4 rounded-xl border p-4 transition',
                      enabled ? 'border-primary/30 bg-primary/5' : 'border-border bg-background'
                    )}
                  >
                    <div
                      className={cn(
                        'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg',
                        enabled ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'
                      )}
                    >
                      <Icon className="h-5 w-5" />
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="text-sm font-medium">{t(def.labelKey)}</div>
                      <div className="text-xs text-muted-foreground">{t(def.descKey)}</div>
                    </div>

                    <button
                      type="button"
                      role="switch"
                      aria-checked={enabled}
                      aria-label={t(def.labelKey)}
                      onClick={() => handleLayerToggle(def.layer)}
                      className={cn(
                        'relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors',
                        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
                        enabled ? 'bg-primary' : 'bg-muted'
                      )}
                    >
                      <span
                        className={cn(
                          'pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-sm transition-transform',
                          enabled ? 'translate-x-5' : 'translate-x-0.5'
                        )}
                      />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        );
      }}
    </Form.Item>
  );
};

export default MemoryForm;
