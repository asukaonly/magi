import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { PluginRequestRecoveryDialog } from '@/components/plugins/PluginRequestRecoveryDialog';
import { usePluginRequestRecoveryStore } from '@/stores/plugin-request-recovery';

const runtime = vi.hoisted(() => ({ reset: undefined as (() => void) | undefined }));
vi.mock('@/runtime/config', () => ({ subscribeRuntimeReset: (callback: () => void) => { runtime.reset = callback; return () => { runtime.reset = undefined; }; } }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('sonner', () => ({ toast: { info: vi.fn() } }));
beforeEach(() => { usePluginRequestRecoveryStore.getState().reset(); vi.clearAllMocks(); });

it('requires operator acknowledgment and never resolves on dismissal', async () => {
  const user = userEvent.setup();
  const resolve = vi.fn().mockResolvedValue('closed');
  const request = { operationId: 'old', path: '/plugins/photos/connections', resolve };
  usePluginRequestRecoveryStore.getState().show(request);
  render(<PluginRequestRecoveryDialog />);
  expect(screen.getByRole('button', { name: 'plugins.requestRecovery.close' })).toBeDisabled();
  await user.click(screen.getByRole('button', { name: 'plugins.requestRecovery.later' }));
  expect(resolve).not.toHaveBeenCalled();
  act(() => usePluginRequestRecoveryStore.getState().show(request));
  await user.click(screen.getByRole('checkbox'));
  await user.click(screen.getByRole('button', { name: 'plugins.requestRecovery.close' }));
  expect(resolve).toHaveBeenCalledOnce();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(usePluginRequestRecoveryStore.getState().closed?.operationId).toBe('old');
});

it('shows closure failures and cancels the visible review when the connection changes', async () => {
  const user = userEvent.setup();
  const resolve = vi.fn().mockRejectedValue(new Error('Still running'));
  usePluginRequestRecoveryStore.getState().show({ operationId: 'old', path: '/plugins/photos/connections', resolve });
  render(<PluginRequestRecoveryDialog />);
  await user.click(screen.getByRole('checkbox'));
  await user.click(screen.getByRole('button', { name: 'plugins.requestRecovery.close' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('plugins.requestRecovery.failed');
  expect(usePluginRequestRecoveryStore.getState().closed).toBeNull();
  act(() => runtime.reset?.());
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
