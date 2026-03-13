import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MainLayout from '@/components/layout/MainLayout';
import { useChatShellStore } from '@/stores';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/components/layout/AppShellProviders', () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('@/components/layout/Sidebar', () => ({
  default: () => <aside data-testid="sidebar" />,
}));

vi.mock('@/components/layout/ShellOverlays', () => ({
  default: () => null,
}));

describe('main layout', () => {
  beforeEach(() => {
    useChatShellStore.setState({
      currentSessionId: null,
      sidebarCollapsed: false,
      activePanel: 'none',
    });
  });

  it('renders a compact titlebar toggle beside the window controls and keeps the drag strip clear of it', async () => {
    const user = userEvent.setup();

    const { container } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/chat" element={<div>chat page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    const toggleButton = screen.getByRole('button', { name: 'shell.collapseSidebar' });
    const dragStrip = container.querySelector('div[data-tauri-drag-region]') as HTMLDivElement | null;

    expect(dragStrip).not.toBeNull();
    expect(toggleButton).toHaveClass('h-7', 'w-7');
    expect((toggleButton as HTMLButtonElement).style.left).toBe('112px');
    expect(dragStrip?.style.left).toBe('148px');

    await user.click(toggleButton);

    expect(useChatShellStore.getState().sidebarCollapsed).toBe(true);
    expect(screen.getByRole('button', { name: 'shell.expandSidebar' })).toBeInTheDocument();
  });
});
