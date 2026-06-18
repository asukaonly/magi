import { Toaster } from 'sonner';
import { CheckCircle2 } from 'lucide-react';
import type { CSSProperties } from 'react';

const themedToastVariables = {
  '--normal-bg': 'hsl(var(--settings-shell-elevated))',
  '--normal-border': 'hsl(var(--settings-subnav-border) / 0.16)',
  '--normal-text': 'hsl(var(--foreground))',
  '--success-bg': 'hsl(var(--primary) / 0.09)',
  '--success-border': 'hsl(var(--primary) / 0.2)',
  '--success-text': 'hsl(var(--primary))',
} as CSSProperties;

export function AppToaster(): JSX.Element {
  return (
    <Toaster
      position="top-right"
      richColors
      closeButton
      style={themedToastVariables}
      icons={{
        success: <CheckCircle2 className="h-5 w-5 text-primary" />,
      }}
      toastOptions={{
        classNames: {
          toast:
            '!border-0 !shadow-[0_18px_46px_hsl(var(--foreground)/0.12),inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.16)]',
          success:
            '!shadow-[0_18px_46px_hsl(var(--foreground)/0.12),inset_0_0_0_1px_hsl(var(--primary)/0.22)]',
          title: '!font-semibold',
          icon: '!text-primary',
          closeButton:
            '!border-0 !shadow-[0_6px_16px_hsl(var(--foreground)/0.08),inset_0_0_0_1px_hsl(var(--settings-subnav-border)/0.2)] hover:!text-foreground',
        },
      }}
    />
  );
}
