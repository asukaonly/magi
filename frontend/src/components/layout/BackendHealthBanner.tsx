import { useTranslation } from 'react-i18next';
import { AlertTriangle, WifiOff, XCircle } from 'lucide-react';
import { useBackendHealthStore, type BackendHealthState, type BackendStatus } from '@/stores/backend-health';

const iconByStatus: Record<Exclude<BackendStatus, 'healthy'>, React.ElementType> = {
  degraded: AlertTriangle,
  offline: WifiOff,
  exited: XCircle,
};

export function getBackendHealthMessageKey(
  health: Pick<
    BackendHealthState,
    'status' | 'runtimeStatus' | 'startupState' | 'deferredReason' | 'llmReady' | 'agentRuntimeReady'
  >,
): `desktop.health.${string}` {
  if (health.status === 'offline' || health.status === 'exited') {
    return `desktop.health.${health.status}`;
  }

  if (health.startupState === 'starting') {
    return 'desktop.health.degradedStarting';
  }

  if (health.startupState === 'deferred') {
    if (health.deferredReason === 'llm_selection_pending') {
      return 'desktop.health.degradedDeferredSelectionPending';
    }
    if (health.deferredReason === 'llm_configuration_invalid') {
      return 'desktop.health.degradedDeferredInvalid';
    }
  }

  if (health.runtimeStatus === 'stale') {
    return 'desktop.health.degradedRuntimeOutOfSync';
  }

  if (health.runtimeStatus === 'unresponsive') {
    return 'desktop.health.degradedRuntimeUnresponsive';
  }

  if (health.llmReady === false) {
    return 'desktop.health.degradedLlmNotReady';
  }

  if (health.agentRuntimeReady === false) {
    return 'desktop.health.degradedAgentRuntimeNotReady';
  }

  return 'desktop.health.degraded';
}

const BackendHealthBanner: React.FC = () => {
  const { t } = useTranslation('app');
  const health = useBackendHealthStore((s) => ({
    status: s.status,
    runtimeStatus: s.runtimeStatus,
    startupState: s.startupState,
    deferredReason: s.deferredReason,
    llmReady: s.llmReady,
    agentRuntimeReady: s.agentRuntimeReady,
  }));

  if (health.status === 'healthy') return null;

  const Icon = iconByStatus[health.status];
  const i18nKey = getBackendHealthMessageKey(health);

  return (
    <div
      role="status"
      className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800"
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span>{t(i18nKey)}</span>
    </div>
  );
};

export default BackendHealthBanner;
