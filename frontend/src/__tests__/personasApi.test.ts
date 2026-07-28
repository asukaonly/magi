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

  it('marks a poll network failure as non-terminal and keeps the job id', async () => {
    vi.useFakeTimers();
    vi.spyOn(personasApi, 'startGenerationJob').mockResolvedValue({
      success: true,
      message: 'started',
      data: { job_id: 'job-poll', status: 'running', stages: [] },
    });
    vi.spyOn(personasApi, 'getGenerationJob').mockRejectedValue(
      new Error('poll network unavailable'),
    );

    const resultPromise = personasApi.generateWithProgress({
      description: 'retryable persona',
      request_id: 'request-poll',
    });
    const expectation = expect(resultPromise).rejects.toMatchObject({
      message: 'poll network unavailable',
      terminal: false,
      generationJobId: 'job-poll',
    });
    await vi.advanceTimersByTimeAsync(1_000);

    await expectation;
  });

  it('marks an explicit failed job as terminal', async () => {
    vi.spyOn(personasApi, 'startGenerationJob').mockResolvedValue({
      success: true,
      message: 'failed',
      data: {
        job_id: 'job-failed',
        status: 'failed',
        stages: [],
        error: 'generation rejected',
        error_code: 'GENERATION_REJECTED',
      },
    });

    await expect(
      personasApi.generateWithProgress({
        description: 'terminal persona',
        request_id: 'request-failed',
      }),
    ).rejects.toMatchObject({
      message: 'generation rejected',
      code: 'GENERATION_REJECTED',
      terminal: true,
      generationJobId: 'job-failed',
    });
  });

  it('keeps a failed start request retryable without inventing a job id', async () => {
    const startSpy = vi
      .spyOn(personasApi, 'startGenerationJob')
      .mockRejectedValue(new Error('start response lost'));
    const request = {
      description: 'start retry',
      request_id: 'request-stable',
    };

    await expect(personasApi.generateWithProgress(request)).rejects.toMatchObject({
      message: 'start response lost',
      terminal: false,
      generationJobId: undefined,
    });
    expect(startSpy).toHaveBeenCalledWith(request);
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
