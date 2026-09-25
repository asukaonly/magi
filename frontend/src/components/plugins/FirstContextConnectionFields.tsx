import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import type { ActivationFlowSpec } from '@/api/modules/plugins';
import { isExtensionFieldVisible } from '@/components/config-forms/dynamic-config-specs';
import PluginSettingsFields from '@/components/settings/PluginSettingsFields';
import { Switch } from '@/components/ui/switch';
import { firstContextSyncKeys } from '@/utils/first-context-settings';

interface Props {
  flow: ActivationFlowSpec;
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}

export function FirstContextConnectionFields({ flow, values, onChange }: Props) {
  const { t } = useTranslation('onboarding');
  const id = useId();
  const [modeKey, intervalKey] = firstContextSyncKeys(flow);
  const mode = flow.fields.find(field => field.key === modeKey);
  const interval = flow.fields.find(field => field.key === intervalKey);
  const canToggle = mode?.type === 'select' && mode.options.length === 2
    && mode.options.some(option => option.value === 'manual')
    && mode.options.some(option => option.value === 'interval')
    && isExtensionFieldVisible(mode, values);
  const fields = flow.fields.filter(field => !canToggle || (field !== mode && field !== interval));
  const automatic = mode && values[mode.key] === 'interval';

  return <div className="space-y-5">
    {fields.length ? <PluginSettingsFields compact fields={fields} values={values} onChange={onChange} /> : null}
    {canToggle && mode ? <div className="space-y-3">
      <div className="flex items-center justify-between gap-6">
        <label htmlFor={id} className="cursor-pointer text-sm font-medium">{t('pluginInstallPanel.autoSync')}</label>
        <Switch id={id} checked={Boolean(automatic)} onCheckedChange={checked => onChange(mode.key, checked ? 'interval' : 'manual')} />
      </div>
      <p className="text-xs text-muted-foreground">{t(automatic ? 'pluginInstallPanel.autoSyncOn' : 'pluginInstallPanel.autoSyncOff')}</p>
      {automatic && interval && isExtensionFieldVisible(interval, values) ? <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">{t('pluginInstallPanel.syncSettings')}</summary>
        <div className="pt-4">
          <PluginSettingsFields compact fields={[{ ...interval,
            label: t('pluginInstallPanel.syncInterval'), label_translated: t('pluginInstallPanel.syncInterval'),
            description: '', description_translated: '',
          }]} values={values} onChange={onChange} />
        </div>
      </details> : null}
    </div> : null}
  </div>;
}
