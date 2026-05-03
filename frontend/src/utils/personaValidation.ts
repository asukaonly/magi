import type { PersonalityConfig, PersonaLayerItem, PersonaRegister, QuietHour, SignatureTrigger } from '@/api/modules/personas';

export type PersonaValidationScope = 'minimum' | 'expert';

export interface PersonaValidationIssue {
  key: string;
  labelKey: string;
  scope: PersonaValidationScope;
}

export interface PersonaValidationReport {
  minimumIssues: PersonaValidationIssue[];
  expertIssues: PersonaValidationIssue[];
  isMinimumReady: boolean;
  isExpertReady: boolean;
}

export const REQUIRED_PERSONA_REGISTERS = ['chat', 'analysis', 'task', 'emotional', 'crisis'] as const;

const hasText = (value: unknown): boolean => typeof value === 'string' && value.trim().length > 0;

const nonEmptyCount = (items: unknown[] | undefined): number =>
  Array.isArray(items) ? items.filter((item) => hasText(item)).length : 0;

const isCompleteTrigger = (item: Partial<SignatureTrigger> | undefined): boolean =>
  Boolean(item && hasText(item.trigger_id) && hasText(item.activates_when) && hasText(item.behavior_shift));

const isCompleteQuietHour = (item: Partial<QuietHour> | undefined): boolean =>
  Boolean(item && hasText(item.condition) && item.clamps && Object.keys(item.clamps).length > 0);

const isCompleteRegister = (item: Partial<PersonaRegister> | undefined): boolean =>
  Boolean(item && hasText(item.description) && hasText(item.behavior));

const hasUsableLayer = (item: Partial<PersonaLayerItem> | undefined): boolean => {
  if (!item || !hasText(item.layer_id)) return false;
  if (item.layer_id === 'surface') return true;
  return Boolean(item.unlock_condition && Object.keys(item.unlock_condition).length > 0 && item.modifiers && Object.keys(item.modifiers).length > 0);
};

const uniqueTriggerIds = (triggers: SignatureTrigger[]): boolean => {
  const ids = triggers.map((item) => item.trigger_id.trim()).filter(Boolean);
  return new Set(ids).size === ids.length;
};

const issue = (key: string, labelKey: string, scope: PersonaValidationScope): PersonaValidationIssue => ({
  key,
  labelKey,
  scope,
});

export const validatePersonalityConfig = (config: PersonalityConfig): PersonaValidationReport => {
  const minimumIssues: PersonaValidationIssue[] = [];
  const expertIssues: PersonaValidationIssue[] = [];

  if (!hasText(config.name)) minimumIssues.push(issue('name', 'personality.fields.name', 'minimum'));
  if (!hasText(config.identity_core.identity_statement)) {
    minimumIssues.push(issue('identity_statement', 'personality.fields.identityStatement', 'minimum'));
  }
  if (nonEmptyCount(config.identity_core.values_loved) === 0) {
    minimumIssues.push(issue('values_loved', 'personality.fields.valuesLoved', 'minimum'));
  }
  if (nonEmptyCount(config.identity_core.values_rejected) === 0) {
    minimumIssues.push(issue('values_rejected', 'personality.fields.valuesRejected', 'minimum'));
  }
  if (!hasText(config.idiolect.sentence_style)) {
    minimumIssues.push(issue('sentence_style', 'personality.fields.sentenceStyle', 'minimum'));
  }
  if (!hasText(config.registers.chat?.behavior)) {
    minimumIssues.push(issue('chat_register', 'personality.registers.chat', 'minimum'));
  }

  const completeTriggerCount = config.signature_triggers.filter(isCompleteTrigger).length;
  if (completeTriggerCount < 2) {
    expertIssues.push(issue('signature_trigger_count', 'personality.validationIssues.signatureTriggerCount', 'expert'));
  }
  if (config.signature_triggers.some((item) => !isCompleteTrigger(item))) {
    expertIssues.push(issue('signature_trigger_shape', 'personality.validationIssues.signatureTriggerShape', 'expert'));
  }
  if (!uniqueTriggerIds(config.signature_triggers)) {
    expertIssues.push(issue('unique_trigger_ids', 'personality.validationIssues.uniqueTriggerIds', 'expert'));
  }

  const completeQuietHourCount = config.quiet_hours.filter(isCompleteQuietHour).length;
  if (completeQuietHourCount < 2) {
    expertIssues.push(issue('quiet_hour_count', 'personality.validationIssues.quietHourCount', 'expert'));
  }
  if (config.quiet_hours.some((item) => !isCompleteQuietHour(item))) {
    expertIssues.push(issue('quiet_hour_shape', 'personality.validationIssues.quietHourShape', 'expert'));
  }

  const missingRegisters = REQUIRED_PERSONA_REGISTERS.filter((key) => !isCompleteRegister(config.registers[key]));
  if (missingRegisters.length > 0) {
    expertIssues.push(issue('all_registers', 'personality.validationIssues.allRegisters', 'expert'));
  }

  const exampleCount = REQUIRED_PERSONA_REGISTERS.reduce((total, key) => {
    const register = config.registers[key];
    return total + nonEmptyCount(register?.examples || []);
  }, 0);
  if (exampleCount < 6) {
    expertIssues.push(issue('examples_count', 'personality.validationIssues.examplesCount', 'expert'));
  }

  if (!config.persona_layers.some((item) => item.layer_id === 'surface')) {
    expertIssues.push(issue('surface_layer', 'personality.validationIssues.surfaceLayer', 'expert'));
  }
  if (config.persona_layers.some((item) => !hasUsableLayer(item))) {
    expertIssues.push(issue('layer_shape', 'personality.validationIssues.layerShape', 'expert'));
  }

  if (!config.bootstrap || !hasText(config.bootstrap.style_instruction) || !hasText(config.bootstrap.opening_line)) {
    expertIssues.push(issue('bootstrap', 'personality.validationIssues.bootstrap', 'expert'));
  }

  return {
    minimumIssues,
    expertIssues,
    isMinimumReady: minimumIssues.length === 0,
    isExpertReady: minimumIssues.length === 0 && expertIssues.length === 0,
  };
};

export const formatPersonaValidationIssues = (
  issues: PersonaValidationIssue[],
  t: (key: string, options?: Record<string, unknown>) => string,
): string[] => issues.map((item) => t(item.labelKey));
