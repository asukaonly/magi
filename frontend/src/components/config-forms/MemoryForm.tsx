import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { SwitchField } from './fields';
import { cn } from '@/lib/utils';

const NumberInput: React.FC<{
  value?: number;
  min?: number;
  max?: number;
  defaultValue?: number;
  onChange?: (value: number) => void;
  disabled?: boolean;
}> = ({ value, min, max, defaultValue, onChange, disabled = false }) => (
  <input
    className={cn(
      'h-10 w-full rounded-md border border-input bg-background px-3 text-sm',
      'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/60',
      disabled && 'cursor-not-allowed opacity-50'
    )}
    type="number"
    min={min}
    max={max}
    value={value ?? defaultValue ?? ''}
    disabled={disabled}
    onChange={(event) => {
      const val = event.target.value ? Number(event.target.value) : (defaultValue ?? 0);
      onChange?.(val);
    }}
  />
);

interface ExpandableMemoryLayerCardProps {
  layerKey: string;
  label: string;
  description: string;
  checked: boolean;
  disabled?: boolean;
  expanded: boolean;
  onToggle: (checked: boolean) => void;
  onExpand: (expanded: boolean) => void;
  children?: React.ReactNode;
}

const ExpandableMemoryLayerCard: React.FC<ExpandableMemoryLayerCardProps> = ({
  label,
  description,
  checked,
  disabled = false,
  expanded,
  onToggle,
  onExpand,
  children,
}) => {
  const handleHeaderClick = () => {
    if (disabled) return;
    if (checked) {
      onExpand(!expanded);
    }
  };

  return (
    <div
      className={cn(
        'rounded-xl border transition-all duration-200',
        checked ? 'border-primary/40 bg-primary/5' : 'border-border/60 bg-background/60',
        disabled && 'opacity-60'
      )}
    >
      {/* Header row with toggle */}
      <div className="flex items-center gap-3 px-4 py-3">
        <SwitchField
          checked={checked}
          disabled={disabled}
          onChange={onToggle}
          ariaLabel={label}
        />
        <div
          className={cn('flex-1', !disabled && 'cursor-pointer')}
          onClick={handleHeaderClick}
        >
          <div className="flex items-center justify-between">
            <div>
              <div className={cn('text-sm font-medium', checked && 'text-primary')}>
                {label}
              </div>
              <div className="text-xs leading-5 text-muted-foreground">{description}</div>
            </div>
            {checked && children && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onExpand(!expanded);
                }}
                className="rounded p-1 hover:bg-muted/50"
              >
                {expanded ? (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                )}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Expandable content */}
      {checked && expanded && children && (
        <div className="border-t border-border/40 px-4 py-3">
          <div className="space-y-4">{children}</div>
        </div>
      )}
    </div>
  );
};

const FieldLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="text-xs font-medium text-muted-foreground">{children}</span>
);

export const MemoryForm: React.FC = () => {
  const { t } = useTranslation('app');
  const [expandedLayers, setExpandedLayers] = useState<Set<string>>(new Set());

  const toggleExpand = (layer: string) => {
    setExpandedLayers((prev) => {
      const next = new Set(prev);
      if (next.has(layer)) {
        next.delete(layer);
      } else {
        next.add(layer);
      }
      return next;
    });
  };

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
        const llm = getFieldValue(['llm']) || {};
        const l1Enabled = memory.enable_l1 !== false;
        const l0Enabled = memory.enable_l0 !== false;
        const l2Enabled = l1Enabled && memory.enable_l2 !== false;
        const l3Enabled = l1Enabled && memory.enable_l3 !== false;
        const l4Enabled = l1Enabled && memory.enable_l4 !== false;

        // Check if embedding model is configured
        const embeddingSelection = llm?.selections?.embedding;
        const hasEmbeddingModel = !!(embeddingSelection?.provider_id && embeddingSelection?.model);

        const patchMemory = (updates: Record<string, any>) => {
          setFieldValue(['memory'], {
            ...memory,
            ...updates,
          });
        };

        const handleLayerToggle = (layer: 'enable_l0' | 'enable_l1' | 'enable_l2' | 'enable_l3' | 'enable_l4', checked: boolean) => {
          // When disabling a layer, collapse it
          if (!checked) {
            const layerKey = layer.replace('enable_', '');
            setExpandedLayers((prev) => {
              const next = new Set(prev);
              next.delete(layerKey);
              return next;
            });
          }

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
            // Collapse all downstream layers
            setExpandedLayers(new Set());
            return;
          }

          if (layer === 'enable_l2' && !checked) {
            patchMemory({ enable_l2: false, enable_l2_llm_extraction: false });
            return;
          }

          if (layer === 'enable_l3' && !checked) {
            patchMemory({ enable_l3: false, enable_l3_llm_summary: false });
            return
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
              {/* L0 Working Context */}
              <ExpandableMemoryLayerCard
                layerKey="l0"
                label={t('settings.memory.fields.enable_l0.label')}
                description={t('settings.memory.fields.enable_l0.description')}
                checked={l0Enabled}
                expanded={expandedLayers.has('l0')}
                onToggle={(checked) => handleLayerToggle('enable_l0', checked)}
                onExpand={() => toggleExpand('l0')}
              >
                <div className="space-y-3">
                  <div>
                    <FieldLabel>{t('settings.memory.fields.l0_checkpoint_interval_seconds.label')}</FieldLabel>
                    <Form.Item name={['memory', 'l0_checkpoint_interval_seconds']} noStyle>
                      <NumberInput min={1} defaultValue={60} />
                    </Form.Item>
                  </div>

                  <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                    <div className="space-y-0.5">
                      <div className="text-xs font-medium">{t('settings.memory.fields.runtime_replay_include_l0_only.label')}</div>
                      <div className="text-[11px] leading-4 text-muted-foreground">{t('settings.memory.fields.runtime_replay_include_l0_only.description')}</div>
                    </div>
                    <SwitchField
                      checked={memory.runtime_replay_include_l0_only !== false}
                      onChange={(checked) => patchMemory({ runtime_replay_include_l0_only: checked })}
                      ariaLabel={t('settings.memory.fields.runtime_replay_include_l0_only.label')}
                    />
                  </label>
                </div>
              </ExpandableMemoryLayerCard>

              {/* L1 Event Memory */}
              <ExpandableMemoryLayerCard
                layerKey="l1"
                label={t('settings.memory.fields.enable_l1.label')}
                description={t('settings.memory.fields.enable_l1.description')}
                checked={l1Enabled}
                expanded={expandedLayers.has('l1')}
                onToggle={(checked) => handleLayerToggle('enable_l1', checked)}
                onExpand={() => toggleExpand('l1')}
              >
                <div className="space-y-3">
                  <div>
                    <FieldLabel>{t('settings.memory.fields.retention_days.label')}</FieldLabel>
                    <Form.Item name={['memory', 'retention_days']} noStyle>
                      <NumberInput min={1} defaultValue={30} />
                    </Form.Item>
                  </div>

                  <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                    <div className="space-y-0.5">
                      <div className="text-xs font-medium">{t('settings.memory.fields.enable_t1_importance.label')}</div>
                      <div className="text-[11px] leading-4 text-muted-foreground">{t('settings.memory.fields.enable_t1_importance.description')}</div>
                    </div>
                    <SwitchField
                      checked={memory.enable_t1_importance !== false}
                      onChange={(checked) => patchMemory({ enable_t1_importance: checked })}
                      ariaLabel={t('settings.memory.fields.enable_t1_importance.label')}
                    />
                  </label>

                  <label className={cn(
                    "flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5",
                    !hasEmbeddingModel && "opacity-50"
                  )}>
                    <div className="space-y-0.5">
                      <div className="text-xs font-medium">{t('settings.memory.fields.enable_l1_vectorization.label')}</div>
                      <div className="text-[11px] leading-4 text-muted-foreground">
                        {hasEmbeddingModel
                          ? t('settings.memory.fields.enable_l1_vectorization.description')
                          : t('settings.memory.fields.enable_l1_vectorization.description_disabled')}
                      </div>
                    </div>
                    <SwitchField
                      checked={memory.enable_l1_vectorization === true}
                      disabled={!hasEmbeddingModel}
                      onChange={(checked) => patchMemory({ enable_l1_vectorization: checked })}
                      ariaLabel={t('settings.memory.fields.enable_l1_vectorization.label')}
                    />
                  </label>
                </div>
              </ExpandableMemoryLayerCard>

              {/* L2 Cognition Graph */}
              <ExpandableMemoryLayerCard
                layerKey="l2"
                label={t('settings.memory.fields.enable_l2.label')}
                description={t('settings.memory.fields.enable_l2.description')}
                checked={l2Enabled}
                disabled={!l1Enabled}
                expanded={expandedLayers.has('l2')}
                onToggle={(checked) => handleLayerToggle('enable_l2', checked)}
                onExpand={() => toggleExpand('l2')}
              >
                <div className="space-y-3">
                  <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                    <div className="space-y-0.5">
                      <div className="text-xs font-medium">{t('settings.memory.fields.enable_l2_llm_extraction.label')}</div>
                      <div className="text-[11px] leading-4 text-muted-foreground">{t('settings.memory.fields.enable_l2_llm_extraction.description')}</div>
                    </div>
                    <SwitchField
                      checked={memory.enable_l2_llm_extraction !== false}
                      disabled={!l2Enabled}
                      onChange={(checked) => patchMemory({ enable_l2_llm_extraction: checked })}
                      ariaLabel={t('settings.memory.fields.enable_l2_llm_extraction.label')}
                    />
                  </label>

                  <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                    <div className="space-y-0.5">
                      <div className="text-xs font-medium">{t('settings.memory.fields.enable_l2_conflict_arbitration.label')}</div>
                      <div className="text-[11px] leading-4 text-muted-foreground">{t('settings.memory.fields.enable_l2_conflict_arbitration.description')}</div>
                    </div>
                    <SwitchField
                      checked={memory.enable_l2_conflict_arbitration !== false}
                      disabled={!l2Enabled}
                      onChange={(checked) => patchMemory({ enable_l2_conflict_arbitration: checked })}
                      ariaLabel={t('settings.memory.fields.enable_l2_conflict_arbitration.label')}
                    />
                  </label>
                </div>
              </ExpandableMemoryLayerCard>

              {/* L3 Reflection */}
              <ExpandableMemoryLayerCard
                layerKey="l3"
                label={t('settings.memory.fields.enable_l3.label')}
                description={t('settings.memory.fields.enable_l3.description')}
                checked={l3Enabled}
                disabled={!l1Enabled}
                expanded={expandedLayers.has('l3')}
                onToggle={(checked) => handleLayerToggle('enable_l3', checked)}
                onExpand={() => toggleExpand('l3')}
              >
                <div className="space-y-3">
                  <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                    <div className="space-y-0.5">
                      <div className="text-xs font-medium">{t('settings.memory.fields.enable_l3_llm_summary.label')}</div>
                      <div className="text-[11px] leading-4 text-muted-foreground">{t('settings.memory.fields.enable_l3_llm_summary.description')}</div>
                    </div>
                    <SwitchField
                      checked={memory.enable_l3_llm_summary !== false}
                      disabled={!l3Enabled}
                      onChange={(checked) => patchMemory({ enable_l3_llm_summary: checked })}
                      ariaLabel={t('settings.memory.fields.enable_l3_llm_summary.label')}
                    />
                  </label>

                  <label className={cn(
                    "flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5",
                    !hasEmbeddingModel && "opacity-50"
                  )}>
                    <div className="space-y-0.5">
                      <div className="text-xs font-medium">{t('settings.memory.fields.enable_l3_vectorization.label')}</div>
                      <div className="text-[11px] leading-4 text-muted-foreground">
                        {hasEmbeddingModel
                          ? t('settings.memory.fields.enable_l3_vectorization.description')
                          : t('settings.memory.fields.enable_l3_vectorization.description_disabled')}
                      </div>
                    </div>
                    <SwitchField
                      checked={memory.enable_l3_vectorization === true}
                      disabled={!l3Enabled || !hasEmbeddingModel}
                      onChange={(checked) => patchMemory({ enable_l3_vectorization: checked })}
                      ariaLabel={t('settings.memory.fields.enable_l3_vectorization.label')}
                    />
                  </label>
                </div>
              </ExpandableMemoryLayerCard>

              {/* L4 Procedural Memory */}
              <ExpandableMemoryLayerCard
                layerKey="l4"
                label={t('settings.memory.fields.enable_l4.label')}
                description={t('settings.memory.fields.enable_l4.description')}
                checked={l4Enabled}
                disabled={!l1Enabled}
                expanded={expandedLayers.has('l4')}
                onToggle={(checked) => handleLayerToggle('enable_l4', checked)}
                onExpand={() => toggleExpand('l4')}
              >
                <label className="flex items-start justify-between gap-4 rounded-lg border border-border/40 bg-background/50 px-3 py-2.5">
                  <div className="space-y-0.5">
                    <div className="text-xs font-medium">{t('settings.memory.fields.enable_l4_skill_extraction.label')}</div>
                    <div className="text-[11px] leading-4 text-muted-foreground">{t('settings.memory.fields.enable_l4_skill_extraction.description')}</div>
                  </div>
                  <SwitchField
                    checked={memory.enable_l4_skill_extraction !== false}
                    disabled={!l4Enabled}
                    onChange={(checked) => patchMemory({ enable_l4_skill_extraction: checked })}
                    ariaLabel={t('settings.memory.fields.enable_l4_skill_extraction.label')}
                  />
                </label>
              </ExpandableMemoryLayerCard>
            </div>

            {!l1Enabled ? (
              <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                <div className="font-medium">{t('settings.memory.form.l1DependencyTitle')}</div>
                <div className="mt-1 text-amber-800">{t('settings.memory.form.l1DependencyDescription')}</div>
                <button
                  type="button"
                  className="mt-3 rounded-lg border border-amber-300 bg-amber-100 px-3 py-1.5 text-xs font-medium text-amber-900 hover:bg-amber-200"
                  onClick={() => handleLayerToggle('enable_l1', true)}
                >
                  {t('settings.memory.form.restoreL1')}
                </button>
              </div>
            ) : null}
          </div>
        );
      }}
    </Form.Item>
  );
};

export default MemoryForm;
