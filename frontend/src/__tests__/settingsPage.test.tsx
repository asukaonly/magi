import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { SettingsPage } from '@/pages/Settings';
import { configApi, DEFAULT_SYSTEM_CONFIG } from '@/api/modules/config';
import { memoryApi } from '@/api/modules/memory';

vi.mock('@/components/config-forms/LLMForm', () => ({
  default: ({ value, onChange }: { value: any; onChange: (next: any) => void }) => (
    <button type="button" onClick={() => onChange({ ...value, model: 'gpt-5' })}>
      change-llm
    </button>
  ),
}));

vi.mock('@/components/config-forms/DynamicToolConfig', () => ({
  DynamicToolsConfig: () => <div>tools-config</div>,
}));

vi.mock('@/components/settings/LLMUsageSection', () => ({
  LLMUsageSection: () => <div>usage-section</div>,
}));

vi.mock('@/api/modules/config', async () => {
  const actual = await vi.importActual<typeof import('@/api/modules/config')>('@/api/modules/config');
  return {
    ...actual,
    configApi: {
      ...actual.configApi,
      get: vi.fn(),
      update: vi.fn(),
    },
  };
});

vi.mock('@/api/modules/memory', () => ({
  memoryApi: {
    listModels: vi.fn(),
    downloadModel: vi.fn(),
    getModelStatus: vi.fn(),
    clearAll: vi.fn(),
  },
}));

describe('settings page save behavior', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    vi.mocked(configApi.get).mockResolvedValue({
      data: structuredClone(DEFAULT_SYSTEM_CONFIG),
    } as any);
    vi.mocked(configApi.update).mockResolvedValue({
      success: true,
      data: structuredClone(DEFAULT_SYSTEM_CONFIG),
    } as any);
    vi.mocked(memoryApi.listModels).mockResolvedValue({
      data: { models: [] },
    } as any);
  });

  it('auto-saves non-llm settings after edits', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.system' }));

    const loopIntervalInput = screen.getAllByRole('spinbutton')[0];
    fireEvent.change(loopIntervalInput, { target: { value: '2' } });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    });

    await waitFor(() => expect(configApi.update).toHaveBeenCalledTimes(1));
    expect(configApi.update).toHaveBeenCalledWith(
      expect.objectContaining({
        loop: expect.objectContaining({ interval: 2 }),
      })
    );
  });

  it('keeps llm changes local until the llm save button is clicked', async () => {
    const user = userEvent.setup();
    render(<SettingsPage />);

    await screen.findByText('settings.title');
    await user.click(screen.getByRole('button', { name: 'settings.tabs.llm' }));
    await user.click(screen.getByRole('button', { name: 'change-llm' }));

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 700));
    });

    expect(configApi.update).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'settings.saveLLM' }));

    await waitFor(() => expect(configApi.update).toHaveBeenCalledTimes(1));
    expect(configApi.update).toHaveBeenCalledWith(
      expect.objectContaining({
        llm: expect.objectContaining({ model: 'gpt-5' }),
      })
    );
  });
});
