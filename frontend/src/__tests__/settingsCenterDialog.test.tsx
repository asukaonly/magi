import { forwardRef, useImperativeHandle, useState } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SettingsCenterDialog from '@/components/layout/SettingsCenterDialog';
import { PluginInstallPanel } from '@/components/plugins/PluginInstallPanel';
import { usePluginInstallFlow } from '@/hooks/usePluginInstallFlow';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';
import type { SettingsPageHandle, SettingsPageProps } from '@/types/settings';

const { translate } = vi.hoisted(() => ({ translate: (key: string) => key }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: translate, i18n: { language: 'en' } }),
}));
vi.mock('@/hooks/usePluginInstallFlow', () => ({ usePluginInstallFlow: vi.fn() }));
vi.mock('@/components/settings/SettingsContent', () => ({
  SettingsPage: forwardRef<SettingsPageHandle, SettingsPageProps>(function SettingsFixture({ onRequestClose }, ref) {
    const [draft, setDraft] = useState('Saved value');
    useImperativeHandle(ref, () => ({
      hasUnsavedChanges: () => draft !== 'Saved value',
      discardChanges: async () => { setDraft('Saved value'); },
    }));
    return <>
      <input aria-label="Settings draft" value={draft} onChange={event => setDraft(event.target.value)} />
      <button onClick={() => usePluginInstallPanelStore.getState().openPanel('calendar', { pluginName: 'Calendar' })}>Connect source</button>
      <button onClick={onRequestClose}>Close settings</button>
    </>;
  }),
}));

const awaitingFlow: ReturnType<typeof usePluginInstallFlow> = {
  phase: 'awaiting_fields', steps: [], flow: null,
  sourceName: null, connectionId: null, description: 'Connect your calendar.',
  installProgress: null, syncedCount: null, syncedRawCount: null,
  syncDeferred: false, memoryReady: false, memoryCount: null, memoryTotalCount: null,
  memoryProcessedCount: null, memoryRemainingCount: null, backfillNote: false,
  error: null, syncFailure: null, submitFields: vi.fn(), retry: vi.fn(),
};

function SettingsWithConnection() {
  const [open, setOpen] = useState(true);
  return <>
    <SettingsCenterDialog open={open} onOpenChange={setOpen} />
    <PluginInstallPanel />
  </>;
}

describe('settings dialog layering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    usePluginInstallPanelStore.getState().closePanel();
    vi.mocked(usePluginInstallFlow).mockReturnValue(awaitingFlow);
  });

  it.each([false, true])('retains settings when opening and cancelling a connection (dirty: %s)', async dirty => {
    const user = userEvent.setup();
    render(<SettingsWithConnection />);
    const draft = screen.getByRole('textbox', { name: 'Settings draft' });
    const shell = screen.getByTestId('settings-center-shell');
    if (dirty) await user.type(draft, ' with edits');
    await user.click(screen.getByRole('button', { name: 'Connect source' }));

    expect(await screen.findByRole('dialog', { name: 'Calendar' })).toBeInTheDocument();
    expect(screen.getByTestId('settings-center-shell')).toBe(shell);
    expect(screen.queryByText('settings.closeConfirm.title')).not.toBeInTheDocument();
    if (dirty) await user.keyboard('{Escape}');
    else await user.click(screen.getByRole('button', { name: 'common.close' }));

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Calendar' })).not.toBeInTheDocument());
    expect(screen.getByRole('textbox', { name: 'Settings draft' })).toBe(draft);
    expect(draft).toHaveValue(dirty ? 'Saved value with edits' : 'Saved value');
    await user.click(screen.getByRole('button', { name: 'Close settings' }));
    if (dirty) {
      expect(await screen.findByText('settings.closeConfirm.title')).toBeInTheDocument();
      await user.click(screen.getByRole('button', { name: 'settings.closeConfirm.confirm' }));
    }
    await waitFor(() => expect(screen.queryByTestId('settings-center-shell')).not.toBeInTheDocument());
  });

  it('keeps settings mounted through connection progress and completion', async () => {
    const user = userEvent.setup();
    const view = render(<SettingsWithConnection />);
    const shell = screen.getByTestId('settings-center-shell');
    await user.click(screen.getByRole('button', { name: 'Connect source' }));
    vi.mocked(usePluginInstallFlow).mockReturnValue({ ...awaitingFlow, phase: 'running' });
    view.rerender(<SettingsWithConnection />);
    expect(screen.getByRole('button', { name: 'pluginInstallPanel.close' })).toBeDisabled();
    expect(screen.getByTestId('settings-center-shell')).toBe(shell);
    vi.mocked(usePluginInstallFlow).mockReturnValue({ ...awaitingFlow, phase: 'done' });
    view.rerender(<SettingsWithConnection />);
    await user.click(screen.getByRole('button', { name: 'pluginInstallPanel.close' }));
    expect(screen.getByRole('dialog', { name: 'settings.title' })).toBeVisible();
    expect(screen.getByTestId('settings-center-shell')).toBe(shell);
  });

  it('still closes clean settings on an outside pointer interaction', async () => {
    render(<SettingsWithConnection />);
    await screen.findByTestId('settings-center-shell');
    // DismissableLayer registers outside-pointer handling after the opening event.
    await new Promise(resolve => setTimeout(resolve, 0));
    fireEvent.pointerDown(document.body);
    await waitFor(() => expect(screen.queryByTestId('settings-center-shell')).not.toBeInTheDocument());
  });
});
