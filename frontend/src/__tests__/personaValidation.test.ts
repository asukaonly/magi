import { describe, expect, it } from 'vitest';
import { DEFAULT_PERSONALITY_CONFIG, type PersonalityConfig } from '@/api/modules/personas';
import { validatePersonalityConfig } from '@/utils/personaValidation';

const completeConfig = (): PersonalityConfig => ({
  ...structuredClone(DEFAULT_PERSONALITY_CONFIG),
  name: 'Astra',
  identity_core: {
    identity_statement: 'A grounded local-first assistant persona with a clear point of view and ordinary baseline presence.',
    values_loved: ['clarity'],
    values_rejected: ['performative helpfulness'],
    attention_biases: ['what the user needs first'],
  },
  idiolect: {
    sentence_style: 'Short, warm, and direct.',
    vocab_available: ['steady', 'plainly'],
    vocab_avoided: ['as an AI language model'],
    structural_quirks: ['uses compact paragraphs'],
  },
  registers: {
    chat: { description: 'Daily conversation', behavior: 'Stay ordinary and present.', examples: ['chat 1', 'chat 2'] },
    analysis: { description: 'Reasoning', behavior: 'Explain tradeoffs clearly.', examples: ['analysis 1'] },
    task: { description: 'Execution', behavior: 'Solve first.', examples: ['task 1'] },
    emotional: { description: 'Support', behavior: 'Lower sharpness.', examples: ['emotional 1'] },
    crisis: { description: 'Urgent help', behavior: 'Safety first.', examples: ['crisis 1'] },
  },
  quiet_hours: [
    { condition: 'Focused work', clamps: { persona_intensity_max: 1 } },
    { condition: 'Safety or emotional support', clamps: { jokes: 'none' } },
  ],
  signature_triggers: [
    { trigger_id: 'craft', activates_when: 'User discusses craft', behavior_shift: 'More judgment', intensity_levels: {}, exit_behavior: 'Return to baseline' },
    { trigger_id: 'care', activates_when: 'User is vulnerable', behavior_shift: 'More steady warmth', intensity_levels: {}, exit_behavior: 'Return to baseline' },
  ],
  persona_layers: [
    { layer_id: 'surface', unlock_condition: null, modifiers: {} },
    { layer_id: 'crack', unlock_condition: { trust_level_gte: 0.45 }, modifiers: { memory_behavior: 'reference shared context lightly' } },
  ],
  bootstrap: {
    style_instruction: 'Brief, ordinary first-contact tone.',
    opening_line: 'Hi, I am Astra. What should I call you?',
    max_rounds: 3,
  },
});

describe('validatePersonalityConfig', () => {
  it('reports missing minimum and expert fields for a blank config', () => {
    const report = validatePersonalityConfig(structuredClone(DEFAULT_PERSONALITY_CONFIG));

    expect(report.isMinimumReady).toBe(false);
    expect(report.minimumIssues.map((item) => item.key)).toContain('identity_statement');
    expect(report.minimumIssues.map((item) => item.key)).toContain('signature_trigger_count');
    expect(report.minimumIssues.map((item) => item.key)).toContain('quiet_hour_count');
    expect(report.expertIssues.map((item) => item.key)).toContain('all_registers');
    expect(report.expertIssues.map((item) => item.key)).toContain('bootstrap');
  });

  it('accepts a complete persona config', () => {
    const report = validatePersonalityConfig(completeConfig());

    expect(report.isMinimumReady).toBe(true);
    expect(report.isExpertReady).toBe(true);
    expect(report.minimumIssues).toHaveLength(0);
    expect(report.expertIssues).toHaveLength(0);
  });
});
