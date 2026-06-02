import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { NotificationCenter } from '@/components/notifications/NotificationCenter';
import * as api from '@/api/modules/notifications';
import * as suggestionsApi from '@/api/modules/systemSuggestions';
import { sensorsApi } from '@/api/modules/sensors';

// `t` is mocked to echo the key, so composed titles render as their key
// (e.g. 'notifications.suggestionTitle'). Rows are selected by test id.
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'zh-CN' } }) }));

describe('NotificationCenter', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'listNotifications').mockResolvedValue({
      items: [{ id: 1, kind: 'suggestion', dedupe_key: 'browser_history', title: '看浏览历史', body: '看浏览历史',
        payload: { plugin_ids: ['chrome-history'], installable_plugin_ids: [] }, status: 'unread', created_at_ms: 1, read_at_ms: null }],
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

  it('expanding a suggestion shows a connect button that opens activation', async () => {
    render(<NotificationCenter />);
    const row = await screen.findByTestId('notification-row');
    await userEvent.click(within(row).getByText('notifications.suggestionTitle'));
    await userEvent.click(await screen.findByTestId('notification-connect-chrome-history'));
    await waitFor(() => expect(sensorsApi.getStatus).toHaveBeenCalled());
  });

  it('shows dismissed footer and restores', async () => {
    render(<NotificationCenter />);
    // expand the 已忽略 footer
    await userEvent.click(await screen.findByRole('button', { name: /notifications.dismissedTitle/ }));
    await userEvent.click(await screen.findByRole('button', { name: 'notifications.restore' }));
    await waitFor(() => expect(suggestionsApi.clearDismissal).toHaveBeenCalledWith('music'));
  });
});
