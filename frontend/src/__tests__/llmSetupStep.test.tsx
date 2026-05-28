import { useState } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { LLMSetupStep } from '@/components/onboarding/LLMSetupStep';
import { RECOMMENDED_MODELS } from '@/constants/llm';
import type { LLMConfig, LLMProviderRegistry } from '@/api/modules/config';

// Mock i18n so the test isn't bound to translation copy churn.
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// Mock LLMProviderConfigurationSection to a simple controlled select so the
// test does not depend on the full internal UI. We use the actual prop names
// the real component expects: `activeProviderId`, `onActiveProviderChange`,
// `onSetProvider`.
vi.mock('@/components/config-forms/LLMProviderConfigurationSection', () => ({
  LLMProviderConfigurationSection: ({
    value,
    activeProviderId,
    onActiveProviderChange,
    onProviderChange,
    onSetProvider,
    registry,
  }: any) => {
    const providerIds = registry.providers.map((p: any) => p.id);
    return (
      <div>
        <label htmlFor="provider-select">provider</label>
        <select
          id="provider-select"
          value={activeProviderId ?? ''}
          onChange={(e) => {
            const pid = e.target.value;
            if (!pid) return;
            // Mimic what the real component does when the user adds a
            // provider via the dialog: it calls onSetProvider with a fresh
            // provider config, then onActiveProviderChange.
            onSetProvider?.(pid, {
              enabled: true,
              provider_type: pid,
              display_name: pid,
              api_key: '',
              base_url: '',
              services: {
                chat: { enabled: true, api_key: '', base_url: '' },
                embedding: { enabled: false, api_key: '', base_url: '' },
                image_generation: { enabled: false, api_key: '', base_url: '' },
                tts: { enabled: false, api_key: '', base_url: '' },
              },
              api_format: 'openai',
              custom_models: [],
              custom_default_model: '',
              model_metadata_overrides: {},
            });
            onActiveProviderChange?.(pid);
          }}
        >
          <option value="">--</option>
          {providerIds.map((pid: string) => (
            <option key={pid} value={pid}>
              {pid}
            </option>
          ))}
        </select>
        <label htmlFor="api-key-input">api key</label>
        <input
          id="api-key-input"
          value={value.providers?.[activeProviderId ?? '']?.api_key ?? ''}
          onChange={(e) => {
            const pid = activeProviderId;
            if (!pid) return;
            onProviderChange?.(pid, (draft: any) => {
              draft.api_key = e.target.value;
              draft.enabled = e.target.value.length > 0;
            });
          }}
        />
      </div>
    );
  },
}));

const buildRegistry = (): LLMProviderRegistry => ({
  providers: [
    {
      id: 'anthropic',
      provider_type: 'anthropic',
      source: 'builtin',
      display_name: 'Anthropic',
    },
    {
      id: 'openai',
      provider_type: 'openai',
      source: 'builtin',
      display_name: 'OpenAI',
    },
  ],
  custom_provider: {
    enabled: true,
    display_name: 'Custom',
  },
});

const buildEmptyValue = (): LLMConfig => ({
  providers: {},
  selections: {} as any,
  model_runtime_overrides: {},
});

const buildNoopProps = () => ({
  registry: buildRegistry(),
  onChange: vi.fn(),
  onValid: vi.fn(),
});

describe('LLMSetupStep', () => {
  it('renders without showing the advanced model section by default', () => {
    const props = buildNoopProps();
    render(<LLMSetupStep {...props} value={buildEmptyValue()} />);
    expect(screen.queryByTestId('llm-setup-advanced-models')).not.toBeInTheDocument();
  });

  it('auto-populates models when user picks a known provider with full set (OpenAI)', async () => {
    const onChange = vi.fn();
    const ControlledHost = () => {
      const [value, setValue] = useState<LLMConfig>(buildEmptyValue());
      return (
        <LLMSetupStep
          registry={buildRegistry()}
          value={value}
          onChange={(next: LLMConfig) => {
            onChange(next);
            setValue(next);
          }}
        />
      );
    };
    render(<ControlledHost />);
    await userEvent.selectOptions(screen.getByLabelText(/provider/i), 'openai');
    await waitFor(() => {
      const calls = onChange.mock.calls.map((c) => c[0]);
      const lastWithSelections = calls.reverse().find((v) => v.selections?.core?.model);
      expect(lastWithSelections?.selections?.core?.model).toBe(RECOMMENDED_MODELS.openai.core);
      expect(lastWithSelections?.selections?.context_decider?.model).toBe(
        RECOMMENDED_MODELS.openai.context_decider,
      );
      expect(lastWithSelections?.selections?.embedding?.model).toBe(
        RECOMMENDED_MODELS.openai.embedding,
      );
    });
    expect(screen.queryByTestId('llm-setup-advanced-models')).not.toBeInTheDocument();
  });

  it('surfaces embedding-fallback row when chosen provider has null embedding (Anthropic)', async () => {
    const ControlledHost = () => {
      const [value, setValue] = useState<LLMConfig>(buildEmptyValue());
      return (
        <LLMSetupStep
          registry={buildRegistry()}
          value={value}
          onChange={(next: LLMConfig) => setValue(next)}
        />
      );
    };
    render(<ControlledHost />);
    await userEvent.selectOptions(screen.getByLabelText(/provider/i), 'anthropic');
    await waitFor(() => {
      expect(screen.getByTestId('llm-setup-embedding-row')).toBeInTheDocument();
    });
  });

  it('reports valid=true when provider+api_key+core selection are present', async () => {
    const onValid = vi.fn();
    const ControlledHost = () => {
      const [value, setValue] = useState<LLMConfig>(buildEmptyValue());
      return (
        <LLMSetupStep
          registry={buildRegistry()}
          value={value}
          onChange={(next: LLMConfig) => setValue(next)}
          onValid={onValid}
        />
      );
    };
    render(<ControlledHost />);
    await userEvent.selectOptions(screen.getByLabelText(/provider/i), 'openai');
    await userEvent.type(screen.getByLabelText(/api key/i), 'sk-test');
    await waitFor(() => {
      expect(onValid).toHaveBeenLastCalledWith(true);
    });
  });
});
