import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { SimpleForm as Form } from '../components/onboarding/simple-form';
import LLMForm from '../components/config-forms/LLMForm';
import MemoryForm from '../components/config-forms/MemoryForm';

vi.mock('../api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('../api/modules/config')>('../api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      getLLMProviders: vi.fn().mockResolvedValue({
        data: {
          providers: [
            {
              id: 'openai',
              display_name: 'OpenAI',
              description: 'General purpose',
              default_model: 'gpt-5.2',
              models: [
                {
                  id: 'gpt-5.2',
                  label: 'GPT-5.2',
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
                  provider_options_example: {},
                },
                {
                  id: 'gpt-4.1-mini',
                  label: 'GPT-4.1 Mini',
                  capabilities: {
                    vision: true,
                    image_output: false,
                    tool_calling: true,
                    reasoning: true,
                    embedding: false,
                  },
                  limits: {
                    context_window: 128000,
                    max_output_tokens: 32000,
                  },
                  provider_options_example: {},
                },
              ],
              fields: {
                api_key: { visible: true, required: true },
                base_url: { visible: true, required: false },
              },
            },
            {
              id: 'anthropic',
              display_name: 'Anthropic',
              description: 'Reasoning',
              default_model: 'claude-sonnet-4-6',
              models: [
                {
                  id: 'claude-sonnet-4-6',
                  label: 'Claude Sonnet 4.6',
                  capabilities: {
                    vision: true,
                    image_output: false,
                    tool_calling: true,
                    reasoning: true,
                    embedding: false,
                  },
                  limits: {
                    context_window: 200000,
                    max_output_tokens: 64000,
                  },
                  provider_options_example: {},
                },
              ],
              fields: {
                api_key: { visible: true, required: true },
                base_url: { visible: true, required: false },
              },
            },
            {
              id: 'glm',
              display_name: 'GLM',
              description: 'Fast',
              default_model: 'glm-5',
              models: [
                {
                  id: 'glm-5',
                  label: 'GLM-5',
                  capabilities: {
                    vision: false,
                    image_output: false,
                    tool_calling: true,
                    reasoning: true,
                    embedding: false,
                  },
                  limits: {
                    context_window: 128000,
                    max_output_tokens: 32000,
                  },
                  provider_options_example: {
                    thinking: { type: 'disabled' },
                  },
                },
              ],
              fields: {
                api_key: { visible: true, required: true },
                base_url: { visible: true, required: false },
              },
            },
          ],
          custom_provider: {
            enabled: true,
            display_name: 'Custom Provider',
            fields: {
              custom_name: { visible: true, required: true },
              api_format: { visible: true, required: true, options: ['openai', 'anthropic', 'custom'] },
              model: { visible: true, required: true },
              api_key: { visible: true, required: true },
              base_url: { visible: true, required: false },
            },
            capabilities: {
              vision: false,
              image_output: false,
              tool_calling: true,
              reasoning: true,
              embedding: false,
            },
            limits: {
              context_window: null,
              max_output_tokens: null,
            },
            provider_options_example: {},
          },
        },
      }),
    },
  };
});

describe('config forms', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  const llmValue = {
    providers: {
      openai: {
        enabled: true,
        provider_type: 'openai',
        display_name: 'OpenAI',
        api_key: 'sk-openai',
        base_url: 'https://api.openai.com/v1',
      },
      anthropic: {
        enabled: false,
        provider_type: 'anthropic',
        display_name: 'Anthropic',
        api_key: '',
        base_url: 'https://api.anthropic.com/v1',
      },
      glm: {
        enabled: true,
        provider_type: 'glm',
        display_name: 'GLM',
        api_key: 'sk-glm',
        base_url: 'https://open.bigmodel.cn/api/paas/v4',
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
  };

  it('shows built-in provider model chips in provider configuration', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await waitFor(() => {
      expect(screen.getByText('llm.providerConfiguration.title')).toBeInTheDocument();
    });

    expect(screen.getAllByText('GPT-5.2').length).toBeGreaterThan(0);
    expect(screen.getByText('Claude Sonnet 4.6')).toBeInTheDocument();
    expect(screen.getByText('GLM-5')).toBeInTheDocument();
  });

  it('renders provider configuration before model selection', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    const providerHeading = await screen.findByText('llm.providerConfiguration.title');
    const modelHeading = screen.getByText('llm.modelSelection.title');
    expect(
      providerHeading.compareDocumentPosition(modelHeading) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it('keeps the provider workbench split on desktop and gives the detail pane its own scroll container', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    const workbench = await screen.findByTestId('llm-provider-workbench');
    const detailPane = screen.getByTestId('llm-provider-detail-pane');
    const modelSection = screen.getByTestId('llm-model-selection-section');

    expect(workbench.className).toContain('xl:grid-cols-[280px_minmax(0,1fr)]');
    expect(detailPane.className).toContain('overflow-y-auto');
    expect(modelSection.className).toContain('bg-muted/20');
  });

  it('lets user switch the core scenario model and shows vision warning', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    const coreCard = await screen.findByTestId('llm-scenario-core');
    const providerSelect = within(coreCard).getByLabelText('llm.fields.provider');

    fireEvent.change(providerSelect, { target: { value: 'glm' } });

    await waitFor(() => {
      expect(within(coreCard).getByLabelText('llm.fields.model')).toHaveValue('glm-5');
    });
    expect(screen.getByText('llm.warnings.coreVisionMissing')).toBeInTheDocument();
  });

  it('memory form disables l2-l5 when l1 off', async () => {
    const user = userEvent.setup();
    render(
      <Form initialValues={{ memory_layers: { L1: { enabled: true } } }}>
        <MemoryForm />
      </Form>
    );
    const l1Switch = screen.getAllByRole('checkbox')[0];
    await user.click(l1Switch);
    expect(await screen.findByText('L2-L5 依赖 L1')).toBeInTheDocument();
  });
});
