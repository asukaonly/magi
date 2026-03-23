import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { configApi, type LLMConfig } from '../api/modules/config';
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
              icon: 'openai',
              default_model: 'gpt-5.2',
              default_classify_model: 'gpt-4.1-mini',
              default_base_url: 'https://api.openai.com/v1',
              chat_models: [
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
              embedding_models: [
                {
                  id: 'text-embedding-3-small',
                  label: 'Text Embedding 3 Small',
                  dimensions: [1536, 512],
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
              icon: 'anthropic',
              default_model: 'claude-sonnet-4-6',
              default_base_url: 'https://api.anthropic.com/v1',
              chat_models: [
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
              display_name: 'Z.ai',
              description: 'Fast',
              icon: 'zai',
              default_model: 'glm-5',
              default_classify_model: 'glm-5',
              default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
              chat_models: [
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
              embedding_models: [
                {
                  id: 'embedding-3',
                  label: 'Embedding-3',
                  dimensions: [1024],
                },
              ],
              fields: {
                api_key: { visible: true, required: true },
                base_url: { visible: true, required: false },
              },
            },
            {
              id: 'gemini',
              display_name: 'Google Gemini',
              description: 'Multimodal models from Google',
              icon: 'gemini',
              default_model: 'gemini-2.5-flash',
              default_base_url: 'https://generativelanguage.googleapis.com/v1beta/openai',
              chat_models: [
                {
                  id: 'gemini-2.5-flash',
                  label: 'Gemini 2.5 Flash',
                  capabilities: {
                    vision: true,
                    image_output: false,
                    tool_calling: true,
                    reasoning: true,
                    embedding: false,
                  },
                  limits: {
                    context_window: 1048576,
                    max_output_tokens: 65536,
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
              id: 'deepseek',
              display_name: 'DeepSeek',
              description: 'Reasoning and coding models',
              icon: 'deepseek',
              default_model: 'deepseek-chat',
              default_base_url: 'https://api.deepseek.com',
              chat_models: [
                {
                  id: 'deepseek-chat',
                  label: 'DeepSeek Chat',
                  capabilities: {
                    vision: false,
                    image_output: false,
                    tool_calling: true,
                    reasoning: true,
                    embedding: false,
                  },
                  limits: {
                    context_window: 128000,
                    max_output_tokens: 8192,
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
              id: 'kimi',
              display_name: 'Kimi',
              description: 'Long context models from Moonshot AI',
              icon: 'kimi',
              default_model: 'moonshot-v1-32k',
              default_base_url: 'https://api.moonshot.cn/v1',
              chat_models: [
                {
                  id: 'moonshot-v1-32k',
                  label: 'Moonshot V1 32K',
                  capabilities: {
                    vision: false,
                    image_output: false,
                    tool_calling: true,
                    reasoning: true,
                    embedding: false,
                  },
                  limits: {
                    context_window: 32768,
                    max_output_tokens: 8192,
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
              id: 'minimax',
              display_name: 'MiniMax',
              description: 'General multimodal models from MiniMax',
              icon: 'minimax',
              default_model: 'MiniMax-M2.5',
              default_base_url: 'https://api.minimaxi.com/v1',
              chat_models: [
                {
                  id: 'MiniMax-M2.5',
                  label: 'MiniMax M2.5',
                  capabilities: {
                    vision: true,
                    image_output: false,
                    tool_calling: true,
                    reasoning: true,
                    embedding: false,
                  },
                  limits: {
                    context_window: 1000192,
                    max_output_tokens: 8192,
                  },
                  provider_options_example: {},
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
        display_name: 'Z.ai',
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
    model_runtime_overrides: {},
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

  it('renders the extended builtin providers with local icons in the provider list', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const providerList = await screen.findByTestId('llm-provider-list-pane');

    expect(within(providerList).getByText('Z.ai')).toBeInTheDocument();
    expect(within(providerList).getByText('Google Gemini')).toBeInTheDocument();
    expect(within(providerList).getByText('DeepSeek')).toBeInTheDocument();
    expect(within(providerList).getByText('Kimi')).toBeInTheDocument();
    expect(within(providerList).getByText('MiniMax')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-openai')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-zai')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-gemini')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-deepseek')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-kimi')).toBeInTheDocument();
    expect(within(providerList).getByTestId('llm-provider-icon-minimax')).toBeInTheDocument();
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
    expect(modelSection.className).toContain('space-y-3');
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
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode />
      </Form>
    );

    const coreCard = await screen.findByTestId('llm-scenario-core');
    const providerSelect = within(coreCard).getByLabelText('llm.fields.provider');

    await user.click(providerSelect);
    await user.click(screen.getByRole('button', { name: 'Z.ai' }));

    await waitFor(() => {
      expect(within(coreCard).getByLabelText('llm.fields.model')).toHaveTextContent('GLM-5');
    });
    expect(screen.getByText('llm.warnings.coreVisionMissing')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('llm.warnings.coreVisionMissing');
  });

  it('uses custom select controls and flat cards for model selection on the settings surface', async () => {
    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="models" showSectionIntro={false} />
      </Form>
    );

    const coreCard = await screen.findByTestId('llm-scenario-core');
    const providerField = within(coreCard).getByLabelText('llm.fields.provider');
    const modelField = within(coreCard).getByLabelText('llm.fields.model');

    expect(providerField.tagName).toBe('BUTTON');
    expect(modelField.tagName).toBe('BUTTON');
    expect(coreCard.className).not.toContain('bg-[linear-gradient');
    expect(coreCard.className).not.toContain('bg-muted/18');
  });

  it('asks for confirmation before changing embedding dimension on the settings surface', async () => {
    const user = userEvent.setup();
    const controlledValue = {
      ...llmValue,
      selections: {
        ...llmValue.selections,
        embedding: {
          provider_id: 'openai',
          model: 'text-embedding-3-small',
          embedding_dimension: 1536,
          capability_override_enabled: false,
          capabilities: {
            vision: false,
            image_output: false,
            tool_calling: false,
            reasoning: false,
            embedding: true,
          },
          limits: {
            context_window: null,
            max_output_tokens: null,
          },
          provider_options: {},
        },
      },
    } as unknown as LLMConfig;
    const onChange = vi.fn();

    render(
      <LLMForm
        quickMode={false}
        surface="settings"
        view="models"
        showSectionIntro={false}
        value={controlledValue}
        onChange={onChange}
      />
    );

    const embeddingCard = await screen.findByTestId('llm-scenario-embedding');
    const dimensionField = within(embeddingCard).getByLabelText('llm.fields.embeddingDimension');
    onChange.mockClear();

    await user.click(dimensionField);
    await user.click(screen.getByRole('button', { name: '512' }));

    expect(await screen.findByText('llm.embeddingDimensionConfirm.title')).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'llm.embeddingDimensionConfirm.cancel' }));
    expect(onChange).not.toHaveBeenCalled();

    await user.click(dimensionField);
    await user.click(screen.getByRole('button', { name: '512' }));
    await user.click(screen.getByRole('button', { name: 'llm.embeddingDimensionConfirm.confirm' }));

    expect(onChange).toHaveBeenCalled();
    const latest = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0];
    expect(latest.selections.embedding.embedding_dimension).toBe(512);
  });

  it('stores max concurrency as a shared runtime override for the selected model', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const controlledValue = {
      ...llmValue,
      model_runtime_overrides: {},
    } as unknown as LLMConfig;

    render(
      <LLMForm
        quickMode={false}
        surface="settings"
        view="models"
        showSectionIntro={false}
        value={controlledValue}
        onChange={onChange}
      />
    );

    const coreCard = await screen.findByTestId('llm-scenario-core');

    await user.click(within(coreCard).getByRole('button', { name: 'llm.showAdvanced' }));

    const maxConcurrencyField = within(coreCard).getByLabelText('llm.fields.maxConcurrency');
    await user.clear(maxConcurrencyField);
    await user.type(maxConcurrencyField, '9');

    await waitFor(() => {
      expect(onChange).toHaveBeenCalled();
    });

    const latest = onChange.mock.calls[onChange.mock.calls.length - 1]?.[0];
    expect(latest.model_runtime_overrides).toEqual({
      'openai::api.openai.com::gpt-5.2::chat': {
        max_concurrency: 9,
      },
    });
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
        embedding: {
          provider_id: '',
          model: '',
          capability_override_enabled: false,
          capabilities: {
            vision: false,
            image_output: false,
            tool_calling: false,
            reasoning: false,
            embedding: true,
          },
          limits: {
            context_window: 8192,
            max_output_tokens: 8192,
          },
          provider_options: {},
        },
      },
      model_runtime_overrides: {},
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
    expect(screen.getByLabelText('llm.fields.defaultModel')).toHaveTextContent('foo-1');
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

  it('puts custom provider identity fields before api connection fields', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));

    const displayNameField = screen.getByLabelText('llm.fields.displayName');
    const apiFormatField = screen.getByLabelText('llm.fields.apiFormat');
    const apiKeyField = screen.getByLabelText('llm.fields.apiKey');
    const baseUrlField = screen.getByLabelText('llm.fields.baseUrl');

    expect(
      displayNameField.compareDocumentPosition(apiKeyField) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      apiFormatField.compareDocumentPosition(baseUrlField) & Node.DOCUMENT_POSITION_FOLLOWING
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
    expect(defaultModelField.tagName).toBe('BUTTON');
    expect(defaultModelField).toBeDisabled();

    await user.type(screen.getByLabelText('llm.fields.modelManualEntry'), 'foo-1');
    await user.click(screen.getByRole('button', { name: 'llm.actions.addModel' }));

    expect(screen.getByLabelText('llm.fields.defaultModel').tagName).toBe('BUTTON');
    expect(screen.getByLabelText('llm.fields.defaultModel')).toHaveTextContent('foo-1');
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

  it('uses the custom provider initial as its icon glyph', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));

    const displayNameField = screen.getByLabelText('llm.fields.displayName');
    await user.clear(displayNameField);
    await user.type(displayNameField, 'Nova Proxy');

    const providerList = await screen.findByTestId('llm-provider-list-pane');
    expect(within(providerList).getByTestId('llm-provider-icon-custom')).toHaveTextContent('N');
  });

  it('does not reintroduce implicit two-column layout for custom providers on the settings surface', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));

    const customDefaultModelField = screen.getByLabelText('llm.fields.defaultModel');
    const detailPane = screen.getByTestId('llm-provider-detail-pane');

    expect(detailPane.className).not.toContain('lg:col-span-2');
    expect(customDefaultModelField).toBeInTheDocument();
  });

  it('uses custom select controls for custom provider fields on the settings surface', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    await user.click(await screen.findByText('llm.actions.addCustomProvider'));

    expect(screen.getByLabelText('llm.fields.apiFormat').tagName).toBe('BUTTON');
    expect(screen.getByLabelText('llm.fields.defaultModel').tagName).toBe('BUTTON');
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
    await user.click(apiFormatSelect);

    expect(screen.queryByRole('button', { name: 'llm.apiFormatOptions.custom' })).not.toBeInTheDocument();
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
    expect(screen.getByLabelText('llm.fields.defaultModel')).toHaveTextContent('fetched-model-1');
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

  it('lets users reveal and hide provider api keys locally', async () => {
    const user = userEvent.setup();

    render(
      <Form initialValues={{ llm: llmValue }}>
        <LLMForm quickMode={false} surface="settings" view="providers" showSectionIntro={false} />
      </Form>
    );

    const apiKeyField = await screen.findByLabelText('llm.fields.apiKey');
    const fieldWrapper = apiKeyField.parentElement?.parentElement;

    expect(apiKeyField).toHaveAttribute('type', 'password');

    const toggleButton = within(fieldWrapper as HTMLElement).getByRole('button');
    await user.click(toggleButton);
    expect(apiKeyField).toHaveAttribute('type', 'text');

    await user.click(toggleButton);
    expect(apiKeyField).toHaveAttribute('type', 'password');
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
    await user.click((within(providerList).getByText('Z.ai') as HTMLElement).closest('button') as HTMLButtonElement);
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

  it('memory form warns when l1 is turned off', async () => {
    const user = userEvent.setup();
    render(
      <Form
        initialValues={{
          memory: {
            l0: { enabled: true, checkpoint_interval_seconds: 30, runtime_replay_include_l0_only: false },
            l1: { enabled: true, retention_days: 7, t1_importance_enabled: true, vectors_enabled: true },
            l2: {
              enabled: true,
              batch_flush_interval_seconds: 60,
              llm_extraction_enabled: true,
              auto_extract_relations: true,
              conflict_arbitration_enabled: true,
              conflict_arbitration_min_confidence: 0.85,
            },
            l3: {
              enabled: true,
              vectors_enabled: true,
              llm_summary_enabled: true,
              temporal_llm_timeout_seconds: 3.0,
              temporal_llm_min_event_count: 2,
              summary_interval_minutes: 60,
            },
            l4: { enabled: true, vectors_enabled: true, skill_extraction_enabled: true },
          },
        }}
      >
        <MemoryForm />
      </Form>
    );
    const l1Switch = screen.getByRole('checkbox', { name: /settings\.memory\.fields\.enable_l1\.label/i });
    await user.click(l1Switch);
    expect(await screen.findByText('settings.memory.form.l1DependencyTitle')).toBeInTheDocument();
  });
});
