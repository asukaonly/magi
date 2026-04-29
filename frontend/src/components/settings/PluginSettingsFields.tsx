import React from 'react';
import { useTranslation } from 'react-i18next';

import { DynamicConfigField } from '@/components/config-forms/DynamicConfigField';
import type { ExtensionFieldSpec } from '@/api/modules/plugins';

type TFunction = (key: string) => string;

const getOptionalTranslation = (t: TFunction, key: string): string | undefined => {
  const translated = t(key);
  return translated === key ? undefined : translated;
};

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

const buildFieldKeyCandidates = (fieldKey: string): string[] => {
  const candidates = [fieldKey];
  const segments = fieldKey.split('.');
  const leafKey = segments[segments.length - 1];
  if (leafKey && !candidates.includes(leafKey)) {
    candidates.push(leafKey);
  }
  return candidates;
};

/**
 * Helper function to get translated section title with fallback
 */
const getSectionTitle = (
  section: string,
  t: TFunction,
  pluginId: string | undefined
): string => {
  if (pluginId) {
    const pluginTitle = getOptionalTranslation(t, `settings.plugins.${pluginId}.sections.${section}`);
    if (pluginTitle) {
      return pluginTitle;
    }
  }
  return getOptionalTranslation(t, `settings.pluginSections.${section}`) ?? section.replace(/_/g, ' ');
};

const getSectionNote = (
  section: string,
  t: TFunction,
  pluginId: string | undefined
): string | undefined => {
  if (!pluginId) {
    return undefined;
  }
  return getOptionalTranslation(t, `settings.plugins.${pluginId}.section_notes.${section}`);
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
  for (const candidate of buildFieldKeyCandidates(fieldKey)) {
    const translationPath = `options.${candidate}.${optionValue}`;
    const translated = getPluginTranslation(t, pluginId, translationPath, translationPath);
    if (translated !== translationPath) {
      return translated;
    }
  }
  return originalLabel;
};

const getTranslatedFieldValue = (
  t: TFunction,
  pluginId: string | undefined,
  fieldKey: string,
  property: 'label' | 'description' | 'placeholder',
  fallback: string
): string => {
  if (!pluginId || !fallback) {
    return fallback;
  }
  for (const candidate of buildFieldKeyCandidates(fieldKey)) {
    const translationPath = `fields.${candidate}.${property}`;
    const translated = getPluginTranslation(t, pluginId, translationPath, translationPath);
    if (translated !== translationPath) {
      return translated;
    }
  }
  return fallback;
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
            {getSectionNote(section, t, pluginId) ? (
              <p className="mt-1 max-w-3xl text-xs leading-6 text-muted-foreground">
                {getSectionNote(section, t, pluginId)}
              </p>
            ) : null}
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {sectionFields.map((field) => (
              <DynamicConfigField
                key={field.key}
                spec={{
                  ...field,
                  label: getTranslatedFieldValue(t, pluginId, field.key, 'label', field.label),
                  description: getTranslatedFieldValue(t, pluginId, field.key, 'description', field.description),
                  placeholder: field.placeholder
                    ? getTranslatedFieldValue(t, pluginId, field.key, 'placeholder', field.placeholder)
                    : field.placeholder,
                }}
                value={values[field.key] ?? field.default ?? (field.type === 'tags' || (field.type === 'path' && Array.isArray(field.default)) ? [] : '')}
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
