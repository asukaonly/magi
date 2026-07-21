import React from 'react';
import { cn } from '@/lib/utils';

interface GuidedConfigFrameProps {
  children: React.ReactNode;
  sidebar?: React.ReactNode;
  footer?: React.ReactNode;
  className?: string;
  layoutClassName?: string;
  sidebarClassName?: string;
  contentClassName?: string;
  footerClassName?: string;
}

export const GuidedConfigFrame: React.FC<GuidedConfigFrameProps> = ({
  children,
  sidebar,
  footer,
  className,
  layoutClassName,
  sidebarClassName,
  contentClassName,
  footerClassName,
}) => (
  <div
    data-testid="guided-config-frame"
    className={cn(
      'h-full w-full overflow-hidden bg-muted/25',
      className
    )}
  >
    <div
      className={cn(
        'grid min-h-0 min-w-0 grid-rows-[auto_minmax(0,1fr)] lg:grid-cols-[11.5rem_minmax(0,1fr)] lg:grid-rows-1',
        layoutClassName,
      )}
    >
      {sidebar ? (
        <aside
          className={cn(
            'shrink-0 overflow-x-auto bg-muted/70 px-4 py-3 lg:w-auto lg:overflow-x-hidden lg:overflow-y-auto lg:px-5 lg:py-8',
            sidebarClassName
          )}
        >
          {sidebar}
        </aside>
      ) : null}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
        <main
          data-testid="guided-config-content"
          className={cn(
            'flex h-full min-h-0 flex-1 flex-col overflow-hidden p-4 sm:p-6 lg:px-8 lg:py-7 xl:px-10',
            contentClassName,
          )}
        >
          {children}
        </main>
        {footer ? (
          <footer
            className={cn(
              'relative z-10 shrink-0 bg-background px-4 py-4 sm:px-6 lg:px-8 xl:px-10',
              footerClassName,
            )}
          >
            {footer}
          </footer>
        ) : null}
      </div>
    </div>
  </div>
);

export default GuidedConfigFrame;
