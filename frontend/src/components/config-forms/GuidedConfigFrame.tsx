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
      'overflow-hidden rounded-3xl border border-border/50 bg-background shadow-lg',
      className
    )}
  >
    <div className={cn('flex min-h-[clamp(560px,78vh,760px)] flex-col lg:flex-row', layoutClassName)}>
      {sidebar ? (
        <aside
          className={cn(
            'shrink-0 border-b border-border/40 bg-muted/30 px-5 py-6 lg:w-52 lg:border-b-0 lg:border-r',
            sidebarClassName
          )}
        >
          {sidebar}
        </aside>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col bg-background">
        <div className={cn('flex-1 overflow-y-auto p-5 sm:p-6 lg:p-7', contentClassName)}>
          {children}
        </div>
        {footer ? (
          <div className={cn('border-t border-border/40 px-5 py-4 sm:px-6 lg:px-7', footerClassName)}>
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  </div>
);

export default GuidedConfigFrame;
