import type { ToolConfigSpec } from '@/api/modules/tools';
import type { ExtensionFieldSpec } from '@/api/modules/plugins';
import { isRecord, isStringArray } from '@/utils/value-guards';

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
  defaultValue?: unknown;
  enumValues?: unknown[];
  minimum?: number;
  maximum?: number;
};

const isExtensionFieldSpec = (spec: DynamicConfigSpec): spec is ExtensionFieldSpec => 'key' in spec;

export function isExtensionFieldVisible(field: ExtensionFieldSpec, values: Record<string, unknown>): boolean {
  return !field.depends_on_key || !field.depends_on_values?.length
    || field.depends_on_values.includes(String(values[field.depends_on_key] ?? ''));
}

export type DynamicConfigIssue = 'required' | 'boolean' | 'number' | 'integer' | 'selection' | 'string' | 'stringArray' | 'object';

/** Validate only constraints represented by the host field specification. */
export function validateDynamicConfigValue(
  spec: DynamicConfigSpec, value: unknown, { allowMissing = true }: { allowMissing?: boolean } = {},
): DynamicConfigIssue | null {
  const normalized = normalizeDynamicSpec(spec);
  if (allowMissing && (value === undefined || value === null)) return normalized.required ? 'required' : null;
  if (normalized.required && ((typeof value === 'string' && !value.trim()) || (Array.isArray(value) && !value.length))) return 'required';
  switch (normalized.inputKind) {
    case 'boolean': return typeof value === 'boolean' ? null : 'boolean';
    case 'number':
      if (typeof value !== 'number' || !Number.isFinite(value)) return 'number';
      if ((normalized.minimum !== undefined && value < normalized.minimum)
        || (normalized.maximum !== undefined && value > normalized.maximum)) return 'number';
      return spec.type === 'integer' && !Number.isInteger(value) ? 'integer' : null;
    case 'select':
      if (value === '' && !normalized.required) return null;
      return normalized.enumValues?.includes(value) ? null : 'selection';
    case 'path_list':
    case 'array': return isStringArray(value) ? null : 'stringArray';
    case 'checkbox_group':
      if (!isStringArray(value)) return 'stringArray';
      return value.every(item => normalized.enumValues?.includes(item)) ? null : 'selection';
    case 'json': return isRecord(value) ? null : 'object';
    default: return typeof value === 'string' ? null : 'string';
  }
}

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
