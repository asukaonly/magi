import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { NotificationCenter } from '@/components/notifications/NotificationCenter';
import * as api from '@/api/modules/notifications';
import { sensorsApi } from '@/api/modules/sensors';

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
    vi.spyOn(sensorsApi, 'getStatus').mockResolvedValue({ sources: [
      { plugin_id: 'chrome-history', source_name: 'chrome', activation_flow: { enabled_key: 'enabled', configured_key: 'configured', authorize_on_confirm: false, fields: [] } },
    ] } as any);
  });

  it('lists notifications and marks one read on expand', async () => {
    render(<NotificationCenter />);
    const row = await screen.findByText('看浏览历史');
    await userEvent.click(row);                       // expand → mark that row read
    await waitFor(() => expect(api.markRead).toHaveBeenCalledWith([1]));
  });

  it('mark-all-read button calls markAllRead', async () => {
    render(<NotificationCenter />);
    await screen.findByText('看浏览历史');
    await userEvent.click(screen.getByRole('button', { name: /notifications.markAllRead/i }));
    expect(api.markAllRead).toHaveBeenCalled();
  });

  it('expanding a suggestion shows a connect button that opens activation', async () => {
    render(<NotificationCenter />);
    await userEvent.click(await screen.findByText('看浏览历史'));
    await userEvent.click(await screen.findByTestId('empty-state-connect-chrome-history'));
    await waitFor(() => expect(sensorsApi.getStatus).toHaveBeenCalled());
  });
});
