import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ProductTour } from '@/components/onboarding/ProductTour';
import * as ss from '@/api/modules/systemSuggestions';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'zh-CN' } }) }));

function mountTargets() {
  for (const id of ['tour-target-conversation', 'tour-target-timeline', 'tour-target-memory', 'tour-target-bell']) {
    const el = document.createElement('div');
    el.setAttribute('data-testid', id);
    document.body.appendChild(el);
  }
}

describe('ProductTour', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    usePluginInstallPanelStore.getState().closePanel();
    document.body.innerHTML = '';
    mountTargets();
    vi.spyOn(ss, 'listInstallable').mockResolvedValue([
      { plugin_id: 'chrome-history', category: 'browser_history', installed: false, rationale: { zh: '', en: '' } },
    ]);
  });

  it('steps through and calls onComplete after the last step', async () => {
    const onComplete = vi.fn();
    render(<ProductTour onComplete={onComplete} />);
    // step 1 → next ×3 → done
    for (let i = 0; i < 3; i++) await userEvent.click(await screen.findByRole('button', { name: 'productTour.next' }));
    await userEvent.click(await screen.findByRole('button', { name: 'productTour.done' }));
    await waitFor(() => expect(onComplete).toHaveBeenCalled());
  });

  it('skip calls onComplete', async () => {
    const onComplete = vi.fn();
    render(<ProductTour onComplete={onComplete} />);
    await userEvent.click(await screen.findByRole('button', { name: 'productTour.skip' }));
    await waitFor(() => expect(onComplete).toHaveBeenCalled());
  });

  it('connect opens the install panel install-first for an uninstalled source', async () => {
    const openPanel = vi.spyOn(usePluginInstallPanelStore.getState(), 'openPanel');
    render(<ProductTour onComplete={vi.fn()} />);
    // Advance to the connect step (index 1: timeline) and click the named connect button.
    await userEvent.click(await screen.findByRole('button', { name: 'productTour.next' }));
    await userEvent.click(await screen.findByTestId('tour-connect-chrome-history'));
    expect(openPanel).toHaveBeenCalledWith('chrome-history', { install: true });
  });
});
