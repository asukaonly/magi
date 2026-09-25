import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { pluginsApi, type SourceCatalogItem, type SourceCatalogResponse } from '@/api/modules/plugins';
import { parseSourceCatalog } from '@/api/plugin-contract';
import { AppSourceCatalog } from '@/components/onboarding/AppSourceCatalog';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';
import fixtures from '../../../contracts/api/frontend-plugins-examples.json';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'zh-CN' } }) }));
const item = (id: string, overrides: Partial<SourceCatalogItem> = {}): SourceCatalogItem => ({
  plugin_id: id, name: id, name_i18n: {}, description: '', description_i18n: {},
  icon: 'lucide:globe', installed: false, scope: { en: 'Last 7 days', zh: '最近 7 天' }, status: 'available', ...overrides,
});
const catalog = (items: SourceCatalogItem[]): SourceCatalogResponse => ({ items, catalog_mode: 'full' });
function show(connectedPluginIds: string[] = []) {
  const onBack = vi.fn(), onConnectDone = vi.fn();
  return { ...render(<AppSourceCatalog connectedPluginIds={connectedPluginIds} onBack={onBack} onConnectDone={onConnectDone} />), onBack, onConnectDone };
}

beforeEach(() => { vi.restoreAllMocks(); usePluginInstallPanelStore.getState().closePanel(); });

describe('AppSourceCatalog', () => {
  it('keeps all entries, searches localized names and opens the existing connect flow', async () => {
    vi.spyOn(pluginsApi, 'getSourceCatalog').mockResolvedValue(catalog([
      ...Array.from({ length: 7 }, (_, index) => item(`browser-${index}`)),
      item('notes', { name_i18n: { 'zh-CN': '笔记库' }, installed: true }),
    ]));
    const { onBack, onConnectDone } = show();
    await screen.findByText('笔记库');
    expect(screen.getAllByRole('button', { name: 'emptyState.connectApp' })).toHaveLength(8);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: '笔记' } });
    expect(screen.queryByText('browser-0')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'emptyState.connectApp' }));
    expect(usePluginInstallPanelStore.getState()).toMatchObject({ pluginId: 'notes', installMode: false,
      context: 'first_context', sourceScope: { en: 'Last 7 days', zh: '最近 7 天' } });
    act(() => usePluginInstallPanelStore.getState().onDone?.({ pluginId: 'notes', connectionId: 'notes-1' }));
    expect(onConnectDone).toHaveBeenCalledWith('notes', { pluginId: 'notes', connectionId: 'notes-1' });
    fireEvent.click(screen.getByRole('button', { name: 'firstContext.catalog.back' }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it('shows connected sources and unavailable reasons without offering another connection', async () => {
    vi.spyOn(pluginsApi, 'getSourceCatalog').mockResolvedValue(catalog([
      item('connected', { status: 'connected' }), item('completed-locally'),
      item('missing', { status: 'app_not_installed' }), item('platform', { status: 'unsupported_platform' }),
    ]));
    show(['completed-locally']);
    await screen.findByText('platform');
    expect(screen.getByText('firstContext.catalog.status.app_not_installed')).toBeInTheDocument();
    expect(screen.getByText('firstContext.catalog.status.unsupported_platform')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'emptyState.connectApp' })).not.toBeInTheDocument();
  });

  it('keeps installed sources accessible when the marketplace is offline', async () => {
    vi.spyOn(pluginsApi, 'getSourceCatalog').mockResolvedValue({ ...catalog([item('local')]), catalog_mode: 'installed_only' });
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('firstContext.catalog.localOnly');
    expect(screen.getByText('local')).toBeInTheDocument();
  });

  it('supports retry after a failed request and distinguishes an empty search', async () => {
    const request = vi.spyOn(pluginsApi, 'getSourceCatalog').mockRejectedValueOnce(new Error('Unavailable')).mockResolvedValue(catalog([item('calendar')]));
    show();
    expect(await screen.findByRole('alert')).toHaveTextContent('firstContext.catalog.failed');
    fireEvent.click(screen.getByRole('button', { name: 'emptyState.retry' }));
    await screen.findByText('calendar');
    expect(request).toHaveBeenCalledTimes(2);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'no-match' } });
    expect(screen.getByText('firstContext.catalog.noMatches')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });

  it('validates server examples and rejects unknown availability statuses', () => {
    expect(parseSourceCatalog(fixtures.source_catalog).items[0].status).toBe('available');
    expect(() => parseSourceCatalog(catalog([item('bad', { status: 'invented' as SourceCatalogItem['status'] })]))).toThrow();
  });
});
