import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { pluginsApi, type PluginPackageState } from '@/api/modules/plugins';
import { Button } from '@/components/ui/button';
import { PluginConsentDialog } from './PluginConsentDialog';

export function PluginPackageTrust({ plugin, onAuthorized }: {
  plugin: PluginPackageState;
  onAuthorized: () => Promise<void>;
}) {
  const { t } = useTranslation('app');
  const [review, setReview] = useState<PluginPackageState | null>(null);
  const [busy, setBusy] = useState(false);
  if (plugin.trusted) return null;

  const authorize = async () => {
    if (!review?.package_sha256 || busy) return;
    setBusy(true);
    try {
      await pluginsApi.authorizePackage(review.manifest.plugin_id, review.package_sha256);
      setReview(null);
      await onAuthorized();
      toast.success(t('plugins.trust.authorized'));
    } catch {
      toast.error(t('plugins.trust.failed'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <Button variant="outline" size="sm" disabled={!plugin.package_sha256 || busy}
        onClick={() => setReview(plugin)}>{t('plugins.trust.review')}</Button>
      {!plugin.package_sha256 ? <p className="text-xs text-muted-foreground">{t('plugins.trust.reinstall')}</p> : null}
      {review ? <PluginConsentDialog open mode="trust" pluginName={review.manifest.name}
        pluginIcon={review.manifest.icon} version={review.manifest.version} official={review.manifest.official}
        executionMode={review.manifest.execution_mode} capabilities={review.manifest.capabilities}
        confirmDisabled={busy} onConfirm={() => void authorize()} onCancel={() => { if (!busy) setReview(null); }} /> : null}
    </div>
  );
}
