import i18n from '@/i18n';
import { render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { AppTitleBar } from '@/components/layout/AppTitleBar';

vi.mock('react-router', () => ({
  useLocation: () => ({ pathname: '/' }),
}));

vi.mock('@/lib/platform', () => ({
  isMacPlatform: () => true,
}));

vi.mock('@/stores', () => ({
  useChatShellStore: (selector: (state: Record<string, unknown>) => unknown) => selector({
    portraitRailOpen: false,
    setPortraitRailOpen: vi.fn(),
    timelinePanel: {},
  }),
  useConversationStore: (selector: (state: Record<string, unknown>) => unknown) => selector({
    currentSessionId: null,
  }),
}));

vi.mock('@/components/layout/DesktopTitleBar', () => ({
  DesktopTitleBar: ({ children }: { children?: ReactNode }) => (
    <div data-testid="desktop-title-bar">{children}</div>
  ),
}));

vi.mock('@/components/layout/NotificationBell', () => ({
  NotificationBell: () => <button type="button">Notifications</button>,
}));

describe('AppTitleBar', () => {
  it('does not repeat the active connection name in the window chrome', () => {
    render(<AppTitleBar />);

    expect(screen.getByTestId('desktop-title-bar')).toBeInTheDocument();
    expect(screen.queryByText(i18n.t('connections.local', { ns: 'app' }))).not.toBeInTheDocument();
  });
});
