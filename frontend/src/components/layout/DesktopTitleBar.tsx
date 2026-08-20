import React, { useCallback } from 'react';
import { isMacPlatform } from '@/lib/platform';
import { cn } from '@/lib/utils';
import { AppWindowControls } from './AppWindowControls';

const NO_DRAG_SELECTOR = [
  'button',
  'a',
  'input',
  'select',
  'textarea',
  '[data-no-drag]',
  '[role="menu"]',
  '[role="combobox"]',
].join(', ');

type DesktopTitleBarProps = {
  children?: React.ReactNode;
  className?: string;
  fixed?: boolean;
};

/**
 * Shared window chrome for desktop surfaces that do not use native decorations.
 * Interactive descendants are excluded from dragging, while the remaining stripe
 * supports native dragging and double-click maximize.
 */
export const DesktopTitleBar = ({
  children,
  className,
  fixed = false,
}: DesktopTitleBarProps) => {
  const isMac = isMacPlatform();

  const handleMouseDown = useCallback(async (event: React.MouseEvent) => {
    if (event.button !== 0) {
      return;
    }

    const target = event.target as HTMLElement | null;
    if (target?.closest?.(NO_DRAG_SELECTOR)) {
      return;
    }

    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      const window = getCurrentWindow();
      if (event.detail >= 2) {
        await window.toggleMaximize();
      } else {
        await window.startDragging();
      }
    } catch {
      // Keep browser previews usable when the Tauri window API is unavailable.
    }
  }, []);

  return (
    <div
      data-testid="desktop-title-bar"
      className={cn(
        fixed ? 'fixed inset-x-0 top-0 z-[100]' : 'relative z-30',
        'flex h-9 shrink-0 select-none items-center',
        'bg-[hsl(var(--app-chrome-surface))]',
        'shadow-[inset_0_-1px_0_hsl(var(--app-chrome-divider)/0.42)]',
        className,
      )}
      onMouseDown={handleMouseDown}
    >
      <div className={cn('shrink-0', isMac ? 'w-[72px]' : 'w-3')} />
      {children ?? <div className="min-w-0 flex-1" />}
      {!isMac ? <AppWindowControls className="ml-1" /> : null}
    </div>
  );
};
