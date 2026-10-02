import { expect, it } from 'vitest';
import { validateSynthesisJob, validateTTSConfiguration } from '@/api/generated/tts-validators';

it('rejects malformed TTS replies instead of presenting fabricated progress', () => {
  expect(validateSynthesisJob({ job_id: 'job', state: 'completed' })).toBe(false);
  expect(validateSynthesisJob({ job_id: 'job', state: 'running', audio: 'base64' })).toBe(false);
  expect(validateTTSConfiguration({ settings: { engine: 'browser' }, revision: 'r', voices: [] })).toBe(false);
});
