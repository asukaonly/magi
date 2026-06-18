import React from 'react';

import type { PluginSettingsLayoutSpec, PluginSettingsLayoutTabSpec } from '@/api/modules/plugins';
import { cn } from '@/lib/utils';

interface PluginSettingsTabsProps {
  layout: PluginSettingsLayoutSpec;
  values: Record<string, any>;
  onChange: (key: string, value: any) => void;
}

const tabLabel = (tab: PluginSettingsLayoutTabSpec): string =>
  tab.label_translated || tab.label || tab.value;

const tabDescription = (tab: PluginSettingsLayoutTabSpec): string | null =>
  tab.description_translated || tab.description || null;

const tabUnavailableReason = (tab: PluginSettingsLayoutTabSpec): string | null =>
  tab.unavailable_reason_translated || tab.unavailable_reason || null;

export const isTabsSettingsLayout = (layout: unknown): layout is PluginSettingsLayoutSpec => {
  if (!layout || typeof layout !== 'object') {
    return false;
  }
  const candidate = layout as Partial<PluginSettingsLayoutSpec>;
  return candidate.kind === 'tabs' && typeof candidate.controller_key === 'string' && Array.isArray(candidate.tabs);
};

export const getActiveSettingsTab = (
  layout: PluginSettingsLayoutSpec | null,
  values: Record<string, any>
): PluginSettingsLayoutTabSpec | null => {
  if (!layout?.tabs.length) {
    return null;
  }
  const selectedValue = String(values[layout.controller_key] ?? '');
  return layout.tabs.find((tab) => String(tab.value) === selectedValue) ?? layout.tabs[0] ?? null;
};

export const PluginSettingsTabs: React.FC<PluginSettingsTabsProps> = ({
  layout,
  values,
  onChange,
}) => {
  const activeTab = getActiveSettingsTab(layout, values);
  const unavailableReason = activeTab && activeTab.available === false
    ? tabUnavailableReason(activeTab)
    : null;
  const activeDescription = activeTab ? tabDescription(activeTab) : null;

  return (
    <div className="space-y-3">
      <div
        role="tablist"
        aria-label="Plugin source"
        className="inline-flex flex-wrap gap-1 rounded-xl border border-[hsl(var(--settings-subnav-border)/0.75)] bg-[hsl(var(--muted)/0.35)] p-1"
      >
        {layout.tabs.map((tab) => {
          const selected = activeTab?.value === tab.value;
          const unavailable = tab.available === false;
          return (
            <button
              key={tab.tab_id || tab.value}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-disabled={unavailable}
              onClick={() => {
                if (!unavailable) {
                  onChange(layout.controller_key, tab.value);
                }
              }}
              className={cn(
                'rounded-lg px-3.5 py-2 text-sm transition-colors',
                selected
                  ? 'bg-background text-foreground shadow-[0_1px_3px_rgba(15,23,42,0.08)]'
                  : 'text-muted-foreground hover:bg-background/60 hover:text-foreground',
                unavailable && 'cursor-not-allowed text-muted-foreground/55 hover:bg-transparent hover:text-muted-foreground/55'
              )}
            >
              {tabLabel(tab)}
            </button>
          );
        })}
      </div>

      {unavailableReason ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {unavailableReason}
        </div>
      ) : activeDescription ? (
        <p className="max-w-3xl text-xs leading-6 text-muted-foreground">{activeDescription}</p>
      ) : null}
    </div>
  );
};

export default PluginSettingsTabs;
