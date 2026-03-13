import React from 'react';
import { useTranslation } from 'react-i18next';

import { DynamicConfigField } from '@/components/config-forms/DynamicToolConfig';
import type { ExtensionFieldSpec } from '@/api/modules/plugins';

type TFunction = (key: string) => string;

/**
 * Helper function to get plugin-specific translation with fallback
 */
const getPluginTranslation = (
  t: TFunction,
  pluginId: string,
  key: string,
  fallback: string
): string => {
  const translationKey = `settings.plugins.${pluginId}.${key}`;
  const translated = t(translationKey);
  // If translation doesn't exist, i18next returns the key itself
  return translated === translationKey ? fallback : translated;
};

/**
 * Helper function to get translated section title with fallback
 */
const getSectionTitle = (
  section: string,
  t: TFunction,
  pluginId: string | undefined
): string => {
  if (!pluginId) {
    return section.replace(/_/g, ' ');
  }
  return getPluginTranslation(t, pluginId, `sections.${section}`, section.replace(/_/g, ' '));
};

/**
 * Helper function to get translated option label with fallback
 */
const getOptionLabel = (
  optionValue: string,
  fieldKey: string,
  t: TFunction,
  pluginId: string | undefined,
  originalLabel: string
): string => {
  if (!pluginId) {
    return originalLabel;
  }
  return getPluginTranslation(t, pluginId, `options.${fieldKey}.${optionValue}`, originalLabel);
};

interface PluginSettingsFieldsProps {
  fields: ExtensionFieldSpec[];
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
  disabled?: boolean;
  pluginId?: string;
}

const sortFields = (fields: ExtensionFieldSpec[]) =>
  [...fields].sort((left, right) => {
    const sectionOrder = ['general', 'storage', 'analysis', 'notifications', 'delivery'];
    const leftSection = left.section || 'general';
    const rightSection = right.section || 'general';
    const leftIndex = sectionOrder.indexOf(leftSection);
    const rightIndex = sectionOrder.indexOf(rightSection);
    if (leftSection !== rightSection) {
      if (leftIndex !== -1 || rightIndex !== -1) {
        return (leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex) - (rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex);
      }
      return leftSection.localeCompare(rightSection);
    }
    return left.order - right.order;
  });

const isFieldVisible = (field: ExtensionFieldSpec, values: Record<string, any>) => {
  if (!field.depends_on_key || !field.depends_on_values?.length) {
    return true;
  }
  return field.depends_on_values.includes(String(values[field.depends_on_key] ?? ''));
};

export const PluginSettingsFields: React.FC<PluginSettingsFieldsProps> = ({
  fields,
  values,
  onChange,
  disabled = false,
  pluginId,
}) => {
  const { t } = useTranslation('app');

  const grouped = sortFields(fields).reduce<Record<string, ExtensionFieldSpec[]>>((acc, field) => {
    if (!isFieldVisible(field, values)) {
      return acc;
    }
    const section = field.section || 'general';
    acc[section] = acc[section] || [];
    acc[section].push(field);
    return acc;
  }, {});

  return (
    <div className="space-y-5">
      {Object.entries(grouped).map(([section, sectionFields]) => (
        <div key={section} className="space-y-3">
          <div>
            <h4 className="text-sm font-medium capitalize text-foreground">
              {getSectionTitle(section, t, pluginId)}
            </h4>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {sectionFields.map((field) => (
              <DynamicConfigField
                key={field.key}
                spec={field}
                value={values[field.key] ?? field.default ?? (field.type === 'tags' ? [] : '')}
                onChange={(value) => onChange(field.key, value)}
                disabled={disabled}
                selectOptions={field.options.map((option) => ({
                  label: getOptionLabel(option.value, field.key, t, pluginId, option.label),
                  value: option.value,
                }))}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

export default PluginSettingsFields;
