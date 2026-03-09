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
      'overflow-hidden rounded-[28px] border border-violet-500/25 bg-background shadow-[0_24px_72px_-36px_rgba(124,58,237,0.45)]',
      className
    )}
  >
    <div className={cn('flex min-h-[clamp(560px,78vh,760px)] flex-col lg:flex-row', layoutClassName)}>
      {sidebar ? (
        <aside
          className={cn(
            'shrink-0 border-b border-violet-500/15 bg-[linear-gradient(180deg,rgba(124,58,237,0.12),rgba(124,58,237,0.03))] px-5 py-6 lg:w-52 lg:border-b-0 lg:border-r',
            sidebarClassName
          )}
        >
          {sidebar}
        </aside>
      ) : null}

      <div className="flex min-w-0 flex-1 flex-col bg-[radial-gradient(120%_120%_at_100%_0%,rgba(124,58,237,0.08)_0%,rgba(124,58,237,0.03)_28%,transparent_56%),linear-gradient(180deg,rgba(255,255,255,0.02),rgba(255,255,255,0))]">
        <div className={cn('flex-1 overflow-y-auto p-5 sm:p-6 lg:p-7', contentClassName)}>
          {children}
        </div>
        {footer ? (
          <div className={cn('border-t border-violet-500/12 px-5 py-4 sm:px-6 lg:px-7', footerClassName)}>
            {footer}
          </div>
        ) : null}
      </div>
    </div>
  </div>
);

export default GuidedConfigFrame;
