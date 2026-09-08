import { recoverPendingCenterMaintenance } from '@/hooks/clearAllMemory';
import { dispatchAppEvent } from '@/constants/events';
import type { StartupPhase } from './config';

export async function finishPendingCenterMaintenanceBeforeAppReady(
  onPhase: (phase: StartupPhase) => void,
  options: { releaseInteractionGateWhenNotPending?: boolean } = {},
): Promise<void> {
  onPhase('recovering_maintenance');
  await recoverPendingCenterMaintenance(options.releaseInteractionGateWhenNotPending === true);
  dispatchAppEvent.memoryClearRecoveryReleased();
}
