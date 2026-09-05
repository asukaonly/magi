import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { ExternalLink, RefreshCw, Shield, ShieldAlert, ShieldCheck } from 'lucide-react';

import {
  pluginsApi,
  type PluginPermissionStatus,
  type PluginPermissionStatusItem,
  type PluginSettingsResourceGroup,
  type PluginSettingsUiBlockSpec,
} from '@/api/modules/plugins';
import { Button } from '@/components/ui/button';
import { openExternalUrl } from '@/runtime/desktop';

interface PluginSettingsCustomBlocksProps {
  connectionId: string;
  blocks: PluginSettingsUiBlockSpec[];
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
}

/**
 * Resolution order (Phase 4):
 *   1. ``block.title_translated`` / ``block.description_translated`` (API, plugin i18n)
 *   2. raw ``block.title`` / ``block.description`` (English fallback from the manifest)
 */
const getBlockTitle = (block: PluginSettingsUiBlockSpec) => block.title_translated || block.title;

const getBlockDescription = (block: PluginSettingsUiBlockSpec) =>
  block.description_translated || block.description;

const isBlockVisible = (block: PluginSettingsUiBlockSpec, values: Record<string, any>) => {
  if (!block.depends_on_key || !block.depends_on_values?.length) {
    return true;
  }
  return block.depends_on_values.includes(String(values[block.depends_on_key] ?? ''));
};

const CalendarListResourcePicker: React.FC<{
  connectionId: string;
  block: PluginSettingsUiBlockSpec;
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
}> = ({ connectionId, block, values, onChange }) => {
  const { t } = useTranslation('app');
  const [groups, setGroups] = useState<PluginSettingsResourceGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedIds = useMemo(() => {
    const value = values[block.value_key];
    return Array.isArray(value) ? value.map(String) : [];
  }, [block.value_key, values]);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const payload = await pluginsApi.getSettingsResource(connectionId, block.resource_name);
        if (cancelled) {
          return;
        }
        setGroups(Array.isArray(payload.data?.groups) ? payload.data.groups : []);
      } catch (fetchError: any) {
        if (cancelled) {
          return;
        }
        setError(fetchError?.message || 'unknown');
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, [block.resource_name, connectionId]);

  const toggleItem = (itemId: string, checked: boolean) => {
    const nextIds = checked
      ? [...selectedIds, itemId]
      : selectedIds.filter((existingId) => existingId !== itemId);
    onChange(block.value_key, nextIds);
  };

  return (
    <div className="space-y-4 rounded-xl border border-[hsl(var(--settings-subnav-border)/0.7)] bg-[hsl(var(--background))] p-4">
      <div className="space-y-1">
        <h4 className="text-sm font-medium text-foreground">{getBlockTitle(block)}</h4>
        <p className="text-xs leading-6 text-muted-foreground">{getBlockDescription(block)}</p>
      </div>

      {loading ? <p className="text-sm text-muted-foreground">{t('settings.timeline.resourceBlocks.loading')}</p> : null}
      {!loading && error ? (
        <p className="text-sm text-destructive">
          {t('settings.timeline.errors.resourceLoadFailed', { message: error })}
        </p>
      ) : null}
      {!loading && !error && groups.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t('settings.timeline.resourceBlocks.empty')}</p>
      ) : null}

      {!loading && !error ? (
        <div className="space-y-3">
          {groups.map((group) => (
            <div key={group.group_id} className="space-y-2">
              <div className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                {group.label}
              </div>
              <div className="space-y-1">
                {group.items.map((item) => (
                  <label
                    key={item.item_id}
                    className="flex items-center gap-2.5 rounded-lg border border-transparent px-2.5 py-1.5 transition-colors hover:bg-muted/40"
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-input"
                      aria-label={item.label}
                      checked={selectedIds.includes(item.item_id)}
                      onChange={(event) => toggleItem(item.item_id, event.target.checked)}
                    />
                    <div className="min-w-0">
                      <div className="text-sm text-foreground">{item.label}</div>
                      {item.description ? (
                        <div className="text-xs text-muted-foreground">{item.description}</div>
                      ) : null}
                    </div>
                  </label>
                ))}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
};

const getPermissionStatusKey = (status: PluginPermissionStatus): string => {
  switch (status) {
    case 'granted':
      return 'settings.permissionStatus.statuses.granted';
    case 'denied':
      return 'settings.permissionStatus.statuses.denied';
    case 'not_determined':
      return 'settings.permissionStatus.statuses.notDetermined';
    case 'unknown':
    default:
      return 'settings.permissionStatus.statuses.unknown';
  }
};

const renderPermissionIcon = (status: PluginPermissionStatus) => {
  if (status === 'granted') {
    return <ShieldCheck className="h-5 w-5 text-emerald-600" aria-hidden="true" />;
  }
  if (status === 'denied') {
    return <ShieldAlert className="h-5 w-5 text-amber-600" aria-hidden="true" />;
  }
  if (status === 'not_determined') {
    return <Shield className="h-5 w-5 text-amber-500" aria-hidden="true" />;
  }
  return <Shield className="h-5 w-5 text-muted-foreground" aria-hidden="true" />;
};

const PermissionStatusBlock: React.FC<{
  connectionId: string;
  block: PluginSettingsUiBlockSpec;
}> = ({ connectionId, block }) => {
  const { t } = useTranslation('app');
  const [items, setItems] = useState<PluginPermissionStatusItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generation = useRef(0);
  const load = useCallback(async () => {
    const request = ++generation.current;
    setLoading(true);
    setError(null);
    try {
      const payload = await pluginsApi.getSettingsResource(connectionId, block.resource_name);
      if (request !== generation.current) return;
      const rawItems = Array.isArray(payload.data?.items) ? payload.data.items : [];
      setItems(rawItems as PluginPermissionStatusItem[]);
    } catch (fetchError: any) {
      if (request === generation.current) {
        setItems([]);
        setError(fetchError?.message || 'unknown');
      }
    } finally {
      if (request === generation.current) setLoading(false);
    }
  }, [block.resource_name, connectionId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      if (!cancelled) {
        await load();
      }
    })();
    return () => {
      cancelled = true;
      generation.current += 1;
    };
  }, [load]);

  // Permission item labels/descriptions are pre-translated server-side from
  // plugin i18n (see ``_translate_resource_payload`` in the backend), so we
  // simply trust the values returned from the API.
  const resolveLabel = (item: PluginPermissionStatusItem): string => item.label;
  const resolveDescription = (item: PluginPermissionStatusItem): string => item.description ?? '';

  return (
    <div className="space-y-3 rounded-xl border border-[hsl(var(--settings-subnav-border)/0.7)] bg-[hsl(var(--background))] p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <h4 className="text-sm font-medium text-foreground">{getBlockTitle(block)}</h4>
          {getBlockDescription(block) ? (
            <p className="text-xs leading-6 text-muted-foreground">{getBlockDescription(block)}</p>
          ) : null}
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={() => void load()}
          disabled={loading}
          aria-label={t('settings.permissionStatus.refresh')}
          title={t('settings.permissionStatus.refresh')}
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
        </Button>
      </div>

      {error ? (
        <p className="text-sm text-destructive">
          {t('settings.timeline.errors.resourceLoadFailed', { message: error })}
        </p>
      ) : null}

      {!error && items.length === 0 && !loading ? (
        <p className="text-sm text-muted-foreground">{t('settings.permissionStatus.empty')}</p>
      ) : null}

      {!error && items.length > 0 ? (
        <ul className="space-y-1.5">
          {items.map((item) => {
            const statusLabel = t(getPermissionStatusKey(item.status));
            const description = resolveDescription(item);
            const showOpenSettings = item.status !== 'granted' && !!item.settings_url;
            return (
              <li
                key={item.id}
                className="flex items-center gap-3 rounded-lg border border-transparent px-1 py-1.5"
              >
                <div className="shrink-0">{renderPermissionIcon(item.status)}</div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-sm text-foreground">{resolveLabel(item)}</span>
                    <span className="text-xs text-muted-foreground">({statusLabel})</span>
                    {item.required ? (
                      <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70">
                        {t('settings.permissionStatus.required')}
                      </span>
                    ) : null}
                  </div>
                  {description ? (
                    <p className="text-xs text-muted-foreground">{description}</p>
                  ) : null}
                </div>
                {showOpenSettings ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 shrink-0 gap-1.5 px-2.5 text-xs"
                    onClick={() => void openExternalUrl(item.settings_url!)}
                    aria-label={t('settings.permissionStatus.openSettings')}
                    title={t('settings.permissionStatus.openSettings')}
                  >
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    {t('settings.permissionStatus.openSettings')}
                  </Button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
};

export const PluginSettingsCustomBlocks: React.FC<PluginSettingsCustomBlocksProps> = ({
  connectionId,
  blocks,
  values,
  onChange,
}) => {
  const visibleBlocks = useMemo(() => blocks.filter((block) => isBlockVisible(block, values)), [blocks, values]);

  if (!visibleBlocks.length) {
    return null;
  }

  return (
    <div className="space-y-5">
      {visibleBlocks.map((block) => {
        if (block.type === 'resource_picker' && block.presentation === 'calendar_list') {
          return (
            <CalendarListResourcePicker
              key={block.block_id}
              connectionId={connectionId}
              block={block}
              values={values}
              onChange={onChange}
            />
          );
        }
        if (block.type === 'resource_picker' && block.presentation === 'permission_status') {
          return <PermissionStatusBlock key={block.block_id} connectionId={connectionId} block={block} />;
        }
        return null;
      })}
    </div>
  );
};

export default PluginSettingsCustomBlocks;
