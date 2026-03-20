import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import MainLayout from '@/components/layout/MainLayout';
import { useChatShellStore, useChatTraceStore } from '@/stores';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock('@/components/layout/AppShellProviders', () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));

vi.mock('@/components/layout/Sidebar', () => ({
  default: ({ collapsed }: { collapsed?: boolean }) => (collapsed ? null : <aside data-testid="sidebar" />),
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
    useChatTraceStore.getState().reset();
  });

  it('renders a compact titlebar toggle beside the window controls and keeps the drag strip shallow enough to avoid page actions', async () => {
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
    expect(dragStrip).toHaveClass('h-4');
    expect((toggleButton as HTMLButtonElement).style.left).toBe('84px');
    expect((toggleButton as HTMLButtonElement).style.top).toBe('14px');
    expect(dragStrip?.style.left).toBe('120px');
    expect(screen.getByText('chat page').closest('div.min-h-0.min-w-0')).toHaveClass('col-start-2');

    await user.click(toggleButton);

    expect(useChatShellStore.getState().sidebarCollapsed).toBe(true);
    expect(screen.getByRole('button', { name: 'shell.expandSidebar' })).toBeInTheDocument();
  });

  it('hides the sidebar toggle while the toolchain drawer is open', () => {
    useChatTraceStore.getState().openDrawer('turn-1');

    render(
      <MemoryRouter initialEntries={['/chat']}>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/chat" element={<div>chat page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    expect(screen.queryByRole('button', { name: 'shell.collapseSidebar' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'shell.expandSidebar' })).not.toBeInTheDocument();
  });
});
