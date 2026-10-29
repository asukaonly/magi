import { expect, it } from 'vitest';
import { validateSynthesisJob, validateTTSConfiguration } from '@/api/generated/tts-validators';

it('rejects malformed TTS replies instead of presenting fabricated progress', () => {
  expect(validateSynthesisJob({ job_id: 'job', state: 'completed' })).toBe(false);
  expect(validateSynthesisJob({ job_id: 'job', state: 'running', audio: 'base64' })).toBe(false);
  expect(validateTTSConfiguration({ settings: { engine: 'browser' }, revision: 'r', voices: [] })).toBe(false);
});

it('rejects unknown capabilities and malformed reference assets', async () => {
  const { modernTTSConfiguration } = await import('./fixtures/tts');
  const config = modernTTSConfiguration();
  expect(validateTTSConfiguration(config)).toBe(true);
  expect(validateTTSConfiguration({ ...config, models: [{ ...config.models[0], reference_audio: 'maybe' }] })).toBe(false);
  expect(validateTTSConfiguration({ ...config, reference_audio: [{ id: '../../voice', name: 'voice', seconds: 5 }] })).toBe(false);
});
