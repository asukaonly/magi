import { recoverPendingFullDataClear } from '@/hooks/clearAllMemory';
import { dispatchAppEvent } from '@/constants/events';
import {
  restartRuntimeAfterFullDataClear,
  type RuntimeConfig,
  type StartupPhase,
} from './config';

type RestartRuntime = (
  onPhase: (phase: StartupPhase) => void,
) => Promise<RuntimeConfig>;

export interface FullDataClearBootstrapOptions {
  restartRuntime?: RestartRuntime;
  releaseInteractionGateWhenNotPending?: boolean;
}

export async function finishPendingFullDataClearBeforeAppReady(
  onPhase: (phase: StartupPhase) => void,
  options: FullDataClearBootstrapOptions = {},
): Promise<RuntimeConfig | null> {
  onPhase('recovering_data_clear');
  const recovered = await recoverPendingFullDataClear();
  if (!recovered) {
    if (options.releaseInteractionGateWhenNotPending) {
      dispatchAppEvent.memoryClearRecoveryReleased();
    }
    return null;
  }
  return (options.restartRuntime ?? restartRuntimeAfterFullDataClear)(onPhase);
}
