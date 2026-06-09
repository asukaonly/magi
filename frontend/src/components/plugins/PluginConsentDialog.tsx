import React from 'react';
import { useTranslation } from 'react-i18next';
import * as LucideIcons from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import type { PluginCapability } from '@/api/modules/plugins';
import { capabilityMeta, groupCapabilities } from '@/lib/pluginCapabilities';

export type ConsentMode = 'install' | 'update' | 'sideload';

interface Props {
  open: boolean;
  mode: ConsentMode;
  pluginName: string;
  version: string;
  official?: boolean;
  capabilities: PluginCapability[];
  newCapabilities?: PluginCapability[];   // update mode highlight
  onConfirm: () => void;
  onCancel: () => void;
}

function localizedReason(c: PluginCapability, lang: string, fallback: string): string {
  return c.reason_i18n?.[lang] ?? c.reason_i18n?.[lang.split('-')[0]] ?? (c.reason || fallback);
}

export const PluginConsentDialog: React.FC<Props> = ({
  open, mode, pluginName, version, official, capabilities, newCapabilities, onConfirm, onCancel,
}) => {
  const { t, i18n } = useTranslation('app');
  const lang = i18n.language;
  const confirmKey = mode === 'update' ? 'update' : 'install';

  const renderRow = (c: PluginCapability, idx: number, highlight = false) => {
    const meta = capabilityMeta(c.capability);
    const Icon = (LucideIcons as unknown as Record<string, React.ComponentType<{ className?: string }>>)[meta.icon]
      ?? LucideIcons.Shield;
    const label = t(`${meta.i18nKey}.label`);
    const desc = localizedReason(c, lang, t(`${meta.i18nKey}.desc`));
    return (
      <div key={`${c.capability}:${c.scope.join(',')}:${idx}`}
        className={`flex gap-2 py-1.5 ${highlight ? 'rounded-md bg-orange-50 px-2' : ''}`}>
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <div className="text-sm font-medium">
            {label}
            {c.scope.length > 0 && (
              <code className="ml-1.5 text-xs text-muted-foreground">{c.scope.join(', ')}</code>
            )}
            {c.optional && (
              <span className="ml-1.5 inline-flex items-center rounded border border-border/60 px-1 py-px text-[10px] font-normal leading-none text-muted-foreground/90 align-[1px]">
                {t('settings.marketplace.consent.optionalTag')}
              </span>
            )}
          </div>
          <div className="text-xs text-muted-foreground">{desc}</div>
        </div>
      </div>
    );
  };

  const renderGroups = (caps: PluginCapability[]) => {
    const { system, data } = groupCapabilities(caps);
    return (
      <>
        {system.length > 0 && (
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {t('settings.marketplace.consent.groupSystem')}
            </div>
            {system.map((c, i) => renderRow(c, i))}
          </div>
        )}
        {data.length > 0 && (
          <div>
            <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              {t('settings.marketplace.consent.groupData')}
            </div>
            {data.map((c, i) => renderRow(c, i))}
          </div>
        )}
      </>
    );
  };

  const isUpdate = mode === 'update' && (newCapabilities?.length ?? 0) > 0;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onCancel(); }}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {t(`settings.marketplace.consent.title.${mode}`, { name: pluginName })}
          </DialogTitle>
          <DialogDescription className="text-xs text-muted-foreground">
            v{version} · {t(official
              ? 'settings.marketplace.badge.official'
              : 'settings.marketplace.consent.thirdParty')}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-3 overflow-y-auto px-6 pb-4">
          {isUpdate && (
            <div className="mb-1">
              <div className="text-sm font-medium text-orange-700">
                {t('settings.marketplace.consent.updateNewLede')}
              </div>
              {newCapabilities!.map((c, i) => renderRow(c, i, true))}
            </div>
          )}

          <div className="text-sm">
            {capabilities.length === 0
              ? t('settings.marketplace.consent.ledeEmpty')
              : t('settings.marketplace.consent.lede')}
          </div>
          {capabilities.length > 0 && renderGroups(capabilities)}
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onCancel}>
            {t('settings.marketplace.consent.cancel')}
          </Button>
          <Button size="sm" onClick={onConfirm}>
            {t(`settings.marketplace.consent.confirm.${confirmKey}`)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default PluginConsentDialog;
