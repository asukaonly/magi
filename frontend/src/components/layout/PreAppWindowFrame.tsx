import type { ReactNode } from 'react';
import { DesktopTitleBar } from './DesktopTitleBar';

/**
 * Window frame used before the routed application shell is ready.
 */
export const PreAppWindowFrame = ({ children }: { children: ReactNode }) => (
  <div className="flex h-screen w-screen flex-col overflow-hidden bg-background">
    <DesktopTitleBar />
    <div className="min-h-0 flex-1 overflow-auto">{children}</div>
  </div>
);
