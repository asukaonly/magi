import { render, screen, waitFor } from '@testing-library/react';
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

  it('renders the first context setup prompt', () => {
    render(<ProductTour onComplete={vi.fn()} />);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('productTour.firstContextTitle')).toBeInTheDocument();
    expect(screen.getByTestId('empty-state-connect-chrome-history')).toBeInTheDocument();
  });

  it('enter chat calls onComplete', async () => {
    const onComplete = vi.fn();
    render(<ProductTour onComplete={onComplete} />);
    await userEvent.click(screen.getByRole('button', { name: 'productTour.enterChat' }));
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
  });

  it('skip calls onComplete', async () => {
    const onComplete = vi.fn();
    render(<ProductTour onComplete={onComplete} />);
    await userEvent.click(screen.getByRole('button', { name: 'productTour.skip' }));
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
  });

  it('connect opens the install panel and completes the prompt', async () => {
    const onComplete = vi.fn();
    const openPanel = vi.spyOn(usePluginInstallPanelStore.getState(), 'openPanel');

    render(<ProductTour onComplete={onComplete} />);
    await userEvent.click(screen.getByTestId('empty-state-connect-chrome-history'));

    expect(openPanel).toHaveBeenCalledWith('chrome-history', { install: true });
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
  });
});
