import React from 'react';
import { useTranslation } from 'react-i18next';
import * as LucideIcons from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import type { PluginCapability } from '@/api/modules/plugins';
import { capabilityMeta, groupCapabilities } from '@/lib/pluginCapabilities';
import { PluginIcon } from './PluginIcon';

export type ConsentMode = 'install' | 'update' | 'sideload';

interface Props {
  open: boolean;
  mode: ConsentMode;
  pluginName: string;
  pluginIcon?: string | null;
  version: string;
  official?: boolean;
  capabilities: PluginCapability[];
  newCapabilities?: PluginCapability[];   // update mode highlight
  confirmDisabled?: boolean;
  statusMessage?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

function localizedReason(c: PluginCapability, lang: string, fallback: string): string {
  return c.reason_i18n?.[lang] ?? c.reason_i18n?.[lang.split('-')[0]] ?? (c.reason || fallback);
}

export const PluginConsentDialog: React.FC<Props> = ({
  open,
  mode,
  pluginName,
  pluginIcon,
  version,
  official,
  capabilities,
  newCapabilities,
  confirmDisabled = false,
  statusMessage,
  onConfirm,
  onCancel,
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
        className={`grid grid-cols-[1rem_minmax(0,1fr)] gap-x-2.5 py-2 ${highlight ? 'rounded-md bg-orange-50 px-2' : ''}`}>
        <Icon className="mt-0.5 h-4 w-4 text-muted-foreground" />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-sm font-medium leading-5">
            <span>{label}</span>
            {c.scope.length > 0 && (
              <span className="sr-only">:</span>
            )}
            {c.optional && (
              <span className="inline-flex items-center rounded border border-border/60 px-1 py-px text-[10px] font-normal leading-none text-muted-foreground/90">
                {t('settings.marketplace.consent.optionalTag')}
              </span>
            )}
          </div>
          {c.scope.length > 0 ? (
            <div className="mt-1 space-y-0.5">
              {c.scope.map((scope, scopeIndex) => (
                <code
                  key={`${scope}:${scopeIndex}`}
                  className="block max-w-full whitespace-normal break-words text-xs leading-5 text-muted-foreground [overflow-wrap:anywhere]"
                >
                  {scope}
                </code>
              ))}
            </div>
          ) : null}
          <div className="mt-1 text-xs leading-5 text-muted-foreground">{desc}</div>
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
        <DialogHeader className="pr-12">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-muted/55 shadow-[inset_0_0_0_1px_hsl(var(--border)/0.55)]">
              <PluginIcon
                iconId={pluginIcon}
                className="h-6 w-6"
              />
            </div>
            <div className="min-w-0 space-y-1.5 pt-0.5">
              <DialogTitle className="break-words leading-6">
                {t(`settings.marketplace.consent.title.${mode}`, { name: pluginName })}
              </DialogTitle>
              <DialogDescription className="text-xs text-muted-foreground">
                v{version} · {t(official
                  ? 'settings.marketplace.badge.official'
                  : 'settings.marketplace.consent.thirdParty')}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-3 overflow-y-auto px-6 pb-4">
          {mode === 'sideload' && (
            <div
              role="note"
              className="flex gap-2.5 rounded-md border border-amber-200/70 bg-amber-50/70 px-3 py-2.5 text-xs leading-5 text-amber-950"
            >
              <LucideIcons.ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{t('settings.marketplace.consent.sideloadWarning')}</span>
            </div>
          )}

          {isUpdate && (
            <div className="mb-1">
              <div className="text-sm font-medium text-orange-700">
                {t('settings.marketplace.consent.updateNewLede')}
              </div>
              {newCapabilities!.map((c, i) => renderRow(c, i, true))}
            </div>
          )}

          {statusMessage ? (
            <div
              role="status"
              className="rounded-md border border-border/70 bg-muted/35 px-3 py-2.5 text-sm text-muted-foreground"
            >
              {statusMessage}
            </div>
          ) : (
            <>
              <div className="text-sm">
                {capabilities.length === 0
                  ? t('settings.marketplace.consent.ledeEmpty')
                  : t('settings.marketplace.consent.lede')}
              </div>
              {capabilities.length > 0 && renderGroups(capabilities)}
            </>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" size="sm" onClick={onCancel}>
            {t('settings.marketplace.consent.cancel')}
          </Button>
          <Button size="sm" onClick={onConfirm} disabled={confirmDisabled}>
            {t(`settings.marketplace.consent.confirm.${confirmKey}`)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};

export default PluginConsentDialog;
