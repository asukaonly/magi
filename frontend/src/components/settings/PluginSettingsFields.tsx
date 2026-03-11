import React from 'react';

import { DynamicConfigField } from '@/components/config-forms/DynamicToolConfig';
import type { ExtensionFieldSpec } from '@/api/modules/plugins';

interface PluginSettingsFieldsProps {
  fields: ExtensionFieldSpec[];
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
  disabled?: boolean;
}

const sortFields = (fields: ExtensionFieldSpec[]) =>
  [...fields].sort((left, right) => {
    if (left.section !== right.section) {
      return left.section.localeCompare(right.section);
    }
    return left.order - right.order;
  });

export const PluginSettingsFields: React.FC<PluginSettingsFieldsProps> = ({
  fields,
  values,
  onChange,
  disabled = false,
}) => {
  const grouped = sortFields(fields).reduce<Record<string, ExtensionFieldSpec[]>>((acc, field) => {
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
            <h4 className="text-sm font-medium capitalize text-foreground">{section.replace(/_/g, ' ')}</h4>
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
                  label: option.label,
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
