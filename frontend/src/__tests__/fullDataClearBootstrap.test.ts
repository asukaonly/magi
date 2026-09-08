import { describe, expect, it, vi } from 'vitest';
import { recoverPendingFullDataClear } from '@/hooks/clearAllMemory';
import { finishPendingFullDataClearBeforeAppReady } from '@/runtime/fullDataClearBootstrap';
vi.mock('@/hooks/clearAllMemory', () => ({ recoverPendingFullDataClear: vi.fn() }));
describe('center maintenance startup gate', () => {
  it('waits for center recovery without starting another runtime', async () => {
    let finish: (value: boolean) => void = () => undefined;
    vi.mocked(recoverPendingFullDataClear).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    let continued = false;
    const gate = finishPendingFullDataClearBeforeAppReady(vi.fn()).then(() => { continued = true; });
    await Promise.resolve(); expect(continued).toBe(false); finish(true); await gate; expect(continued).toBe(true);
  });
  it('keeps startup blocked when center recovery fails', async () => {
    vi.mocked(recoverPendingFullDataClear).mockRejectedValue(new Error('pending'));
    await expect(finishPendingFullDataClearBeforeAppReady(vi.fn())).rejects.toThrow('pending');
  });
});
