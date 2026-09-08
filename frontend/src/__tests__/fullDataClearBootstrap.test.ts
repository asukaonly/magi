import { describe, expect, it, vi } from 'vitest';
import { recoverPendingCenterMaintenance } from '@/hooks/clearAllMemory';
import { finishPendingCenterMaintenanceBeforeAppReady } from '@/runtime/fullDataClearBootstrap';
vi.mock('@/hooks/clearAllMemory', () => ({ recoverPendingCenterMaintenance: vi.fn() }));
describe('center maintenance startup gate', () => {
  it('waits for center recovery without starting another runtime', async () => {
    let finish: (value: boolean) => void = () => undefined;
    vi.mocked(recoverPendingCenterMaintenance).mockImplementation((_retry, onPending) => {
      onPending?.();
      return new Promise((resolve) => { finish = resolve; });
    });
    let continued = false;
    const phase = vi.fn();
    const gate = finishPendingCenterMaintenanceBeforeAppReady(phase).then(() => { continued = true; });
    await Promise.resolve(); expect(continued).toBe(false); finish(true); await gate; expect(continued).toBe(true);
    expect(phase.mock.calls).toEqual([['connecting'], ['recovering_maintenance']]);
  });
  it('does not describe a failed status read as active maintenance', async () => {
    vi.mocked(recoverPendingCenterMaintenance).mockRejectedValue({ message: 'Network Error' });
    const phase = vi.fn();
    await expect(finishPendingCenterMaintenanceBeforeAppReady(phase)).rejects.toMatchObject({ message: 'Network Error' });
    expect(phase.mock.calls).toEqual([['connecting']]);
  });
  it('keeps startup blocked when center recovery fails', async () => {
    vi.mocked(recoverPendingCenterMaintenance).mockRejectedValue(new Error('pending'));
    await expect(finishPendingCenterMaintenanceBeforeAppReady(vi.fn())).rejects.toThrow('pending');
  });
});
