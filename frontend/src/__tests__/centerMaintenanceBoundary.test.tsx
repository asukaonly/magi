import { useState } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CenterMaintenanceBoundary } from '@/components/connections/CenterMaintenanceBoundary';
import type { FullDataClearInteractionGate } from '@/hooks/useFullDataClearInteractionGate';

function Draft() {
  const [text, setText] = useState('');
  return <input aria-label="Draft" value={text} onChange={(event) => setText(event.target.value)} />;
}
const idle: FullDataClearInteractionGate = { status: 'idle', kind: null, message: null };
describe('center maintenance interaction boundary', () => {
  it('preserves mounted drafts across memory restore and failed retries', () => {
    const retry = vi.fn();
    const view = (gate: FullDataClearInteractionGate) => <CenterMaintenanceBoundary gate={gate} onRetry={retry}><Draft /></CenterMaintenanceBoundary>;
    const { rerender } = render(view(idle));
    fireEvent.change(screen.getByLabelText('Draft'), { target: { value: 'unsent text' } });
    rerender(view({ status: 'running', kind: 'restore', message: null }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByLabelText('Draft')).not.toBeVisible();
    rerender(view({ status: 'failed', kind: 'restore', message: 'Connection interrupted' }));
    fireEvent.click(screen.getByRole('button'));
    expect(retry).toHaveBeenCalledOnce();
    rerender(view(idle));
    expect(screen.getByLabelText('Draft')).toHaveValue('unsent text');
  });
  it('retires mounted content during full data clear', () => {
    const view = (gate: FullDataClearInteractionGate) => <CenterMaintenanceBoundary gate={gate} onRetry={() => undefined}><Draft /></CenterMaintenanceBoundary>;
    const { rerender } = render(view(idle));
    fireEvent.change(screen.getByLabelText('Draft'), { target: { value: 'private draft' } });
    rerender(view({ status: 'running', kind: 'clear', message: null }));
    expect(screen.queryByLabelText('Draft')).toBeNull();
    rerender(view(idle));
    expect(screen.getByLabelText('Draft')).toHaveValue('');
  });
});
