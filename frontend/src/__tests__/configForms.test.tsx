import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { configApi } from '../api/modules/config';
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
              default_base_url: 'https://api.openai.com/v1',
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
              default_base_url: 'https://api.anthropic.com/v1',
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
              default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
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
              api_format: { visible: true, required: true, options: ['openai', 'anthropic'] },
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
      discoverLLMProviderModels: vi.fn().mockResolvedValue({
        data: {
          models: ['fetched-model-1', 'fetched-model-2'],
          default_model: 'fetched-model-1',
        },
      }),
      testLLMProviderConnection: vi.fn().mockResolvedValue({
        data: {
          model: 'gpt-5.2',
          latency_ms: 42,
          preview: 'hello',
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

  it('keeps the provider list compact and pushes details to the workbench pane', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await waitFor(() => {
      expect(screen.getByText('llm.providerConfiguration.title')).toBeInTheDocument();
    });

    const providerList = screen.getByTestId('llm-provider-list-pane');

    expect(within(providerList).getByText('OpenAI')).toBeInTheDocument();
    expect(within(providerList).queryByText('General purpose')).not.toBeInTheDocument();
    expect(within(providerList).queryByText('GPT-5.2')).not.toBeInTheDocument();
    expect(screen.getByText('llm.providerConfiguration.availableModels')).toBeInTheDocument();
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

    expect(workbench.className).toContain('xl:grid-cols-[220px_minmax(0,1fr)]');
    expect(workbench.className).toContain('md:h-[clamp(440px,56vh,680px)]');
    expect(detailPane.className).toContain('overflow-y-auto');
    expect(modelSection.className).toContain('border-t');
  });

  it('uses a switch control for provider enablement in the detail pane', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await waitFor(() => {
      expect(screen.getByTestId('llm-provider-detail-pane')).toBeInTheDocument();
    });

    expect(screen.getByRole('switch', { name: 'llm.fields.enabled' })).toBeInTheDocument();
  });

  it('keeps provider test actions compact without extra explanatory copy', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await waitFor(() => {
      expect(screen.getByTestId('llm-provider-detail-pane')).toBeInTheDocument();
    });

    expect(screen.getByRole('button', { name: 'llm.actions.testConnection' })).toBeInTheDocument();
    expect(screen.queryByText('llm.providerConfiguration.testTitle')).not.toBeInTheDocument();
    expect(screen.queryByText('llm.providerConfiguration.testDesc')).not.toBeInTheDocument();
  });

  it('does not prefill default base url for inactive built-in providers', async () => {
    const user = userEvent.setup();
    const valueWithoutAnthropicBaseUrl = {
      ...llmValue,
      providers: {
        ...llmValue.providers,
        anthropic: {
          ...llmValue.providers.anthropic,
          base_url: '',
        },
      },
    };

    render(
      <Form initialValues={{ llm: valueWithoutAnthropicBaseUrl }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click((await screen.findByText('Anthropic')).closest('button') as HTMLButtonElement);

    expect(screen.getByLabelText('llm.fields.baseUrl')).toHaveValue('');
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

  it('does not auto-select a provider or model when onboarding starts with all providers disabled', async () => {
    const onChange = vi.fn();
    const blankValue = {
      providers: {},
      selections: {
        context_decider: {
          provider_id: '',
          model: '',
          capability_override_enabled: false,
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
          provider_options: {},
        },
        core: {
          provider_id: '',
          model: '',
          capability_override_enabled: false,
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
          provider_options: {},
        },
      },
    };

    render(<LLMForm quickMode={false} value={blankValue} onChange={onChange} />);

    await waitFor(() => {
      expect(screen.getByText('llm.providerConfiguration.title')).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(onChange).toHaveBeenCalled();
    });

    const latest = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0];

    expect(latest.providers.openai.enabled).toBe(false);
    expect(latest.providers.anthropic.enabled).toBe(false);
    expect(latest.providers.glm.enabled).toBe(false);
    expect(latest.selections.context_decider.provider_id).toBe('');
    expect(latest.selections.context_decider.model).toBe('');
    expect(latest.selections.core.provider_id).toBe('');
    expect(latest.selections.core.model).toBe('');
  });

  it('lets users add a custom provider model manually', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));
    await user.type(screen.getByLabelText('llm.fields.modelManualEntry'), 'foo-1');
    await user.click(screen.getByRole('button', { name: 'llm.actions.addModel' }));

    expect(screen.getAllByText('foo-1').length).toBeGreaterThan(0);
    expect(screen.getByLabelText('llm.fields.defaultModel')).toHaveValue('foo-1');
  });

  it('lets users remove a custom provider and falls back to builtin providers', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));
    expect(screen.getByDisplayValue('llm.customProviderDefaultName')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'llm.actions.removeProvider' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'llm.actions.removeProvider' }));

    await waitFor(() => {
      expect(screen.queryByDisplayValue('llm.customProviderDefaultName')).not.toBeInTheDocument();
    });
    expect(screen.getByLabelText('llm.fields.apiKey')).toHaveValue('sk-openai');
    expect(screen.queryByRole('button', { name: 'llm.actions.removeProvider' })).not.toBeInTheDocument();
  });

  it('puts api connection fields before model management for custom providers', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));

    const apiKeyField = screen.getByLabelText('llm.fields.apiKey');
    const baseUrlField = screen.getByLabelText('llm.fields.baseUrl');
    const modelEntryField = screen.getByLabelText('llm.fields.modelManualEntry');

    expect(
      apiKeyField.compareDocumentPosition(modelEntryField) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      baseUrlField.compareDocumentPosition(modelEntryField) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it('uses a selectable default model instead of free text for custom providers', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));

    const defaultModelField = screen.getByLabelText('llm.fields.defaultModel');
    expect(defaultModelField.tagName).toBe('SELECT');
    expect(defaultModelField).toBeDisabled();

    await user.type(screen.getByLabelText('llm.fields.modelManualEntry'), 'foo-1');
    await user.click(screen.getByRole('button', { name: 'llm.actions.addModel' }));

    expect(screen.getByLabelText('llm.fields.defaultModel').tagName).toBe('SELECT');
    expect(screen.getByLabelText('llm.fields.defaultModel')).toHaveValue('foo-1');
  });

  it('shows default model before model entry and adds a model id placeholder for custom providers', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));

    const defaultModelField = screen.getByLabelText('llm.fields.defaultModel');
    const modelEntryField = screen.getByLabelText('llm.fields.modelManualEntry');

    expect(modelEntryField).toHaveAttribute('placeholder', 'llm.fields.modelManualEntryPlaceholder');
    expect(
      defaultModelField.compareDocumentPosition(modelEntryField) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it('removes the ambiguous custom api format option', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));

    const apiFormatSelect = screen.getByLabelText('llm.fields.apiFormat');

    expect(within(apiFormatSelect).queryByRole('option', { name: 'llm.apiFormatOptions.custom' })).not.toBeInTheDocument();
  });

  it('fetches custom provider models on demand', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));
    await user.type(screen.getByLabelText('llm.fields.baseUrl'), 'https://proxy.example.com/v1');
    await user.click(screen.getByRole('button', { name: 'llm.actions.fetchModels' }));

    await waitFor(() => {
      expect(screen.getAllByText('fetched-model-1').length).toBeGreaterThan(0);
    });
    expect(screen.getByLabelText('llm.fields.defaultModel')).toHaveValue('fetched-model-1');
    expect(configApi.discoverLLMProviderModels).toHaveBeenCalled();
  });

  it('tests the active provider with current draft credentials', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    await user.clear(await screen.findByLabelText('llm.fields.apiKey'));
    await user.type(screen.getByLabelText('llm.fields.apiKey'), 'sk-draft-openai');
    await user.click(screen.getByRole('button', { name: 'llm.actions.testConnection' }));

    await waitFor(() => {
      expect(configApi.testLLMProviderConnection).toHaveBeenCalledWith({
        provider_id: 'openai',
        model: 'gpt-5.2',
        provider: expect.objectContaining({
          provider_type: 'openai',
          api_key: 'sk-draft-openai',
          base_url: 'https://api.openai.com/v1',
        }),
      });
    });

    expect(screen.getByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();
  });

  it('uses the registry default base url when testing a built-in provider with a blank field', async () => {
    const user = userEvent.setup();
    const glmWithoutBaseUrl = {
      ...llmValue,
      selections: {
        ...llmValue.selections,
        context_decider: {
          ...llmValue.selections.context_decider,
          provider_id: 'glm',
          model: 'glm-5',
        },
        core: {
          ...llmValue.selections.core,
          provider_id: 'glm',
          model: 'glm-5',
        },
      },
      providers: {
        ...llmValue.providers,
        glm: {
          ...llmValue.providers.glm,
          base_url: '',
        },
      },
    };

    render(
      <Form initialValues={{ llm: glmWithoutBaseUrl }}>
        <LLMForm quickMode />
      </Form>
    );

    const providerList = await screen.findByTestId('llm-provider-list-pane');
    await user.click((within(providerList).getByText('GLM') as HTMLElement).closest('button') as HTMLButtonElement);
    await user.click(screen.getByRole('button', { name: 'llm.actions.testConnection' }));

    await waitFor(() => {
      expect(configApi.testLLMProviderConnection).toHaveBeenCalledWith({
        provider_id: 'glm',
        model: 'glm-5',
        provider: expect.objectContaining({
          provider_type: 'glm',
          base_url: 'https://open.bigmodel.cn/api/paas/v4',
        }),
      });
    });
  });

  it('stacks provider detail fields in a single column on the settings surface', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const apiKeyField = await screen.findByLabelText('llm.fields.apiKey');
    const fieldGrid = apiKeyField.closest('div.grid');
    const availableModels = screen.getByText('llm.providerConfiguration.availableModels').parentElement;

    expect(fieldGrid).toHaveClass('grid');
    expect(fieldGrid?.className).not.toContain('lg:grid-cols-2');
    expect(availableModels?.className).not.toContain('lg:col-span-2');
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
