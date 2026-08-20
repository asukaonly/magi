import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { DesktopTitleBar } from '@/components/layout/DesktopTitleBar';
import { PreAppWindowFrame } from '@/components/layout/PreAppWindowFrame';

const {
  closeMock,
  minimizeMock,
  startDraggingMock,
  toggleMaximizeMock,
} = vi.hoisted(() => ({
  closeMock: vi.fn(),
  minimizeMock: vi.fn(),
  startDraggingMock: vi.fn(),
  toggleMaximizeMock: vi.fn(),
}));

vi.mock('@/lib/platform', () => ({
  isMacPlatform: () => false,
}));

vi.mock('@tauri-apps/api/window', () => ({
  getCurrentWindow: () => ({
    close: closeMock,
    minimize: minimizeMock,
    startDragging: startDraggingMock,
    toggleMaximize: toggleMaximizeMock,
  }),
}));

describe('DesktopTitleBar', () => {
  beforeEach(() => {
    closeMock.mockReset();
    minimizeMock.mockReset();
    startDraggingMock.mockReset();
    toggleMaximizeMock.mockReset();
  });

  it('starts a native drag and handles double-click maximize', async () => {
    render(<DesktopTitleBar />);
    const titleBar = screen.getByTestId('desktop-title-bar');

    fireEvent.mouseDown(titleBar, { button: 0, detail: 1 });
    await waitFor(() => expect(startDraggingMock).toHaveBeenCalledTimes(1));

    fireEvent.mouseDown(titleBar, { button: 0, detail: 2 });
    await waitFor(() => expect(toggleMaximizeMock).toHaveBeenCalledTimes(1));
  });

  it('does not start dragging from interactive content', async () => {
    render(
      <DesktopTitleBar>
        <button type="button">Action</button>
      </DesktopTitleBar>,
    );

    fireEvent.mouseDown(screen.getByRole('button', { name: 'Action' }), {
      button: 0,
      detail: 1,
    });

    await Promise.resolve();
    expect(startDraggingMock).not.toHaveBeenCalled();
    expect(toggleMaximizeMock).not.toHaveBeenCalled();
  });

  it('exposes native window controls and frames pre-app content', async () => {
    render(
      <PreAppWindowFrame>
        <div>Startup content</div>
      </PreAppWindowFrame>,
    );

    expect(screen.getByText('Startup content')).toBeInTheDocument();
    expect(screen.getByTestId('desktop-title-bar')).toBeInTheDocument();

    fireEvent.click(await screen.findByRole('button', { name: 'Close' }));
    await waitFor(() => expect(closeMock).toHaveBeenCalledTimes(1));
  });
});
