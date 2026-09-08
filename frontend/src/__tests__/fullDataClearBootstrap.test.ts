import { describe, expect, it, vi } from 'vitest';
import { recoverPendingCenterMaintenance } from '@/hooks/clearAllMemory';
import { finishPendingCenterMaintenanceBeforeAppReady } from '@/runtime/fullDataClearBootstrap';
vi.mock('@/hooks/clearAllMemory', () => ({ recoverPendingCenterMaintenance: vi.fn() }));
describe('center maintenance startup gate', () => {
  it('waits for center recovery without starting another runtime', async () => {
    let finish: (value: boolean) => void = () => undefined;
    vi.mocked(recoverPendingCenterMaintenance).mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    let continued = false;
    const gate = finishPendingCenterMaintenanceBeforeAppReady(vi.fn()).then(() => { continued = true; });
    await Promise.resolve(); expect(continued).toBe(false); finish(true); await gate; expect(continued).toBe(true);
  });
  it('keeps startup blocked when center recovery fails', async () => {
    vi.mocked(recoverPendingCenterMaintenance).mockRejectedValue(new Error('pending'));
    await expect(finishPendingCenterMaintenanceBeforeAppReady(vi.fn())).rejects.toThrow('pending');
  });
});
