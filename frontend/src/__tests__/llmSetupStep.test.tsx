import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { LLMSetupStep } from '@/components/onboarding/LLMSetupStep';
import type { LLMConfig } from '@/api/modules/config';

// Mock i18n so the test isn't bound to translation copy churn.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// LLMSetupStep is a thin wrapper over LLMForm (the same component Settings
// uses). Mock LLMForm and capture the `view` prop so we can assert the
// advanced toggle wiring without standing up the full provider catalog.
const llmFormSpy = vi.fn();
vi.mock('@/components/config-forms/LLMForm', () => ({
  default: (props: Record<string, unknown>) => {
    llmFormSpy(props);
    return <div data-testid="llm-form" data-view={String(props.view)} />;
  },
}));

function emptyValue(): LLMConfig {
  return { providers: {}, selections: {} as any, model_runtime_overrides: {} };
}

function readyValue(): LLMConfig {
  return {
    providers: {
      openai: {
        enabled: true,
        provider_type: 'openai',
        api_key: 'sk-test',
        services: { chat: { enabled: true, api_key: 'sk-test', base_url: '' } },
      } as any,
    },
    selections: {
      core: { provider_id: 'openai', model: 'gpt-4o' },
      context_decider: { provider_id: 'openai', model: 'gpt-4o-mini' },
    } as any,
    model_runtime_overrides: {},
  };
}

function anthropicCoreNoEmbedding(): LLMConfig {
  return {
    providers: {
      anthropic: {
        enabled: true,
        provider_type: 'anthropic',
        api_key: 'sk-ant',
        services: { chat: { enabled: true, api_key: 'sk-ant', base_url: '' } },
      } as any,
    },
    selections: {
      core: { provider_id: 'anthropic', model: 'claude-sonnet-4-5' },
      context_decider: { provider_id: 'anthropic', model: 'claude-haiku-4-5' },
    } as any,
    model_runtime_overrides: {},
  };
}

describe('LLMSetupStep', () => {
  beforeEach(() => llmFormSpy.mockClear());

  it('renders LLMForm with view="providers" by default (advanced collapsed)', () => {
    render(<LLMSetupStep value={emptyValue()} onChange={() => {}} />);
    expect(screen.getByTestId('llm-form')).toHaveAttribute('data-view', 'providers');
  });

  it('advanced toggle flips LLMForm view to "all" and back', async () => {
    render(<LLMSetupStep value={emptyValue()} onChange={() => {}} />);
    const toggle = screen.getByTestId('llm-setup-advanced-toggle');
    await userEvent.click(toggle);
    expect(screen.getByTestId('llm-form')).toHaveAttribute('data-view', 'all');
    await userEvent.click(toggle);
    expect(screen.getByTestId('llm-form')).toHaveAttribute('data-view', 'providers');
  });

  it('reports valid=false for an empty config', () => {
    const onValid = vi.fn();
    render(<LLMSetupStep value={emptyValue()} onChange={() => {}} onValid={onValid} />);
    expect(onValid).toHaveBeenLastCalledWith(false);
  });

  it('reports valid=true when an enabled provider with key + core + context_decider exist', () => {
    const onValid = vi.fn();
    render(<LLMSetupStep value={readyValue()} onChange={() => {}} onValid={onValid} />);
    expect(onValid).toHaveBeenLastCalledWith(true);
  });

  it('shows the embedding-fallback row when the core provider has null embedding (Anthropic)', () => {
    render(<LLMSetupStep value={anthropicCoreNoEmbedding()} onChange={() => {}} />);
    expect(screen.getByTestId('llm-setup-embedding-row')).toBeInTheDocument();
  });

  it('hides the embedding-fallback row once an embedding selection exists', () => {
    const value = anthropicCoreNoEmbedding();
    (value.selections as any).embedding = {
      provider_id: 'openai',
      model: 'text-embedding-3-small',
    };
    render(<LLMSetupStep value={value} onChange={() => {}} />);
    expect(screen.queryByTestId('llm-setup-embedding-row')).not.toBeInTheDocument();
  });
});
