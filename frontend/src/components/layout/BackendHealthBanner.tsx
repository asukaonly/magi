import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { useBackendHealthStore, type BackendHealthState } from '@/stores/backend-health';

export function getBackendHealthMessageKey(
  health: Pick<
    BackendHealthState,
    'status' | 'startupState' | 'deferredReason'
  >,
): `desktop.health.${string}` | null {
  if (health.status !== 'degraded') return null;

  if (health.startupState === 'deferred') {
    if (health.deferredReason === 'llm_selection_pending') {
      return 'desktop.health.degradedDeferredSelectionPending';
    }
    if (health.deferredReason === 'llm_configuration_invalid') {
      return 'desktop.health.degradedDeferredInvalid';
    }
  }

  // Transport recovery and optional runtime startup do not require user action.
  return null;
}

const BackendHealthBanner: React.FC = () => {
  const { t } = useTranslation('app');
  const health = useBackendHealthStore((s) => ({
    status: s.status,
    startupState: s.startupState,
    deferredReason: s.deferredReason,
  }));

  const i18nKey = getBackendHealthMessageKey(health);
  if (!i18nKey) return null;

  return (
    <div
      role="status"
      className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800"
    >
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span>{t(i18nKey)}</span>
    </div>
  );
};

export default BackendHealthBanner;
