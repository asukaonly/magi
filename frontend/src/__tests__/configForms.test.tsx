import { render, screen, waitFor } from '@testing-library/react';
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
              ],
              fields: {
                model: { visible: true, required: true },
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

  it('quick mode should hide advanced llm fields until expanded', async () => {
    render(
      <Form initialValues={{ llm: { provider: 'openai', model: 'gpt-5.2' } }}>
        <LLMForm quickMode />
      </Form>
    );

    await waitFor(() => {
      expect(screen.getByText('llm.summaryEyebrow')).toBeInTheDocument();
    });

    expect(screen.queryByText('llm.providerOptionsLabel')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /llm\.advancedTitle/i }));
    expect(screen.getByText('llm.providerOptionsLabel')).toBeInTheDocument();
  });

  it('shows capability summary from the selected model', async () => {
    render(
      <Form initialValues={{ llm: { provider: 'openai', model: 'gpt-5.2' } }}>
        <LLMForm quickMode />
      </Form>
    );

    expect(await screen.findByText('llm.capabilities.vision')).toBeInTheDocument();
    expect(screen.getAllByText('llm.capabilityEnabled').length).toBeGreaterThan(0);
    expect(screen.getByText(/llm\.contextWindowLabelShort/)).toBeInTheDocument();
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
