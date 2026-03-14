import React from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { SwitchField } from './fields';

const NumberInput: React.FC<{
  value?: number;
  min?: number;
  onChange?: (value: number) => void;
  disabled?: boolean;
}> = ({ value, min, onChange, disabled = false }) => (
  <input
    className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60 disabled:cursor-not-allowed disabled:opacity-50"
    type="number"
    min={min}
    value={value ?? ''}
    disabled={disabled}
    onChange={(event) => onChange?.(Number(event.target.value))}
  />
);

const ToggleField: React.FC<{
  label: string;
  description: string;
  checked?: boolean;
  disabled?: boolean;
  onChange?: (checked: boolean) => void;
}> = ({ label, description, checked, disabled, onChange }) => (
  <div className="rounded-xl border border-border/60 bg-background/60 px-4 py-3">
    <div className="flex items-start justify-between gap-4">
      <div className="space-y-1">
        <div className="text-sm font-medium">{label}</div>
        <div className="text-xs leading-5 text-muted-foreground">{description}</div>
      </div>
      <SwitchField checked={checked} disabled={disabled} onChange={onChange} ariaLabel={label} />
    </div>
  </div>
);

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
        const l1Enabled = memory.enable_l1 !== false;
        const l0Enabled = memory.enable_l0 !== false;
        const l2Enabled = l1Enabled && memory.enable_l2 !== false;
        const l3Enabled = l1Enabled && memory.enable_l3 !== false;
        const l4Enabled = l1Enabled && memory.enable_l4 !== false;

        const patchMemory = (updates: Record<string, any>) => {
          setFieldValue(['memory'], {
            ...memory,
            ...updates,
          });
        };

        const handleLayerToggle = (layer: 'enable_l0' | 'enable_l1' | 'enable_l2' | 'enable_l3' | 'enable_l4', checked: boolean) => {
          if (layer === 'enable_l1' && !checked) {
            patchMemory({
              enable_l1: false,
              enable_l2: false,
              enable_l3: false,
              enable_l4: false,
              enable_t1_importance: false,
              enable_l2_llm_extraction: false,
              enable_l3_llm_summary: false,
              enable_l4_skill_extraction: false,
            });
            return;
          }

          if (layer === 'enable_l2' && !checked) {
            patchMemory({ enable_l2: false, enable_l2_llm_extraction: false });
            return;
          }

          if (layer === 'enable_l3' && !checked) {
            patchMemory({ enable_l3: false, enable_l3_llm_summary: false });
            return;
          }

          if (layer === 'enable_l4' && !checked) {
            patchMemory({ enable_l4: false, enable_l4_skill_extraction: false });
            return;
          }

          patchMemory({ [layer]: checked });
        };

        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <h3 className="text-sm font-semibold">{t('settings.memory.form.title')}</h3>
              <p className="text-xs leading-5 text-muted-foreground">{t('settings.memory.form.description')}</p>
            </div>

            <div className="space-y-3">
              <ToggleField
                label={t('settings.memory.fields.enable_l0.label')}
                description={t('settings.memory.fields.enable_l0.description')}
                checked={l0Enabled}
                onChange={(checked) => handleLayerToggle('enable_l0', checked)}
              />
              <ToggleField
                label={t('settings.memory.fields.enable_l1.label')}
                description={t('settings.memory.fields.enable_l1.description')}
                checked={l1Enabled}
                onChange={(checked) => handleLayerToggle('enable_l1', checked)}
              />
              <ToggleField
                label={t('settings.memory.fields.enable_l2.label')}
                description={t('settings.memory.fields.enable_l2.description')}
                checked={l2Enabled}
                disabled={!l1Enabled}
                onChange={(checked) => handleLayerToggle('enable_l2', checked)}
              />
              <ToggleField
                label={t('settings.memory.fields.enable_l3.label')}
                description={t('settings.memory.fields.enable_l3.description')}
                checked={l3Enabled}
                disabled={!l1Enabled}
                onChange={(checked) => handleLayerToggle('enable_l3', checked)}
              />
              <ToggleField
                label={t('settings.memory.fields.enable_l4.label')}
                description={t('settings.memory.fields.enable_l4.description')}
                checked={l4Enabled}
                disabled={!l1Enabled}
                onChange={(checked) => handleLayerToggle('enable_l4', checked)}
              />
            </div>

            {!l1Enabled ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                <div className="font-medium">{t('settings.memory.form.l1DependencyTitle')}</div>
                <div className="mt-1 text-amber-800">{t('settings.memory.form.l1DependencyDescription')}</div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="mt-3"
                  onClick={() => handleLayerToggle('enable_l1', true)}
                >
                  {t('settings.memory.form.restoreL1')}
                </Button>
              </div>
            ) : null}

            <div className="grid gap-4 md:grid-cols-2">
              <Form.Item label={t('settings.memory.fields.l0_checkpoint_interval_seconds.label')} name={['memory', 'l0_checkpoint_interval_seconds']}>
                <NumberInput min={1} disabled={!l0Enabled} />
              </Form.Item>
              <Form.Item label={t('settings.memory.fields.retention_days.label')} name={['memory', 'retention_days']}>
                <NumberInput min={1} disabled={!l1Enabled} />
              </Form.Item>
            </div>

            <div className="space-y-3">
              <ToggleField
                label={t('settings.memory.fields.runtime_replay_include_l0_only.label')}
                description={t('settings.memory.fields.runtime_replay_include_l0_only.description')}
                checked={memory.runtime_replay_include_l0_only !== false}
                disabled={!l0Enabled}
                onChange={(checked) => patchMemory({ runtime_replay_include_l0_only: checked })}
              />
              <ToggleField
                label={t('settings.memory.fields.enable_t1_importance.label')}
                description={t('settings.memory.fields.enable_t1_importance.description')}
                checked={memory.enable_t1_importance !== false}
                disabled={!l1Enabled}
                onChange={(checked) => patchMemory({ enable_t1_importance: checked })}
              />
              <ToggleField
                label={t('settings.memory.fields.enable_l2_llm_extraction.label')}
                description={t('settings.memory.fields.enable_l2_llm_extraction.description')}
                checked={memory.enable_l2_llm_extraction !== false}
                disabled={!l2Enabled}
                onChange={(checked) => patchMemory({ enable_l2_llm_extraction: checked })}
              />
              <ToggleField
                label={t('settings.memory.fields.enable_l3_llm_summary.label')}
                description={t('settings.memory.fields.enable_l3_llm_summary.description')}
                checked={memory.enable_l3_llm_summary !== false}
                disabled={!l3Enabled}
                onChange={(checked) => patchMemory({ enable_l3_llm_summary: checked })}
              />
              <ToggleField
                label={t('settings.memory.fields.enable_l4_skill_extraction.label')}
                description={t('settings.memory.fields.enable_l4_skill_extraction.description')}
                checked={memory.enable_l4_skill_extraction !== false}
                disabled={!l4Enabled}
                onChange={(checked) => patchMemory({ enable_l4_skill_extraction: checked })}
              />
            </div>
          </div>
        );
      }}
    </Form.Item>
  );
};

export default MemoryForm;
