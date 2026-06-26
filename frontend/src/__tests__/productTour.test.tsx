import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ProductTour } from '@/components/onboarding/ProductTour';
import { configApi, DEFAULT_SYSTEM_CONFIG, type SystemConfig } from '@/api/modules/config';
import type { InstallableItem } from '@/api/modules/systemSuggestions';
import { useChatShellStore } from '@/stores/chat-shell';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'zh-CN' } }),
}));

const mockUseInstallableSensors = vi.fn();
vi.mock('@/hooks/useInstallableSensors', () => ({
  useInstallableSensors: () => mockUseInstallableSensors(),
}));

function item(overrides: Partial<InstallableItem> = {}): InstallableItem {
  return {
    plugin_id: 'chrome-history',
    category: 'browser_history',
    installed: false,
    rationale: { zh: '', en: '' },
    ...overrides,
  };
}

function configWithRemoteEmbedding(): SystemConfig {
  const config = structuredClone(DEFAULT_SYSTEM_CONFIG);
  config.memory.embedding.mode = 'remote';
  config.llm.selections.embedding.provider_id = 'openai';
  config.llm.selections.embedding.model = 'text-embedding-3-small';
  return config;
}

function configWithoutEmbedding(): SystemConfig {
  const config = structuredClone(DEFAULT_SYSTEM_CONFIG);
  config.memory.embedding.mode = 'off';
  config.llm.selections.embedding.provider_id = '';
  config.llm.selections.embedding.model = '';
  return config;
}

describe('ProductTour', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(configApi, 'get').mockResolvedValue({
      success: true,
      data: configWithRemoteEmbedding(),
    } as any);
    mockUseInstallableSensors.mockReset();
    mockUseInstallableSensors.mockReturnValue({
      items: [item()],
      loading: false,
      refresh: vi.fn(),
    });
    useChatShellStore.setState({ activePanel: 'none', settingsNavigationIntent: null });
    usePluginInstallPanelStore.getState().closePanel();
  });

  it('renders the first context setup prompt', async () => {
    render(<ProductTour onComplete={vi.fn()} />);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('productTour.firstContextTitle')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state-connect-chrome-history')).toBeInTheDocument();
  });

  it('connect later calls onComplete', async () => {
    const onComplete = vi.fn();
    render(<ProductTour onComplete={onComplete} />);
    await screen.findByText('productTour.firstContextTitle');
    await userEvent.click(screen.getByRole('button', { name: 'productTour.connectLater' }));
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
  });

  it('ignores accidental outside and escape dismissal', async () => {
    const onComplete = vi.fn();
    render(<ProductTour onComplete={onComplete} />);
    await screen.findByText('productTour.firstContextTitle');

    expect(screen.queryByRole('button', { name: 'Close' })).not.toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape', code: 'Escape' });
    fireEvent.pointerDown(document.body);
    fireEvent.mouseDown(document.body);
    fireEvent.click(document.body);

    expect(onComplete).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('connect opens the install panel and completes only after install succeeds', async () => {
    const onComplete = vi.fn();
    const openPanel = vi.spyOn(usePluginInstallPanelStore.getState(), 'openPanel');

    render(<ProductTour onComplete={onComplete} />);
    await screen.findByText('productTour.firstContextTitle');
    await userEvent.click(screen.getByTestId('empty-state-connect-chrome-history'));

    expect(openPanel).toHaveBeenCalledWith('chrome-history', {
      install: true,
      onDone: expect.any(Function),
    });
    expect(onComplete).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());

    usePluginInstallPanelStore.getState().closePanel();
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
    expect(onComplete).not.toHaveBeenCalled();

    const onDone = openPanel.mock.calls[0]?.[1]?.onDone;
    onDone?.();
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
  });

  it('shows the memory model prompt before the plugin prompt when embeddings are missing', async () => {
    vi.mocked(configApi.get).mockResolvedValue({
      success: true,
      data: configWithoutEmbedding(),
    } as any);

    render(<ProductTour onComplete={vi.fn()} />);

    expect(await screen.findByText('productTour.memoryModelTitle')).toBeInTheDocument();
    expect(screen.queryByText('productTour.firstContextTitle')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'productTour.memoryModelSkip' }));

    expect(await screen.findByText('productTour.firstContextTitle')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state-connect-chrome-history')).toBeInTheDocument();
  });

  it('opens model settings from the memory model prompt and resumes the plugin prompt after settings closes', async () => {
    vi.mocked(configApi.get).mockResolvedValue({
      success: true,
      data: configWithoutEmbedding(),
    } as any);

    render(<ProductTour onComplete={vi.fn()} />);

    await screen.findByText('productTour.memoryModelTitle');
    await userEvent.click(screen.getByRole('button', { name: 'productTour.memoryModelConfigure' }));

    expect(useChatShellStore.getState().activePanel).toBe('settings');
    expect(useChatShellStore.getState().settingsNavigationIntent).toEqual({ section: 'llmModels' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    act(() => {
      useChatShellStore.setState({ activePanel: 'none' });
    });

    expect(await screen.findByText('productTour.firstContextTitle')).toBeInTheDocument();
  });
});
