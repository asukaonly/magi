import React, { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';

import {
  pluginsApi,
  type PluginSettingsResourceGroup,
  type PluginSettingsUiBlockSpec,
} from '@/api/modules/plugins';

interface PluginSettingsCustomBlocksProps {
  pluginId: string;
  blocks: PluginSettingsUiBlockSpec[];
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
}

const getPluginTranslation = (
  t: (key: string, params?: Record<string, any>) => string,
  pluginId: string,
  key: string,
  fallback: string
): string => {
  const translationKey = `settings.plugins.${pluginId}.${key}`;
  const translated = t(translationKey);
  return translated === translationKey ? fallback : translated;
};

const getBlockTitle = (
  t: (key: string, params?: Record<string, any>) => string,
  pluginId: string,
  block: PluginSettingsUiBlockSpec
) => getPluginTranslation(t, pluginId, `ui_blocks.${block.block_id}.title`, block.title);

const getBlockDescription = (
  t: (key: string, params?: Record<string, any>) => string,
  pluginId: string,
  block: PluginSettingsUiBlockSpec
) => getPluginTranslation(t, pluginId, `ui_blocks.${block.block_id}.description`, block.description);

const isBlockVisible = (block: PluginSettingsUiBlockSpec, values: Record<string, any>) => {
  if (!block.depends_on_key || !block.depends_on_values?.length) {
    return true;
  }
  return block.depends_on_values.includes(String(values[block.depends_on_key] ?? ''));
};

const CalendarListResourcePicker: React.FC<{
  pluginId: string;
  block: PluginSettingsUiBlockSpec;
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
}> = ({ pluginId, block, values, onChange }) => {
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
        const payload = await pluginsApi.getSettingsResource(pluginId, block.resource_name);
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
  }, [block.resource_name, pluginId]);

  const toggleItem = (itemId: string, checked: boolean) => {
    const nextIds = checked
      ? [...selectedIds, itemId]
      : selectedIds.filter((existingId) => existingId !== itemId);
    onChange(block.value_key, nextIds);
  };

  return (
    <div className="space-y-4 rounded-xl border border-[hsl(var(--settings-subnav-border)/0.7)] bg-[hsl(var(--background))] p-4">
      <div className="space-y-1">
        <h4 className="text-sm font-medium text-foreground">{getBlockTitle(t, pluginId, block)}</h4>
        <p className="text-xs leading-6 text-muted-foreground">{getBlockDescription(t, pluginId, block)}</p>
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
        <div className="space-y-4">
          {groups.map((group) => (
            <div key={group.group_id} className="space-y-3">
              <div className="text-xs font-medium uppercase tracking-[0.14em] text-muted-foreground">
                {group.label}
              </div>
              <div className="space-y-2">
                {group.items.map((item) => (
                  <label
                    key={item.item_id}
                    className="flex items-center gap-3 rounded-lg border border-transparent px-3 py-2 transition-colors hover:bg-muted/40"
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-input"
                      aria-label={item.label}
                      checked={selectedIds.includes(item.item_id)}
                      onChange={(event) => toggleItem(item.item_id, event.target.checked)}
                    />
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ backgroundColor: item.accent_color || 'hsl(var(--muted-foreground))' }}
                      aria-hidden="true"
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

export const PluginSettingsCustomBlocks: React.FC<PluginSettingsCustomBlocksProps> = ({
  pluginId,
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
              pluginId={pluginId}
              block={block}
              values={values}
              onChange={onChange}
            />
          );
        }
        return null;
      })}
    </div>
  );
};

export default PluginSettingsCustomBlocks;
