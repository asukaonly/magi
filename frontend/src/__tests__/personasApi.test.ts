import { afterEach, describe, expect, it, vi } from 'vitest';
import { personasApi, type PersonalityConfig } from '../api/modules/personas';

vi.mock('@/runtime/config', () => ({
  getRuntimeConfig: () => ({ apiBaseUrl: 'http://localhost/api' }),
}));

function makeGeneratedConfig(): PersonalityConfig {
  return {
    name: 'Soryu',
    avatar: '',
    description: 'quietly intense persona',
    appearance_prompt: '',
    identity_core: {
      identity_statement: 'a guarded pilot',
      values_loved: [],
      values_rejected: [],
      attention_biases: [],
    },
    idiolect: {
      sentence_style: 'sharp and restrained',
      vocab_available: [],
      vocab_avoided: [],
      structural_quirks: [],
    },
    registers: {},
    quiet_hours: [],
    signature_triggers: [],
    persona_layers: [],
    dynamic_state_rules: {},
    milestone_conditions: {},
    interim_lines: {},
    bootstrap: null,
  };
}

describe('personasApi generation jobs', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('keeps polling custom persona generation jobs beyond three minutes', async () => {
    vi.useFakeTimers();
    const generated = makeGeneratedConfig();
    let pollCount = 0;

    vi.spyOn(personasApi, 'startGenerationJob').mockResolvedValue({
      success: true,
      message: 'started',
      data: { job_id: 'job-1', status: 'running', stages: [] },
    });
    vi.spyOn(personasApi, 'getGenerationJob').mockImplementation(async () => {
      pollCount += 1;
      if (pollCount >= 185) {
        return {
          success: true,
          message: 'done',
          data: {
            job_id: 'job-1',
            status: 'completed',
            stages: [],
            data: generated,
          },
        };
      }
      return {
        success: true,
        message: 'running',
        data: { job_id: 'job-1', status: 'running', stages: [] },
      };
    });

    const resultPromise = personasApi.generateWithProgress({
      description: 'eva里的明日香',
      target_language: 'Chinese',
    });

    await vi.advanceTimersByTimeAsync(185_000);

    await expect(resultPromise).resolves.toMatchObject({
      success: true,
      data: { name: 'Soryu' },
    });
  });
});

describe('personasApi avatar URLs', () => {
  it('does not turn generated avatar text into a broken static image URL', () => {
    expect(personasApi.getAvatarUrl('惣流·明日香·兰格雷')).toBe('');
  });

  it('resolves image filenames to the built-in static avatar directory', () => {
    expect(personasApi.getAvatarUrl('echo.png')).toBe('http://localhost/static/avatars/echo.png');
  });
});
