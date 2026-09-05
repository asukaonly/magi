import type { ExtensionFieldSpec } from '@/api/modules/plugins';

export const writeConnectionSetting = (
  settings: Record<string, unknown>, key: string, value: unknown,
): Record<string, unknown> => {
  if (Object.prototype.hasOwnProperty.call(settings, key)) return { ...settings, [key]: value };
  const [head, ...tail] = key.split('.');
  if (!tail.length) return { ...settings, [head]: value };
  const child = settings[head];
  return { ...settings, [head]: writeConnectionSetting(
    child && typeof child === 'object' && !Array.isArray(child) ? child as Record<string, unknown> : {},
    tail.join('.'), value,
  ) };
};

export const mergeConnectionSettings = (
  settings: Record<string, unknown>, updates: Record<string, unknown>,
): Record<string, unknown> => Object.entries(updates).reduce(
  (result, [key, value]) => writeConnectionSetting(result, key, value), settings,
);

export const connectionInput = (fields: ExtensionFieldSpec[], values: Record<string, unknown>) => {
  let settings: Record<string, unknown> = {};
  const credentials: Record<string, string> = {};
  for (const field of fields) {
    const value = Object.prototype.hasOwnProperty.call(values, field.key) ? values[field.key] : field.default;
    if (field.type === 'secret') {
      if (typeof value === 'string' && value) credentials[field.key] = value;
    } else if (value !== null && value !== undefined) {
      settings = writeConnectionSetting(settings, field.key, value);
    }
  }
  return { settings, credentials };
};
