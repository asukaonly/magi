import { useState } from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { configApi, DEFAULT_LLM_CUSTOM_PROVIDER_META, type LLMConfig, type PluginModelProviderCatalogEntry } from '@/api/modules/config';
import LLMForm from '@/components/config-forms/LLMForm';
import { buildRegistryFromCatalog, cloneLLMConfig, cloneProvider, normalizeLLMConfig } from '@/components/config-forms/llm-form-state';

const t = (key: string, options?: Record<string, string>) => options?.provider ? `${key}: ${options.provider}` : key;
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }));

const provider: PluginModelProviderCatalogEntry = {
  provider_id: 'account-a:chat',
  plugin_id: 'local-model',
  connection_id: 'account-a',
  display_name: 'Local account / chat',
  model_selection: 'manual',
};

function Harness({ initialValue = cloneLLMConfig(), onChange = () => {} }: {
  initialValue?: LLMConfig;
  onChange?: (value: LLMConfig) => void;
}) {
  const [value, setValue] = useState(initialValue);
  return <LLMForm view="models" surface="settings" value={value} onChange={(next) => { setValue(next); onChange(next); }} />;
}

describe('plugin model selection', () => {
  beforeEach(() => {
    vi.spyOn(configApi, 'resolveLLMProviderCatalog').mockResolvedValue({ providers: [], plugin_providers: [provider] });
    vi.spyOn(configApi, 'getLLMCustomProviderTemplate').mockResolvedValue({
      template: DEFAULT_LLM_CUSTOM_PROVIDER_META, defaults: cloneProvider(),
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it('selects a live plugin with no native provider and preserves a manual model', async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    render(<Harness onChange={changed} />);
    const core = within(await screen.findByTestId('llm-scenario-core'));
    await user.click(core.getByRole('button', { name: 'llm.fields.provider' }));
    await user.click(screen.getByRole('button', { name: 'llm.modelSelection.pluginProvider: Local account / chat' }));
    expect(core.getByText('llm.modelSelection.pluginManualModel')).toBeInTheDocument();
    expect(screen.getAllByText('llm.modelSelection.pluginModelRequired').length).toBeGreaterThan(0);
    expect(core.queryByRole('button', { name: 'llm.showAdvanced' })).not.toBeInTheDocument();
    await user.type(core.getByRole('textbox', { name: 'llm.fields.model' }), 'local/manual-model');
    await waitFor(() => {
      const selected = changed.mock.lastCall?.[0] as LLMConfig;
      expect(selected.selections.core.provider_id).toBe('account-a:chat');
      expect(selected.selections.core.model).toBe('local/manual-model');
      expect(selected.providers).toEqual({});
    });
    expect(screen.queryByText('llm.modelSelection.pluginModelRequired')).not.toBeInTheDocument();
    const previousCalls = vi.mocked(configApi.resolveLLMProviderCatalog).mock.calls.length;
    fireEvent.focus(window);
    await waitFor(() => expect(vi.mocked(configApi.resolveLLMProviderCatalog).mock.calls.length).toBeGreaterThan(previousCalls));
    expect(core.getByRole('textbox', { name: 'llm.fields.model' })).toHaveValue('local/manual-model');
    expect(within(screen.getByTestId('llm-scenario-embedding')).queryByText('llm.modelSelection.pluginProvider: Local account / chat')).not.toBeInTheDocument();
  });

  it('refreshes connection availability on focus without changing the saved model', async () => {
    const initialValue = cloneLLMConfig();
    initialValue.selections.core.provider_id = provider.provider_id;
    initialValue.selections.core.model = 'saved-model';
    render(<Harness initialValue={initialValue} />);
    const core = within(await screen.findByTestId('llm-scenario-core'));
    expect(core.getByText('llm.modelSelection.pluginManualModel')).toBeInTheDocument();
    vi.mocked(configApi.resolveLLMProviderCatalog).mockResolvedValue({ providers: [], plugin_providers: [] });
    fireEvent.focus(window);
    await waitFor(() => expect(core.getByText('llm.modelSelection.pluginUnavailable')).toBeInTheDocument());
    expect(core.getByRole('textbox', { name: 'llm.fields.model' })).toHaveValue('saved-model');
  });

  it('keeps a saved selection visible when the provider is disabled or removed', async () => {
    vi.mocked(configApi.resolveLLMProviderCatalog).mockResolvedValue({ providers: [], plugin_providers: [] });
    const initialValue = cloneLLMConfig();
    initialValue.selections.core.provider_id = provider.provider_id;
    initialValue.selections.core.model = 'saved-model';
    render(<Harness initialValue={initialValue} />);
    const core = within(await screen.findByTestId('llm-scenario-core'));
    expect(core.getByRole('button', { name: 'llm.fields.provider' })).toHaveTextContent('llm.modelSelection.pluginUnavailableOption: account-a:chat');
    expect(core.getByRole('textbox', { name: 'llm.fields.model' })).toHaveValue('saved-model');
    expect(core.getByText('llm.modelSelection.pluginUnavailable')).toBeInTheDocument();
  });

  it('does not replace unavailable plugin choices with a native provider during normalization', () => {
    const value = cloneLLMConfig();
    value.providers.native = cloneProvider({ enabled: true });
    value.selections.core.provider_id = provider.provider_id;
    value.selections.core.model = 'saved-model';
    const normalized = normalizeLLMConfig(value, buildRegistryFromCatalog({ providers: [], plugin_providers: [] }, null));
    expect(normalized.selections.core).toEqual(value.selections.core);
    expect(normalized.providers[provider.provider_id]).toBeUndefined();
  });
});
