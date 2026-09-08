import { recoverPendingFullDataClear } from '@/hooks/clearAllMemory';
import { dispatchAppEvent } from '@/constants/events';
import type { StartupPhase } from './config';

export async function finishPendingFullDataClearBeforeAppReady(
  onPhase: (phase: StartupPhase) => void,
  options: { releaseInteractionGateWhenNotPending?: boolean } = {},
): Promise<void> {
  onPhase('recovering_data_clear');
  await recoverPendingFullDataClear(options.releaseInteractionGateWhenNotPending === true);
  dispatchAppEvent.memoryClearRecoveryReleased();
}
