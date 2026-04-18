import { useTranslation } from 'react-i18next';
import { AlertTriangle, WifiOff, XCircle } from 'lucide-react';
import { useBackendHealthStore, type BackendStatus } from '@/stores/backend-health';

const iconByStatus: Record<Exclude<BackendStatus, 'healthy'>, React.ElementType> = {
  degraded: AlertTriangle,
  offline: WifiOff,
  exited: XCircle,
};

const BackendHealthBanner: React.FC = () => {
  const { t } = useTranslation('app');
  const status = useBackendHealthStore((s) => s.status);

  if (status === 'healthy') return null;

  const Icon = iconByStatus[status];
  const i18nKey = `desktop.health.${status}` as const;

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
