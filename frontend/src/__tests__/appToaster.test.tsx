import { render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const toasterPropsRef = vi.hoisted(() => ({
  current: null as null | { style?: Record<string, string> },
}));

vi.mock('sonner', () => ({
  Toaster: (props: { style?: Record<string, string> }) => {
    toasterPropsRef.current = props;
    return <div data-testid="app-toaster" />;
  },
}));

import { AppToaster } from '@/components/ui/sonner';

describe('AppToaster', () => {
  it('uses an opaque background for success toasts', () => {
    render(<AppToaster />);

    expect(toasterPropsRef.current?.style?.['--success-bg']).toBe(
      'hsl(var(--settings-shell-elevated))',
    );
  });
});
