import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { NotificationCenter } from '@/components/notifications/NotificationCenter';
import * as api from '@/api/modules/notifications';
import * as suggestionsApi from '@/api/modules/systemSuggestions';
import { sensorsApi } from '@/api/modules/sensors';
import { usePluginInstallPanelStore } from '@/stores/pluginInstallPanel';
import { useNotificationStore } from '@/stores/notifications';

// `t` is mocked to echo the key, so composed titles render as their key
// (e.g. 'notifications.suggestionTitle'). Rows are selected by test id.
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'zh-CN' } }) }));

describe('NotificationCenter', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    usePluginInstallPanelStore.getState().closePanel();
    useNotificationStore.setState({ items: [], unreadCount: 0, loading: false });
    vi.spyOn(api, 'listNotifications').mockResolvedValue({
      items: [{ id: 1, kind: 'suggestion', dedupe_key: 'browser_history', title: '看浏览器历史', body: '看浏览器历史',
        payload: { plugins: [{ plugin_id: 'chrome-history', name: 'Chrome History', name_i18n: { 'zh-CN': 'Chrome 浏览器历史' }, icon: 'brand:googlechrome', installed: true }] }, status: 'unread', created_at_ms: 1, read_at_ms: null }],
      unread_count: 1,
    });
    vi.spyOn(api, 'markRead').mockResolvedValue();
    vi.spyOn(api, 'markAllRead').mockResolvedValue();
    vi.spyOn(api, 'dismissNotification').mockResolvedValue();
    vi.spyOn(api, 'dismissAllNotifications').mockResolvedValue();
    vi.spyOn(sensorsApi, 'getStatus').mockResolvedValue({ sources: [
      { plugin_id: 'chrome-history', source_name: 'chrome', activation_flow: { enabled_key: 'enabled', configured_key: 'configured', authorize_on_confirm: false, fields: [] } },
    ] } as any);
    vi.spyOn(suggestionsApi, 'listDismissals').mockResolvedValue([
      { dedupe_key: 'music', dismissed_at: new Date().toISOString(), kind: 'explicit' },
    ]);
    vi.spyOn(suggestionsApi, 'clearDismissal').mockResolvedValue();
  });

  it('marks a row read on expand', async () => {
    render(<NotificationCenter />);
    const row = await screen.findByTestId('notification-row');
    await userEvent.click(within(row).getByText('notifications.suggestionTitle'));
    await waitFor(() => expect(api.markRead).toHaveBeenCalledWith([1]));
  });

  it('mark-all-read button calls markAllRead', async () => {
    render(<NotificationCenter />);
    await screen.findByTestId('notification-row');
    await userEvent.click(screen.getByRole('button', { name: 'notifications.markAllRead' }));
    expect(api.markAllRead).toHaveBeenCalled();
  });

  it('clear-all button calls dismissAllNotifications', async () => {
    render(<NotificationCenter />);
    await screen.findByTestId('notification-row');
    await userEvent.click(screen.getByRole('button', { name: 'notifications.clearAll' }));
    await waitFor(() => expect(api.dismissAllNotifications).toHaveBeenCalled());
  });

  it('per-row dismiss (x) calls dismissNotification', async () => {
    render(<NotificationCenter />);
    await screen.findByTestId('notification-row');
    await userEvent.click(screen.getByRole('button', { name: 'notifications.dismissAria' }));
    await waitFor(() => expect(api.dismissNotification).toHaveBeenCalledWith(1));
  });

  it('connect button opens the shared install panel (with an onDone to mark acted)', async () => {
    render(<NotificationCenter />);
    const row = await screen.findByTestId('notification-row');
    await userEvent.click(within(row).getByText('notifications.suggestionTitle'));
    await userEvent.click(await screen.findByTestId('notification-connect-chrome-history'));
    await waitFor(() => {
      const s = usePluginInstallPanelStore.getState();
      expect(s.open).toBe(true);
      expect(s.pluginId).toBe('chrome-history');
      expect(s.pluginName).toBe('Chrome 浏览器历史');
      expect(s.pluginIcon).toBe('brand:googlechrome');
      expect(s.installMode).toBe(false);
      expect(typeof s.onDone).toBe('function');
    });
  });

  it('shows dismissed footer and restores', async () => {
    render(<NotificationCenter />);
    // expand the 已忽略 footer
    await userEvent.click(await screen.findByRole('button', { name: /notifications.dismissedTitle/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'notifications.restore' }));
    await waitFor(() => expect(suggestionsApi.clearDismissal).toHaveBeenCalledWith('music'));
  });

  it('labels a dismissed row with its stored localized title (not humanized key)', async () => {
    vi.spyOn(suggestionsApi, 'listDismissals').mockResolvedValue([
      { dedupe_key: 'browser_history', dismissed_at: new Date().toISOString(),
        kind: 'explicit', title: '看看你的浏览器历史' },
    ]);
    render(<NotificationCenter />);
    await userEvent.click(await screen.findByRole('button', { name: /notifications.dismissedTitle/ }));
    // Shows the localized title the user saw, not the humanized "Browser History".
    expect(await screen.findByText('看看你的浏览器历史')).toBeInTheDocument();
    expect(screen.queryByText('Browser History')).not.toBeInTheDocument();
  });

  it('falls back to humanized dedupe_key when a dismissal has no title', async () => {
    render(<NotificationCenter />);  // default mock: { dedupe_key: 'music' } (no title)
    await userEvent.click(await screen.findByRole('button', { name: /notifications.dismissedTitle/ }));
    expect(await screen.findByText('Music')).toBeInTheDocument();
  });
});

describe('NotificationCenter — profile_conflict branch', () => {
  const CONFLICT_NOTIFICATION = {
    id: 42,
    kind: 'suggestion' as const,
    dedupe_key: 'profile_conflict:42',
    title: '个人信息存在冲突',
    body: '你自陈「职业」为「工程师」，但 magi 推断为「研究员」。',
    payload: {
      conflict_type: 'profile_conflict' as const,
      shadow_id: 'shadow-1',
      authoritative_id: 'auth-1',
      trait_name: '职业',
      authoritative_value: '工程师',
      inferred_value: '研究员',
      entity_id: 'entity-1',
    },
    status: 'unread' as const,
    created_at_ms: 2,
    read_at_ms: null,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
    // Reset the zustand singleton so stale items from other describe blocks don't bleed in.
    useNotificationStore.setState({ items: [], unreadCount: 0, loading: false });
    vi.spyOn(api, 'listNotifications').mockResolvedValue({
      items: [CONFLICT_NOTIFICATION],
      unread_count: 1,
    });
    vi.spyOn(api, 'markRead').mockResolvedValue();
    vi.spyOn(api, 'markAllRead').mockResolvedValue();
    vi.spyOn(api, 'dismissNotification').mockResolvedValue();
    vi.spyOn(api, 'dismissAllNotifications').mockResolvedValue();
    vi.spyOn(api, 'actionNotification').mockResolvedValue();
    vi.spyOn(api, 'resolveConflict').mockResolvedValue();
    vi.spyOn(suggestionsApi, 'listDismissals').mockResolvedValue([]);
  });

  it('renders 更新 and 保持 buttons when expanded', async () => {
    render(<NotificationCenter />);
    const row = await screen.findByTestId('notification-row');
    // expand the row (click the title area)
    await userEvent.click(within(row).getByText('个人信息存在冲突'));
    expect(await screen.findByTestId('notification-conflict-confirm')).toBeInTheDocument();
    expect(screen.getByTestId('notification-conflict-reject')).toBeInTheDocument();
  });

  it('更新 calls resolveConflict(id, "confirm") then act', async () => {
    render(<NotificationCenter />);
    const row = await screen.findByTestId('notification-row');
    await userEvent.click(within(row).getByText('个人信息存在冲突'));
    await userEvent.click(await screen.findByTestId('notification-conflict-confirm'));
    await waitFor(() => {
      expect(api.resolveConflict).toHaveBeenCalledWith(42, 'confirm');
      expect(api.actionNotification).toHaveBeenCalledWith(42);
    });
  });

  it('保持 calls resolveConflict(id, "reject") then act', async () => {
    render(<NotificationCenter />);
    const row = await screen.findByTestId('notification-row');
    await userEvent.click(within(row).getByText('个人信息存在冲突'));
    await userEvent.click(await screen.findByTestId('notification-conflict-reject'));
    await waitFor(() => {
      expect(api.resolveConflict).toHaveBeenCalledWith(42, 'reject');
      expect(api.actionNotification).toHaveBeenCalledWith(42);
    });
  });

  it('does NOT render conflict buttons for a suggestion notification', async () => {
    vi.spyOn(api, 'listNotifications').mockResolvedValue({
      items: [{ id: 1, kind: 'suggestion', dedupe_key: 'browser_history', title: '看浏览器历史', body: '看浏览器历史',
        payload: { plugins: [{ plugin_id: 'chrome-history', name: 'Chrome History', name_i18n: {}, icon: 'brand:googlechrome', installed: true }] }, status: 'unread', created_at_ms: 1, read_at_ms: null }],
      unread_count: 1,
    });
    render(<NotificationCenter />);
    const row = await screen.findByTestId('notification-row');
    await userEvent.click(within(row).getByText('notifications.suggestionTitle'));
    await screen.findByTestId('notification-connect-chrome-history');
    expect(screen.queryByTestId('notification-conflict-confirm')).not.toBeInTheDocument();
    expect(screen.queryByTestId('notification-conflict-reject')).not.toBeInTheDocument();
  });
});
