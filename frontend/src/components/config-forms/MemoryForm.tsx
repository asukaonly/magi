import React from 'react';
import { useTranslation } from 'react-i18next';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { SwitchField } from './fields';
import { cn } from '@/lib/utils';


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
        const l2 = memory.l2 || {};
        const l3 = memory.l3 || {};
        const l4 = memory.l4 || {};
        const l1Enabled = (memory.l1 || {}).enabled !== false;
        const l2Enabled = l1Enabled && l2.enabled !== false;
        const l3Enabled = l1Enabled && l3.enabled !== false;
        const l4Enabled = l1Enabled && l4.enabled !== false;

        const patchMemory = (updates: Record<string, any>) => {
          setFieldValue(['memory'], {
            ...memory,
            ...updates,
          });
        };

        const patchLayer = (layer: 'l2' | 'l3' | 'l4', updates: Record<string, any>) => {
          patchMemory({
            [layer]: {
              ...(memory[layer] || {}),
              ...updates,
            },
          });
        };

        const handleLayerToggle = (layer: 'l2' | 'l3' | 'l4', checked: boolean) => {
          patchLayer(layer, { enabled: checked });
        };

        return (
          <div className="space-y-6">
            <div className="space-y-2">
              <h3 className="text-sm font-semibold">{t('settings.memory.form.title')}</h3>
              <p className="text-xs leading-5 text-muted-foreground">{t('settings.memory.form.description')}</p>
            </div>

            <div className="space-y-3">
              {/* L2 Knowledge Extraction */}
              <ExpandableMemoryLayerCard
                layerKey="l2"
                label={t('settings.memory.fields.enable_l2.label')}
                description={t('settings.memory.fields.enable_l2.description')}
                checked={l2Enabled}
                expanded={false}
                onToggle={(checked) => handleLayerToggle('l2', checked)}
                onExpand={() => {}}
              />

              {/* L3 Summary & Review */}
              <ExpandableMemoryLayerCard
                layerKey="l3"
                label={t('settings.memory.fields.enable_l3.label')}
                description={t('settings.memory.fields.enable_l3.description')}
                checked={l3Enabled}
                expanded={false}
                onToggle={(checked) => handleLayerToggle('l3', checked)}
                onExpand={() => {}}
              />

              {/* L4 Experience Learning */}
              <ExpandableMemoryLayerCard
                layerKey="l4"
                label={t('settings.memory.fields.enable_l4.label')}
                description={t('settings.memory.fields.enable_l4.description')}
                checked={l4Enabled}
                expanded={false}
                onToggle={(checked) => handleLayerToggle('l4', checked)}
                onExpand={() => {}}
              />
            </div>
          </div>
        );
      }}
    </Form.Item>
  );
};

export default MemoryForm;
