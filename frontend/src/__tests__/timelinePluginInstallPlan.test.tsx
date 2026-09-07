import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, it, vi } from 'vitest';
import { pluginsApi } from '@/api/modules/plugins';
import type { SourceStatusItem } from '@/api/modules/sources';
import { TimelineSourcesSection } from '@/components/settings/TimelineSourcesSection';
import { planFor } from './fixtures/pluginInstallPlan';
import examples from '../../../contracts/api/frontend-plugins-examples.json';
import { parsePluginPackage } from '@/api/plugin-contract';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));
beforeEach(() => vi.restoreAllMocks());

it('reviews a timeline entry plan before submitting its exact approval', async () => {
  const plan = planFor('new-browser');
  vi.spyOn(pluginsApi, 'getInstallPlan').mockResolvedValue(plan);
  const install = vi.spyOn(pluginsApi, 'installFromRegistryWithProgress').mockResolvedValue(parsePluginPackage(examples.package));
  const source: SourceStatusItem = {
    source_name: 'existing-browser', plugin_id: 'existing-browser', connection_id: 'existing-connection',
    connection_display_name: 'Personal', connection_revision: 1, contribution_id: 'history',
    display_name: 'Existing browser', description: '', capability_id: 'browser_history',
    capability_display_name: 'Browser history', fields: [], current_settings: {}, enabled: false,
    sync_mode: 'manual', sync_interval_minutes: 60, storage_mode: 'sqlite', fetch_page_content: false,
    edge_whitelist: [], supports_pull_sync: false, status: 'disabled',
  };
  const refresh = vi.fn().mockResolvedValue(undefined);
  render(<TimelineSourcesSection
    userMode="quick" statuses={[source]} loadingStatus={false} selectedSourceName="browser_history"
    onSelectSource={vi.fn()} onRefreshSources={refresh}
    availableEntries={[{
      capabilityId: 'browser_history', capabilityDisplayName: 'Browser history', capabilityDescription: '',
      pluginId: 'new-browser', entryId: 'new-browser', entryDisplayName: 'New browser', entryDescription: '',
      entryOrder: 1, version: '2.0.0', official: false, capabilities: [], executionMode: 'restricted_process',
      installFingerprint: 'unapproved-registry-fingerprint',
    }]}
  />);
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'settings.timeline.actions.installEntry' }));
  await screen.findByRole('region', { name: 'new-browser' });
  expect(pluginsApi.getInstallPlan).toHaveBeenCalledExactlyOnceWith('new-browser', false);
  expect(install).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button', { name: 'settings.marketplace.plan.confirm' }));
  await waitFor(() => expect(install).toHaveBeenCalledExactlyOnceWith('new-browser', plan.fingerprint, expect.any(Function)));
  expect(refresh).toHaveBeenCalledOnce();
});
