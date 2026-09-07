import type { ExtensionFieldSpec } from '@/api/modules/plugins';
import { isExtensionFieldVisible, validateDynamicConfigValue, type DynamicConfigIssue } from '@/components/config-forms/dynamic-config-specs';

/** Drafts may omit setup fields, but provided values always retain their declared type. */
export function validateConnectionField(
  field: ExtensionFieldSpec, value: unknown, values: Record<string, unknown>, enabled: boolean,
): DynamicConfigIssue | null {
  const required = enabled && field.required && isExtensionFieldVisible(field, values);
  if (value === undefined) return required && field.default == null ? 'required' : null;
  // A declared required selector only accepts its options, even on a disabled draft.
  const spec = { ...field, required: required || (field.type === 'select' && field.required) };
  return validateDynamicConfigValue(spec, value, { allowMissing: false });
}
