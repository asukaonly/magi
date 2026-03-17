import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { toast } from 'sonner';

import { SimpleForm as Form } from '@/components/onboarding/simple-form';
import { PersonalityForm } from '@/components/config-forms/PersonalityForm';
import { DEFAULT_PERSONALITY_CONFIG } from '@/api/modules/personality';
import { personalityApi, personalitiesApi } from '@/api';

vi.mock('sonner', () => ({
  toast: {
    error: vi.fn(),
  },
}));

vi.mock('@/api', async () => {
  const actual = await vi.importActual<typeof import('@/api')>('@/api');
  return {
    ...actual,
    personalityApi: {
      ...actual.personalityApi,
      generate: vi.fn().mockResolvedValue({
        data: actual.DEFAULT_PERSONALITY_CONFIG,
      }),
    },
    personalitiesApi: {
      ...actual.personalitiesApi,
      list: vi.fn().mockResolvedValue({ data: [] }),
      get: vi.fn(),
      uploadAvatar: vi.fn(),
      getAvatarUrl: vi.fn(() => ''),
    },
  };
});

describe('PersonalityForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('scrollTo', vi.fn());
  });

  it('passes the current llm draft override when generating personality', async () => {
    const user = userEvent.setup();

    render(
      <Form
        initialValues={{
          llm: {
            providers: {
              openai: {
                enabled: true,
                provider_type: 'openai',
                display_name: 'OpenAI',
                api_key: 'sk-draft-openai',
                base_url: 'https://api.openai.com/v1',
              },
            },
            selections: {
              context_decider: {
                provider_id: 'openai',
                model: 'gpt-5.2',
                capability_override_enabled: false,
                capabilities: {
                  vision: true,
                  image_output: false,
                  tool_calling: true,
                  reasoning: true,
                  embedding: false,
                },
                limits: {
                  context_window: 400000,
                  max_output_tokens: 128000,
                },
                provider_options: {},
              },
              core: {
                provider_id: 'openai',
                model: 'gpt-5.2',
                capability_override_enabled: false,
                capabilities: {
                  vision: true,
                  image_output: false,
                  tool_calling: true,
                  reasoning: true,
                  embedding: false,
                },
                limits: {
                  context_window: 400000,
                  max_output_tokens: 128000,
                },
                provider_options: {},
              },
            },
          },
          personality: DEFAULT_PERSONALITY_CONFIG,
        }}
      >
        <PersonalityForm language="zh" />
      </Form>
    );

    await user.click((await screen.findByText('personality.blankCardTitle')).closest('button') as HTMLButtonElement);
    await user.type(await screen.findByPlaceholderText('personality.oneLinerPlaceholder'), '一个冷静可靠的助手');
    await user.click(screen.getByRole('button', { name: 'personality.generateAction' }));

    await waitFor(() => {
      expect(personalityApi.generate).toHaveBeenCalledWith(
        expect.objectContaining({
          description: '一个冷静可靠的助手',
          target_language: 'Chinese',
          llm_override: expect.objectContaining({
            providers: expect.objectContaining({
              openai: expect.objectContaining({
                api_key: 'sk-draft-openai',
              }),
            }),
            selections: expect.objectContaining({
              core: expect.objectContaining({
                provider_id: 'openai',
                model: 'gpt-5.2',
              }),
            }),
          }),
        })
      );
    });

    expect(personalitiesApi.list).toHaveBeenCalled();
  });

  it('applies the generated personality payload from the api response envelope', async () => {
    const user = userEvent.setup();

    vi.mocked(personalityApi.generate).mockResolvedValueOnce({
      data: {
        success: true,
        message: 'ok',
        data: {
          ...DEFAULT_PERSONALITY_CONFIG,
          persona_entity: {
            ...DEFAULT_PERSONALITY_CONFIG.persona_entity,
            basic_profile: {
              ...DEFAULT_PERSONALITY_CONFIG.persona_entity.basic_profile,
              name: '向晚',
              occupation: '虚拟偶像',
              core_background: '一个努力又有点笨拙的虚拟偶像。',
            },
          },
        },
      },
    } as any);

    render(
      <Form
        initialValues={{
          llm: {
            providers: {},
            selections: {},
          },
          personality: DEFAULT_PERSONALITY_CONFIG,
        }}
      >
        <PersonalityForm language="zh" />
      </Form>
    );

    await user.click((await screen.findByText('personality.blankCardTitle')).closest('button') as HTMLButtonElement);
    await user.type(await screen.findByPlaceholderText('personality.oneLinerPlaceholder'), '一个有点笨拙但很努力的偶像');
    await user.click(screen.getByRole('button', { name: 'personality.generateAction' }));

    await waitFor(() => {
      expect(screen.getAllByText('向晚').length).toBeGreaterThan(0);
    });
  });

  it('surfaces generate failures to the user', async () => {
    const user = userEvent.setup();

    vi.mocked(personalityApi.generate).mockRejectedValueOnce({
      message: 'GLM request failed',
    });

    render(
      <Form
        initialValues={{
          llm: {
            providers: {},
            selections: {},
          },
          personality: DEFAULT_PERSONALITY_CONFIG,
        }}
      >
        <PersonalityForm language="zh" />
      </Form>
    );

    await user.click((await screen.findByText('personality.blankCardTitle')).closest('button') as HTMLButtonElement);
    await user.type(await screen.findByPlaceholderText('personality.oneLinerPlaceholder'), 'asoul的向晚');
    await user.click(screen.getByRole('button', { name: 'personality.generateAction' }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith('GLM request failed');
    });
  });

  it('auto-selects Echo-01 as the default preset when current personality is blank', async () => {
    vi.mocked(personalitiesApi.list).mockResolvedValueOnce({
      data: [
        {
          id: 'seven_hacker',
          name: '七号',
          occupation: '赛博乐子人 / 反讽大师',
          description: 'desc-seven',
          avatar: 'system-caspar.jpg',
          prompt: 'prompt-seven',
          group: 'general',
          order: 2,
        },
        {
          id: 'echo_ai_ssistant',
          name: 'Echo-01',
          occupation: '标准通用型交互助手',
          description: 'desc-echo',
          avatar: 'system-echo.jpg',
          prompt: 'prompt-echo',
          group: 'general',
          order: 1,
        },
      ],
    } as any);
    vi.mocked(personalitiesApi.get).mockResolvedValueOnce({
      data: {
        ...DEFAULT_PERSONALITY_CONFIG,
        persona_entity: {
          ...DEFAULT_PERSONALITY_CONFIG.persona_entity,
          basic_profile: {
            ...DEFAULT_PERSONALITY_CONFIG.persona_entity.basic_profile,
            name: 'Echo-01',
          },
        },
      },
    } as any);

    render(
      <Form
        initialValues={{
          llm: {
            providers: {},
            selections: {},
          },
          personality: DEFAULT_PERSONALITY_CONFIG,
        }}
      >
        <PersonalityForm language="zh" />
      </Form>
    );

    await waitFor(() => {
      expect(personalitiesApi.get).toHaveBeenCalledWith('echo_ai_ssistant', 'zh');
    });
  });
});
