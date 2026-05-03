import { describe, expect, it } from 'vitest';
import enApp from '@/i18n/locales/en/app.json';
import zhCnApp from '@/i18n/locales/zh-CN/app.json';

const REQUIRED_PERSONALITY_KEYS = [
  'personality.sections.identityCore',
  'personality.sections.idiolect',
  'personality.sections.registers',
  'personality.sections.signatureTriggers',
  'personality.sections.quietHours',
  'personality.sectionDescriptions.basicProfile',
  'personality.sectionDescriptions.identityCore',
  'personality.sectionDescriptions.registers',
  'personality.fields.identityStatement',
  'personality.fields.valuesLoved',
  'personality.fields.valuesRejected',
  'personality.fields.attentionBiases',
  'personality.fields.sentenceStyle',
  'personality.fields.vocabAvailable',
  'personality.fields.vocabAvoided',
  'personality.fields.structuralQuirks',
  'personality.fields.chatBehavior',
  'personality.fields.registerDescription',
  'personality.fields.registerBehavior',
  'personality.fields.registerExamples',
  'personality.fields.triggerId',
  'personality.fields.activatesWhen',
  'personality.fields.intensityLevels',
  'personality.fields.exitBehavior',
  'personality.fields.quietHourCondition',
  'personality.fields.clamps',
  'personality.fields.triggerCard',
  'personality.fields.quietHourCard',
  'personality.fields.layerCard',
  'personality.fields.clampKey',
  'personality.fields.clampValue',
  'personality.fields.layerModifiers',
  'personality.fieldHelp.description',
  'personality.fieldHelp.identityStatement',
  'personality.fieldHelp.registerExamples',
  'personality.fieldHelp.clamps',
  'personality.fieldHelp.appearancePrompt',
  'personality.placeholders.registerExamples',
  'personality.actions.addTrigger',
  'personality.actions.removeTrigger',
  'personality.actions.addQuietHour',
  'personality.actions.removeQuietHour',
  'personality.actions.addClamp',
  'personality.actions.removeClamp',
  'personality.actions.addModifier',
  'personality.actions.removeModifier',
  'personality.editorModes.quick',
  'personality.editorModes.expert',
  'personality.generationStages.base',
  'personality.generationStages.registers',
  'personality.generationStages.rules',
  'personality.generationStages.layers',
  'personality.generationStages.bootstrap',
  'personality.generationStages.appearance',
  'personality.generationStages.integrate',
  'personality.registers.chat',
  'personality.registers.analysis',
  'personality.registers.task',
  'personality.registers.emotional',
  'personality.registers.crisis',
  'personality.validation.ready',
  'personality.validation.missing',
  'personality.validation.expertReady',
  'personality.validation.expertMissing',
  'personality.validationIssues.signatureTriggerCount',
  'personality.validationIssues.signatureTriggerShape',
  'personality.validationIssues.uniqueTriggerIds',
  'personality.validationIssues.quietHourCount',
  'personality.validationIssues.quietHourShape',
  'personality.validationIssues.allRegisters',
  'personality.validationIssues.examplesCount',
  'personality.validationIssues.surfaceLayer',
  'personality.validationIssues.layerShape',
  'personality.validationIssues.bootstrap',
] as const;

const localeResources = {
  en: enApp,
  'zh-CN': zhCnApp,
} as const;

const getValue = (resource: unknown, key: string): unknown =>
  key.split('.').reduce<unknown>((current, part) => {
    if (!current || typeof current !== 'object') return undefined;
    return (current as Record<string, unknown>)[part];
  }, resource);

describe('personality i18n', () => {
  it('keeps the persona editor translation keys in every app locale', () => {
    for (const [locale, resource] of Object.entries(localeResources)) {
      const missingKeys = REQUIRED_PERSONALITY_KEYS.filter((key) => {
        const value = getValue(resource, key);
        return typeof value !== 'string' || value.length === 0;
      });

      expect(missingKeys, `${locale} missing keys`).toEqual([]);
    }
  });
});
