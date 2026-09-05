import type { ToolConfigSpec } from '@/api/modules/tools';
import type { ExtensionFieldSpec } from '@/api/modules/plugins';

export type DynamicConfigSpec = ToolConfigSpec | ExtensionFieldSpec;

export type NormalizedDynamicConfigSpec = {
  inputKind: 'boolean' | 'select' | 'secret' | 'number' | 'string' | 'array' | 'json' | 'path' | 'path_list' | 'checkbox_group';
  label: string;
  description?: string;
  required: boolean;
  placeholder?: string;
  readOnly: boolean;
  sensitive: boolean;
  pathKind?: 'file' | 'directory';
  defaultValue?: any;
  enumValues?: any[];
  minimum?: number;
  maximum?: number;
};

const isExtensionFieldSpec = (spec: DynamicConfigSpec): spec is ExtensionFieldSpec => 'key' in spec;

export const normalizeDynamicSpec = (
  spec: DynamicConfigSpec,
  providerName?: string
): NormalizedDynamicConfigSpec => {
  if (isExtensionFieldSpec(spec)) {
    const enumValues = spec.type === 'select'
      ? spec.options.map((option) => option.value)
      : spec.type === 'tags' && spec.options.length > 0
        ? spec.options.map((option) => option.value)
        : undefined;
    const inputKind = (() => {
      switch (spec.type) {
        case 'switch':
          return 'boolean';
        case 'select':
          return 'select';
        case 'secret':
          return 'secret';
        case 'number':
          return 'number';
        case 'tags':
          return spec.options.length > 0 ? 'checkbox_group' : 'array';
        case 'path':
          if (Array.isArray(spec.default)) {
            return 'path_list';
          }
          return spec.path_kind ? 'path' : 'string';
        case 'input':
          return 'string';
        default:
          return 'string';
      }
    })();
    return {
      inputKind,
      label: spec.label,
      description: spec.description,
      required: spec.required,
      placeholder: spec.placeholder ?? undefined,
      readOnly: false,
      sensitive: spec.type === 'secret',
      pathKind: spec.path_kind ?? undefined,
      defaultValue: spec.default,
      enumValues,
      minimum: spec.minimum ?? undefined,
      maximum: spec.maximum ?? undefined,
    };
  }

  const label = spec.is_template && providerName
    ? spec.description.replace('{provider}', providerName)
    : spec.description;
  const inputKind = (() => {
    if (spec.type === 'boolean') {
      return 'boolean';
    }
    if (spec.type === 'string' && spec.enum && spec.enum.length > 0) {
      return 'select';
    }
    if (spec.type === 'string' && spec.sensitive) {
      return 'secret';
    }
    if (spec.type === 'integer' || spec.type === 'float') {
      return 'number';
    }
    if (spec.type === 'array') {
      return 'array';
    }
    if (spec.type === 'object') {
      return 'json';
    }
    return 'string';
  })();

  return {
    inputKind,
    label,
    required: spec.required,
    placeholder: spec.placeholder,
    readOnly: spec.read_only,
    sensitive: spec.sensitive,
    defaultValue: spec.default,
    enumValues: spec.enum,
  };
};
