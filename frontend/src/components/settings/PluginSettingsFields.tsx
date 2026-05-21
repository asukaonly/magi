import React from 'react';
import { useTranslation } from 'react-i18next';

import { DynamicConfigField } from '@/components/config-forms/DynamicConfigField';
import type { ExtensionFieldOption, ExtensionFieldSpec } from '@/api/modules/plugins';

type TFunction = (key: string) => string;

const getOptionalTranslation = (t: TFunction, key: string): string | undefined => {
  const translated = t(key);
  return translated === key ? undefined : translated;
};

/**
 * Section title resolution (Phase 4):
 *   1. ``field.section_translated`` (API, per-plugin override from plugin i18n)
 *      — handled at the caller via ``getSectionTitleForFields``.
 *   2. shared host i18n at ``settings.pluginSections.{section}``
 *   3. the raw section key with underscores replaced
 */
const getSharedSectionTitle = (section: string, t: TFunction): string =>
  getOptionalTranslation(t, `settings.pluginSections.${section}`) ?? section.replace(/_/g, ' ');

const getSectionTitleForFields = (
  section: string,
  fields: ExtensionFieldSpec[],
  t: TFunction
): string => {
  const apiOverride = fields.find((field) => field.section_translated)?.section_translated;
  if (apiOverride) {
    return apiOverride;
  }
  return getSharedSectionTitle(section, t);
};

/**
 * Option label resolution (Phase 4):
 *   1. ``option.label_translated`` (API, plugin i18n)
 *   2. raw ``option.label`` (English fallback from the manifest)
 */
const getOptionLabel = (option: ExtensionFieldOption): string =>
  option.label_translated || option.label;

/**
 * Field text resolution (Phase 4):
 *   1. ``field.{property}_translated`` (API, plugin i18n)
 *   2. raw ``fallback`` (English value from the manifest)
 */
const getTranslatedFieldValue = (
  field: ExtensionFieldSpec,
  property: 'label' | 'description' | 'placeholder',
  fallback: string
): string => {
  if (property === 'label' && field.label_translated) {
    return field.label_translated;
  }
  if (property === 'description' && field.description_translated) {
    return field.description_translated;
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

const getSectionNoteForFields = (fields: ExtensionFieldSpec[]): string | undefined =>
  fields.find((field) => field.section_note_translated)?.section_note_translated || undefined;

export const PluginSettingsFields: React.FC<PluginSettingsFieldsProps> = ({
  fields,
  values,
  onChange,
  disabled = false,
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
      {Object.entries(grouped).map(([section, sectionFields]) => {
        const note = getSectionNoteForFields(sectionFields);
        return (
          <div key={section} className="space-y-3">
            <div>
              <h4 className="text-sm font-medium capitalize text-foreground">
                {getSectionTitleForFields(section, sectionFields, t)}
              </h4>
              {note ? (
                <p className="mt-1 max-w-3xl text-xs leading-6 text-muted-foreground">{note}</p>
              ) : null}
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              {sectionFields.map((field) => (
                <DynamicConfigField
                  key={field.key}
                  spec={{
                    ...field,
                    label: getTranslatedFieldValue(field, 'label', field.label),
                    description: getTranslatedFieldValue(field, 'description', field.description),
                    placeholder: field.placeholder
                      ? getTranslatedFieldValue(field, 'placeholder', field.placeholder)
                      : field.placeholder,
                  }}
                  value={values[field.key] ?? field.default ?? (field.type === 'tags' || (field.type === 'path' && Array.isArray(field.default)) ? [] : '')}
                  onChange={(value) => onChange(field.key, value)}
                  disabled={disabled}
                  selectOptions={field.options.map((option) => ({
                    label: getOptionLabel(option),
                    value: option.value,
                  }))}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default PluginSettingsFields;
