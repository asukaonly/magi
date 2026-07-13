import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ProductTour } from '@/components/onboarding/ProductTour';
import type { InstallableItem } from '@/api/modules/systemSuggestions';
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
    setup_time_estimate_seconds: 10,
    data_locality: 'local_only',
    ...overrides,
  };
}

describe('ProductTour', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockUseInstallableSensors.mockReset();
    mockUseInstallableSensors.mockReturnValue({
      items: [item()],
      loading: false,
      refresh: vi.fn(),
    });
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
      context: 'first_context',
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

  it('does not interrupt with vector-model setup when embeddings are missing', async () => {
    render(<ProductTour onComplete={vi.fn()} />);

    expect(await screen.findByText('productTour.firstContextTitle')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state-connect-chrome-history')).toBeInTheDocument();
    expect(screen.queryByText('productTour.memoryModelTitle')).not.toBeInTheDocument();
  });
});
