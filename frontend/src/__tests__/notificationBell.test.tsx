import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { NotificationBell } from '@/components/layout/NotificationBell';
import * as api from '@/api/modules/notifications';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k, i18n: { language: 'zh-CN' } }) }));

describe('NotificationBell', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, 'listNotifications').mockResolvedValue({ items: [], total: 3, unread_count: 3 });
  });
  it('renders the bell with an unread badge', async () => {
    render(<NotificationBell />);
    expect(await screen.findByText('3')).toBeInTheDocument();        // badge
    expect(screen.getByRole('button', { name: /notifications.bellAria/i })).toBeInTheDocument();
  });
});
