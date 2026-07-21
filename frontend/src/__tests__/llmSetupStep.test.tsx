import { useState } from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { configApi, DEFAULT_SYSTEM_CONFIG, type LLMConfig } from '@/api/modules/config';
import {
  LLMSetupStep,
  type LLMConnectionTestState,
} from '@/components/onboarding/LLMSetupStep';

const { reducedMotionMock } = vi.hoisted(() => ({
  reducedMotionMock: vi.fn(() => false),
}));

vi.mock('framer-motion', async (importOriginal) => {
  const actual = await importOriginal<typeof import('framer-motion')>();
  return {
    ...actual,
    useReducedMotion: () => reducedMotionMock(),
  };
});

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const chatCapabilities = {
  vision: false,
  image_output: false,
  tool_calling: true,
  reasoning: true,
};

const embeddingCapabilities = {
  vision: false,
  image_output: false,
  tool_calling: false,
  reasoning: false,
  embedding: true,
};

function catalog() {
  return {
    providers: [
      {
        id: 'openai',
        provider_type: 'openai',
        source: 'builtin',
        display_name: 'OpenAI',
        default_model: 'gpt-4o',
        default_classify_model: 'gpt-4o-mini',
        default_base_url: 'https://api.openai.com/v1',
        api_format: 'openai',
        resolved_chat_models: [
          {
            id: 'gpt-4o',
            capabilities: chatCapabilities,
            limits: {},
            hidden: false,
            preferred: true,
            source: 'builtin',
            input_modalities: ['text'],
            output_modalities: ['text'],
          },
          {
            id: 'gpt-4o-mini',
            capabilities: chatCapabilities,
            limits: {},
            hidden: false,
            preferred: false,
            source: 'builtin',
            input_modalities: ['text'],
            output_modalities: ['text'],
          },
        ],
        resolved_embedding_models: [
          {
            id: 'text-embedding-3-small',
            dimensions: [1536],
            capabilities: embeddingCapabilities,
            hidden: false,
            preferred: true,
            source: 'builtin',
            input_modalities: ['text'],
            output_modalities: ['embedding'],
          },
        ],
      },
      {
        id: 'anthropic',
        provider_type: 'anthropic',
        source: 'builtin',
        display_name: 'Anthropic',
        default_model: 'claude-sonnet-4-5',
        default_classify_model: 'claude-haiku-4-5',
        default_base_url: 'https://api.anthropic.com/v1',
        api_format: 'anthropic',
        resolved_chat_models: [
          {
            id: 'claude-sonnet-4-5',
            capabilities: chatCapabilities,
            limits: {},
            hidden: false,
            preferred: true,
            source: 'builtin',
            input_modalities: ['text'],
            output_modalities: ['text'],
          },
          {
            id: 'claude-haiku-4-5',
            capabilities: chatCapabilities,
            limits: {},
            hidden: false,
            preferred: false,
            source: 'builtin',
            input_modalities: ['text'],
            output_modalities: ['text'],
          },
        ],
        resolved_embedding_models: [],
      },
      {
        id: 'glm',
        provider_type: 'glm',
        source: 'builtin',
        display_name: 'Z.ai',
        default_model: 'glm-5',
        default_classify_model: 'glm-5',
        default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
        api_format: 'openai',
        resolved_chat_models: [
          {
            id: 'glm-5',
            capabilities: chatCapabilities,
            limits: {},
            hidden: false,
            preferred: true,
            source: 'builtin',
            input_modalities: ['text'],
            output_modalities: ['text'],
          },
        ],
        resolved_embedding_models: [
          {
            id: 'embedding-3',
            dimensions: [1024],
            capabilities: embeddingCapabilities,
            hidden: false,
            preferred: true,
            source: 'builtin',
            input_modalities: ['text'],
            output_modalities: ['embedding'],
          },
        ],
        plans: [
          {
            id: 'codeplan',
            display_name: 'Z.ai CodePlan',
            default_model: 'glm-5',
            default_classify_model: 'glm-5-code',
            default_base_url: 'https://open.bigmodel.cn/api/coding/paas/v4',
            endpoints: [
              {
                id: 'china',
                label: 'China',
                country: 'China',
                base_url: 'https://open.bigmodel.cn/api/coding/paas/v4',
                api_format: 'openai',
              },
              {
                id: 'global',
                label: 'Global',
                base_url: 'https://api.z.ai/api/coding/paas/v4',
                api_format: 'openai',
              },
            ],
            embedding_models: [],
            image_generation_models: [],
            resolved_chat_models: [
              {
                id: 'glm-5',
                capabilities: chatCapabilities,
                limits: {},
                hidden: false,
                preferred: true,
                source: 'builtin',
                input_modalities: ['text'],
                output_modalities: ['text'],
              },
              {
                id: 'glm-5-code',
                capabilities: chatCapabilities,
                limits: {},
                hidden: false,
                preferred: false,
                source: 'builtin',
                input_modalities: ['text'],
                output_modalities: ['text'],
              },
            ],
            resolved_embedding_models: [],
            resolved_image_generation_models: [],
          },
        ],
      },
    ],
  };
}

function customTemplate() {
  return {
    template: {
      enabled: true,
      display_name: 'Custom Provider',
      fields: {
        api_format: { visible: true, required: true, options: ['openai', 'anthropic'] },
      },
      capabilities: {
        vision: false,
        image_output: false,
        tool_calling: true,
        reasoning: true,
        embedding: false,
      },
      limits: {},
      provider_options_example: {},
    },
    defaults: {
      enabled: true,
      provider_type: 'custom',
      display_name: 'Custom Provider',
      api_key: '',
      base_url: '',
      services: {
        chat: { enabled: true, api_key: '', base_url: '' },
        embedding: { enabled: false, api_key: '', base_url: '' },
        image_generation: { enabled: false, api_key: '', base_url: '', timeout: 180, native_protocol: null },
        tts: { enabled: false, api_key: '', base_url: '', model: '', voice: '', response_format: '' },
      },
      api_format: 'openai',
      custom_models: [],
      custom_default_model: '',
      model_metadata_overrides: {},
    },
  };
}

function emptyValue(): LLMConfig {
  return structuredClone(DEFAULT_SYSTEM_CONFIG.llm);
}

function Harness({
  initial = emptyValue(),
  onValid,
  onChangeSpy,
  connectionTestState = { loading: false, error: null, result: null },
  onTestConnection = async () => true,
}: {
  initial?: LLMConfig;
  onValid?: (valid: boolean) => void;
  onChangeSpy?: (value: LLMConfig) => void;
  connectionTestState?: LLMConnectionTestState;
  onTestConnection?: (force?: boolean) => Promise<boolean>;
}) {
  const [value, setValue] = useState(initial);
  return (
    <LLMSetupStep
      value={value}
      onValid={onValid}
      connectionTestState={connectionTestState}
      onTestConnection={onTestConnection}
      onChange={(next) => {
        onChangeSpy?.(next);
        setValue(next);
      }}
    />
  );
}

describe('LLMSetupStep', () => {
  beforeEach(() => {
    reducedMotionMock.mockReturnValue(false);
    vi.spyOn(configApi, 'resolveLLMProviderCatalog').mockResolvedValue(catalog() as any);
    vi.spyOn(configApi, 'getLLMCustomProviderTemplate').mockResolvedValue(customTemplate() as any);
    vi.spyOn(configApi, 'testLLMProviderConnection').mockResolvedValue({
      model: 'gpt-4o',
      latency_ms: 42,
      preview: 'hello',
    });
  });

  it('renders flat provider cards and keeps optional settings collapsed', async () => {
    render(<Harness />);
    expect(await screen.findByTestId('llm-setup-provider-openai')).toBeInTheDocument();
    expect(screen.getByTestId('llm-setup-provider-custom')).toBeInTheDocument();
    expect(screen.queryByTestId('llm-setup-core-model')).not.toBeInTheDocument();
  });

  it('renders provider cards with only icon and name copy', async () => {
    render(<Harness />);

    const openAiCard = await screen.findByTestId('llm-setup-provider-openai');

    expect(openAiCard).toHaveTextContent('llm.providers.openai.name');
    expect(openAiCard).not.toHaveTextContent('llm.providers.openai.desc');
  });

  it('collapses the provider grid into a selected-provider summary', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const openAiCard = await screen.findByTestId('llm-setup-provider-openai');
    expect(openAiCard).toHaveAttribute('aria-pressed', 'false');
    expect(openAiCard).not.toHaveClass('border');

    await user.click(openAiCard);

    const providerSummary = await screen.findByTestId('llm-setup-provider-summary');
    expect(providerSummary).toHaveTextContent(
      'llm.providers.openai.name',
    );
    expect(providerSummary).not.toHaveClass('rounded-xl', 'bg-accent/75');
    expect(within(providerSummary).getByTestId('llm-provider-icon-openai')).toHaveClass(
      'rounded-sm',
      'shadow-none',
    );
    expect(screen.getByRole('button', { name: 'llmSetup.changeProvider' })).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByTestId('llm-setup-provider-anthropic')).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole('button', { name: 'llmSetup.changeProvider' }));
    const selectedOpenAiCard = await screen.findByTestId('llm-setup-provider-openai');
    expect(selectedOpenAiCard).toHaveAttribute('aria-pressed', 'true');
    // 选中态:中性纸面 + 低调的 primary 细描边(不再用彩色填充)。
    expect(selectedOpenAiCard).toHaveClass(
      'bg-card',
      'shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.38)]',
    );
  });

  it('returns to the current setup without losing entered credentials', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(await screen.findByTestId('llm-setup-api-key'), 'sk-kept');
    await user.click(screen.getByRole('button', { name: 'llmSetup.changeProvider' }));
    await user.click(await screen.findByRole('button', { name: 'llmSetup.backToProviderConfig' }));

    expect(await screen.findByTestId('llm-setup-api-key')).toHaveValue('sk-kept');
  });

  it('keeps provider switching usable when motion is reduced', async () => {
    const user = userEvent.setup();
    reducedMotionMock.mockReturnValue(true);
    render(<Harness />);

    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    expect(await screen.findByTestId('llm-setup-provider-summary')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'llmSetup.changeProvider' }));
    expect(await screen.findByTestId('llm-setup-provider-anthropic')).toBeInTheDocument();
  });

  it('uses compact single-line provider cards after descriptions are removed', async () => {
    render(<Harness />);

    const openAiCard = await screen.findByTestId('llm-setup-provider-openai');

    expect(openAiCard).toHaveClass('min-h-[64px]');
    expect(openAiCard).toHaveClass('items-center');
    expect(openAiCard).not.toHaveClass('min-h-[96px]');
    expect(openAiCard).not.toHaveClass('items-start');
  });

  it('reports valid once a builtin provider has an API key', async () => {
    const user = userEvent.setup();
    const onValid = vi.fn();
    const onChangeSpy = vi.fn();
    render(<Harness onValid={onValid} onChangeSpy={onChangeSpy} />);

    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    expect(onValid).toHaveBeenLastCalledWith(false);

    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    await waitFor(() => expect(onValid).toHaveBeenLastCalledWith(true));

    const latest = onChangeSpy.mock.calls[onChangeSpy.mock.calls.length - 1]?.[0] as LLMConfig;
    expect(latest.providers.openai.api_key).toBe('sk-test');
    expect(latest.selections.core.model).toBe('gpt-4o');
    expect(latest.selections.context_decider.model).toBe('gpt-4o-mini');
  });

  it('tests the selected provider from onboarding before continuing', async () => {
    const user = userEvent.setup();
    const onTestConnection = vi.fn().mockResolvedValue(true);
    render(<Harness onTestConnection={onTestConnection} />);

    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.type(screen.getByTestId('llm-setup-api-key'), 'sk-test');
    await user.click(screen.getByRole('button', { name: 'llmSetup.verifyConnection' }));

    await waitFor(() => expect(onTestConnection).toHaveBeenCalledWith(true));
  });

  it('renders a successful connection result owned by the onboarding flow', async () => {
    const user = userEvent.setup();
    render(
      <Harness
        connectionTestState={{
          loading: false,
          error: null,
          result: { model: 'gpt-4o', latency_ms: 42, preview: 'hello' },
        }}
      />,
    );

    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    expect(await screen.findByText('llm.providerConfiguration.testSuccess')).toBeInTheDocument();
  });

  it('supports keyless OpenAI-compatible relay setup with base URL and model ID', async () => {
    const user = userEvent.setup();
    const onValid = vi.fn();
    const onChangeSpy = vi.fn();
    render(<Harness onValid={onValid} onChangeSpy={onChangeSpy} />);

    await user.click(await screen.findByTestId('llm-setup-provider-custom'));
    await user.type(screen.getByTestId('llm-setup-base-url'), 'http://localhost:3000/v1');
    await user.type(screen.getByTestId('llm-setup-custom-model'), 'gpt-4o-mini');

    await waitFor(() => expect(onValid).toHaveBeenLastCalledWith(true));
    const latest = onChangeSpy.mock.calls[onChangeSpy.mock.calls.length - 1]?.[0] as LLMConfig;
    expect(latest.providers.custom.provider_type).toBe('custom');
    expect(latest.providers.custom.api_key).toBe('');
    expect(latest.providers.custom.base_url).toBe('http://localhost:3000/v1');
    expect(latest.providers.custom.custom_models).toContain('gpt-4o-mini');
    expect(latest.selections.core.model).toBe('gpt-4o-mini');
  });

  it('prioritizes required custom connection fields and defers the display name', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(await screen.findByTestId('llm-setup-provider-custom'));

    const baseUrl = screen.getByTestId('llm-setup-base-url');
    const coreModel = screen.getByTestId('llm-setup-custom-model');
    const apiKey = screen.getByTestId('llm-setup-api-key');
    expect(baseUrl.compareDocumentPosition(coreModel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(coreModel.compareDocumentPosition(apiKey) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByTestId('llm-setup-custom-name')).not.toBeInTheDocument();

    const verifyConnection = screen.getByRole('button', { name: 'llmSetup.verifyConnection' });
    expect(verifyConnection).toHaveClass('bg-muted/45');
    expect(verifyConnection).not.toHaveClass('border');

    await user.click(screen.getByTestId('llm-setup-advanced-toggle'));
    expect(screen.getByTestId('llm-setup-custom-name')).toBeInTheDocument();
  });

  it('requires an API key when a custom provider uses the Anthropic format', async () => {
    const user = userEvent.setup();
    const onValid = vi.fn();
    render(<Harness onValid={onValid} />);

    await user.click(await screen.findByTestId('llm-setup-provider-custom'));
    await user.type(screen.getByTestId('llm-setup-base-url'), 'https://anthropic-relay.example.com');
    await user.type(screen.getByTestId('llm-setup-custom-model'), 'claude-local');
    await user.click(screen.getByTestId('llm-setup-advanced-toggle'));
    await user.selectOptions(screen.getByTestId('llm-setup-api-format'), 'anthropic');

    await waitFor(() => {
      expect(onValid).toHaveBeenLastCalledWith(false);
    });
    expect(screen.getByText('llmSetup.apiKeyLabel')).toBeInTheDocument();
    expect(screen.queryByText('llmSetup.apiKeyOptionalLabel')).not.toBeInTheDocument();

    await user.type(screen.getByTestId('llm-setup-api-key'), 'relay-key');
    await waitFor(() => {
      expect(onValid).toHaveBeenLastCalledWith(true);
    });
  });

  it('reveals optional model routing fields from the advanced toggle', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(await screen.findByTestId('llm-setup-provider-openai'));
    await user.click(screen.getByTestId('llm-setup-advanced-toggle'));

    expect(screen.getByTestId('llm-setup-core-model')).toBeInTheDocument();
    expect(screen.getByTestId('llm-setup-fast-model')).toBeInTheDocument();
  });

  it('shows the vector-model row when the selected provider has no native vector model', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(await screen.findByTestId('llm-setup-provider-anthropic'));

    const vectorModelHint = screen.getByTestId('llm-setup-embedding-row');
    expect(vectorModelHint).toBeInTheDocument();
    expect(vectorModelHint).toHaveAttribute('role', 'status');
    expect(vectorModelHint).toHaveClass('bg-secondary/55', 'px-3', 'py-2.5');
    expect(vectorModelHint).not.toHaveClass('border', 'border-amber-200');
    expect(screen.getByText('llmSetup.memoryModelMissingTitle')).toBeInTheDocument();
    expect(screen.getByText('llmSetup.memoryModelMissingBody')).toBeInTheDocument();
  });

  it('warns that a CodePlan billing plan does not include a vector model', async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(await screen.findByTestId('llm-setup-provider-glm'));
    expect(screen.queryByTestId('llm-setup-embedding-row')).not.toBeInTheDocument();

    await user.click(screen.getByText('llm.providerPlans.default'));
    await user.click(await screen.findByText('Z.ai CodePlan'));

    expect(await screen.findByText('llmSetup.memoryModelPlanMissingTitle')).toBeInTheDocument();
    expect(screen.getByText('llmSetup.memoryModelPlanMissingBody')).toBeInTheDocument();
  });

  it('fills and switches provider plan endpoint base URLs', async () => {
    const user = userEvent.setup();
    const onChangeSpy = vi.fn();
    render(<Harness onChangeSpy={onChangeSpy} />);

    await user.click(await screen.findByTestId('llm-setup-provider-glm'));
    await user.click(screen.getByText('llm.providerPlans.default'));
    await user.click(await screen.findByText('Z.ai CodePlan'));
    await user.click(await screen.findByText('China'));
    await user.click(await screen.findByText('Global'));
    await user.click(screen.getByTestId('llm-setup-advanced-toggle'));

    expect(screen.getByTestId('llm-setup-base-url')).toHaveValue(
      'https://api.z.ai/api/coding/paas/v4'
    );

    await waitFor(() => {
      const latest = onChangeSpy.mock.calls[onChangeSpy.mock.calls.length - 1]?.[0] as LLMConfig;
      expect(latest.providers.glm.provider_plan).toBe('codeplan');
      expect(latest.providers.glm.base_url).toBe('https://api.z.ai/api/coding/paas/v4');
    });
  });
});
