import { useEffect } from 'react';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import type { PluginSettingsUiBlockSpec } from '@/api/modules/plugins';

const mocks = vi.hoisted(() => ({
  read: vi.fn(), open: vi.fn(), mode: 'remote', t: (key: string) => key,
  refresh: new Set<() => Promise<void>>(),
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.t }) }));
vi.mock('@/api/modules/plugins', () => ({ pluginsApi: { getSettingsResource: mocks.read } }));
vi.mock('@/runtime/desktop', () => ({ openExternalUrl: mocks.open }));
vi.mock('@/runtime/config', () => ({ getRuntimeConfig: () => ({ mode: mocks.mode }) }));
vi.mock('@/hooks/useCenterRefresh', () => ({ useCenterRefresh: (read: () => Promise<void>) => {
  useEffect(() => { mocks.refresh.add(read); return () => { mocks.refresh.delete(read); }; }, [read]);
} }));

import { PluginSettingsCustomBlocks } from '@/components/settings/PluginSettingsCustomBlocks';

const permissionBlock: PluginSettingsUiBlockSpec = {
  block_id: 'permissions', type: 'resource_picker', title: 'Permissions', description: '',
  resource_name: 'permissions', value_key: 'permissions', presentation: 'permission_status',
};
const item = { id: 'photos', label: 'Photos', status: 'denied', required: true, settings_url: 'x-apple.systempreferences:com.apple.preference.security?Privacy_Photos' };
beforeEach(() => {
  vi.resetAllMocks(); mocks.mode = 'remote'; mocks.refresh.clear();
  mocks.read.mockResolvedValue({ data: { items: [item] } });
  mocks.open.mockResolvedValue(undefined);
});
async function refresh() { await act(async () => { await Promise.all([...mocks.refresh].map(read => read())); }); }

it('explains center permissions and never opens the remote client system settings', async () => {
  render(<PluginSettingsCustomBlocks connectionId="center-photos" blocks={[permissionBlock]} values={{}} onChange={vi.fn()} />);
  expect(await screen.findByText('Photos')).toBeInTheDocument();
  expect(screen.getByText('settings.permissionStatus.centerDevice')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'settings.permissionStatus.openSettings' })).not.toBeInTheDocument();
  mocks.read.mockResolvedValue({ data: { items: [{ ...item, status: 'granted' }] } });
  await refresh();
  expect(screen.getByText('(settings.permissionStatus.statuses.granted)')).toBeInTheDocument();
  expect(mocks.open).not.toHaveBeenCalled();
});

it('opens the system settings for a local center and retains status after a failed read', async () => {
  mocks.mode = 'local';
  const user = userEvent.setup();
  render(<PluginSettingsCustomBlocks connectionId="local-photos" blocks={[permissionBlock]} values={{}} onChange={vi.fn()} />);
  await user.click(await screen.findByRole('button', { name: 'settings.permissionStatus.openSettings' }));
  expect(mocks.open).toHaveBeenCalledWith(item.settings_url);
  mocks.read.mockRejectedValue(new Error('Offline'));
  await refresh();
  expect(screen.getByText('Photos')).toBeInTheDocument();
  expect(mocks.open).toHaveBeenCalledTimes(1);
});

it('refreshes center calendars without changing unsaved selections', async () => {
  const onChange = vi.fn();
  const block = { ...permissionBlock, presentation: 'calendar_list' as const, value_key: 'calendar_ids' };
  const group = { group_id: 'account', label: 'Account', items: [{ item_id: 'work', label: 'Work' }] };
  mocks.read.mockResolvedValue({ data: { groups: [group] } });
  render(<PluginSettingsCustomBlocks connectionId="center-calendar" blocks={[block]} values={{ calendar_ids: ['work'] }} onChange={onChange} />);
  expect(await screen.findByRole('checkbox', { name: 'Work' })).toBeChecked();
  mocks.read.mockResolvedValue({ data: { groups: [{ ...group, items: [...group.items, { item_id: 'family', label: 'Family' }] }] } });
  await refresh();
  expect(screen.getByRole('checkbox', { name: 'Work' })).toBeChecked();
  expect(screen.getByRole('checkbox', { name: 'Family' })).not.toBeChecked();
  expect(onChange).not.toHaveBeenCalled();
});
