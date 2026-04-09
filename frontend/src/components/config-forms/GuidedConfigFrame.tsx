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
    className={cn(
      'max-h-[calc(100vh-2rem)] overflow-hidden rounded-3xl border border-border/50 bg-background shadow-lg',
      className
    )}
  >
    <div className={cn('flex min-h-0 min-w-0 flex-col lg:flex-row', layoutClassName)}>
      {sidebar ? (
        <aside
          className={cn(
            'shrink-0 overflow-y-auto border-b border-border/40 bg-muted/30 px-5 py-6 lg:w-52 lg:border-b-0 lg:border-r',
            sidebarClassName
          )}
        >
          {sidebar}
        </aside>
      ) : null}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-background">
        <div className={cn('flex min-h-0 flex-1 flex-col overflow-y-auto p-5 sm:p-6 lg:p-7', contentClassName)}>
          {children}
        </div>
        {footer ? (
          <div className={cn('shrink-0 border-t border-border/40 px-5 py-4 sm:px-6 lg:px-7', footerClassName)}>
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  </div>
);

export default GuidedConfigFrame;
