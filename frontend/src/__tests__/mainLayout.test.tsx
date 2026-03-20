import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { render, screen } from '@testing-library/react';
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

  it('does not render a standalone sidebar toggle and keeps the drag strip anchored near the window controls', () => {
    const { container } = render(
      <MemoryRouter initialEntries={['/chat']}>
        <Routes>
          <Route element={<MainLayout />}>
            <Route path="/chat" element={<div>chat page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>
    );

    const dragStrip = container.querySelector('div[data-tauri-drag-region]') as HTMLDivElement | null;

    expect(dragStrip).not.toBeNull();
    expect(dragStrip).toHaveClass('h-4');
    expect(dragStrip?.style.left).toBe('84px');
    expect(screen.getByText('chat page').closest('div.min-h-0.min-w-0')).toHaveClass('col-start-2');
    expect(screen.queryByRole('button', { name: 'shell.collapseSidebar' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'shell.expandSidebar' })).not.toBeInTheDocument();
  });

  it('still keeps the standalone toggle hidden while the toolchain drawer is open', () => {
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
