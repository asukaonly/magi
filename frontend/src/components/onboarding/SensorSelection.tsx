import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2, Download, Check, AlertCircle, Info } from 'lucide-react';
import { motion, useReducedMotion } from 'framer-motion';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';
import { pluginsApi } from '@/api/modules/plugins';
import type { ScenarioId } from './ScenarioSelection';

/** Sensor plugins recommended per scenario. */
const SCENARIO_RECOMMENDED_SENSORS: Record<string, string[]> = {
  life_monitor: ['photo-library', 'calendar', 'screen-time'],
  knowledge_partner: ['chrome-history', 'git-activity'],
};

/** Resolve the localized text from an i18n map, falling back to the default. */
function localized(
  base: string,
  i18nMap: Record<string, string> | undefined,
  lang: string,
): string {
  if (!i18nMap) return base;
  return i18nMap[lang] ?? i18nMap[lang.split('-')[0]] ?? base;
}

/** Detect current platform for filtering plugins. */
function getCurrentPlatform(): string {
  return /mac/i.test(navigator.userAgent) ? 'macos' : 'windows';
}

interface SensorSelectionProps {
  scenario?: ScenarioId;
  onInstallStatusChange?: (status: SensorInstallStatus) => void;
}

type InstallState = 'idle' | 'installing' | 'installed' | 'error';

export interface SensorInstallStatus {
  canContinue: boolean;
  isInstalling: boolean;
}

interface SensorItem {
  pluginId: string;
  name: string;
  description: string;
  alreadyInstalled: boolean;
}

const SensorSelection: React.FC<SensorSelectionProps> = ({ scenario, onInstallStatusChange }) => {
  const { t, i18n } = useTranslation('onboarding');
  const shouldReduceMotion = useReducedMotion();
  const [loading, setLoading] = useState(true);
  const [registryAvailable, setRegistryAvailable] = useState(false);
  const [registryError, setRegistryError] = useState<string | null>(null);
  const [sensors, setSensors] = useState<SensorItem[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [installStates, setInstallStates] = useState<Record<string, InstallState>>({});

  const platform = useMemo(() => getCurrentPlatform(), []);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const registry = await pluginsApi.getRegistry();
        const lang = i18n.language;

        // Filter: only sensors, only current platform.
        const sensorEntries = registry.plugins.filter((entry) => {
          if (!entry.contribution_types.includes('sensor')) return false;
          if (entry.platforms.length > 0 && !entry.platforms.includes(platform)) return false;
          return true;
        });

        const items: SensorItem[] = sensorEntries.map((entry) => ({
          pluginId: entry.plugin_id,
          name: localized(entry.name, entry.name_i18n, lang),
          description: localized(entry.description, entry.description_i18n, lang),
          alreadyInstalled: entry.installed,
        }));

        if (!cancelled) {
          setSensors(items);
          setRegistryAvailable(true);
          setRegistryError(null);

          // Pre-select recommended sensors that exist in filtered list.
          const recommended = (scenario && SCENARIO_RECOMMENDED_SENSORS[scenario]) ?? [];
          const availableIds = new Set(items.map((s: SensorItem) => s.pluginId));
          setSelected(new Set(recommended.filter((id) => availableIds.has(id))));

          const preInstalled: Record<string, InstallState> = {};
          for (const item of items) {
            if (item.alreadyInstalled) preInstalled[item.pluginId] = 'installed';
          }
          setInstallStates(preInstalled);
        }
      } catch (error: any) {
        if (!cancelled) {
          setSensors([]);
          setRegistryAvailable(false);
          setRegistryError(error?.message || t('sensorSelection.registryUnavailable'));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [i18n.language, platform, scenario]);

  // Reset selection when scenario changes.
  useEffect(() => {
    const recommended = (scenario && SCENARIO_RECOMMENDED_SENSORS[scenario]) ?? [];
    const availableIds = new Set(sensors.map((s: SensorItem) => s.pluginId));
    setSelected(new Set(recommended.filter((id) => availableIds.has(id))));
  }, [scenario, sensors]);

  const toggleSensor = useCallback((pluginId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(pluginId)) {
        next.delete(pluginId);
      } else {
        next.add(pluginId);
      }
      return next;
    });
  }, []);

  const handleInstallSelected = useCallback(async () => {
    const toInstall = [...selected].filter((id) => {
      const sensor = sensors.find((s) => s.pluginId === id);
      return sensor && !sensor.alreadyInstalled && installStates[id] !== 'installed';
    });

    if (toInstall.length === 0) return;

    let successCount = 0;
    let failCount = 0;

    for (const pluginId of toInstall) {
      setInstallStates((prev) => ({ ...prev, [pluginId]: 'installing' }));
      try {
        await pluginsApi.installFromRegistry(pluginId);
        setInstallStates((prev) => ({ ...prev, [pluginId]: 'installed' }));
        successCount++;
      } catch (error) {
        console.error('[sensorSelection] failed to install sensor plugin', { pluginId, error });
        setInstallStates((prev) => ({ ...prev, [pluginId]: 'error' }));
        failCount++;
      }
    }

    if (failCount === 0) {
      toast.success(t('sensorSelection.installSuccess', { count: successCount }));
    } else if (successCount === 0) {
      toast.error(t('sensorSelection.installAllFailed', { count: failCount }));
    } else {
      toast.warning(t('sensorSelection.installPartial', { success: successCount, fail: failCount }));
    }
  }, [selected, sensors, installStates, t]);

  const recommended = (scenario && SCENARIO_RECOMMENDED_SENSORS[scenario]) ?? [];
  const hasSelection = selected.size > 0;
  const allSelectedInstalled = [...selected].every(
    (id) => installStates[id] === 'installed' || sensors.find((s) => s.pluginId === id)?.alreadyInstalled
  );
  const isInstalling = Object.values(installStates).some((s) => s === 'installing');
  const canContinue = !loading && (!registryAvailable || selected.size === 0 || allSelectedInstalled);

  useEffect(() => {
    onInstallStatusChange?.({ canContinue, isInstalling });
  }, [canContinue, isInstalling, onInstallStatusChange]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Registry unavailable — show a brief message and let user proceed.
  if (!registryAvailable) {
    return (
      <div className="space-y-5">
        <div>
          <h3 className="mb-1 text-base font-medium">{t('sensorSelection.title')}</h3>
          <p className="mb-3 text-sm text-muted-foreground">{t('sensorSelection.description')}</p>
        </div>
        <div className="rounded-lg border border-border bg-muted/30 p-4">
          <div className="flex items-start gap-2">
            <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">{t('sensorSelection.registryUnavailable')}</p>
              {registryError ? (
                <p className="text-xs text-muted-foreground/90">{registryError}</p>
              ) : null}
            </div>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">{t('sensorSelection.installLaterHint')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div>
        <h3 className="mb-1 text-base font-medium">{t('sensorSelection.title')}</h3>
        <p className="mb-3 text-sm text-muted-foreground">{t('sensorSelection.description')}</p>
      </div>

      <div className="grid auto-rows-fr gap-2 sm:grid-cols-2">
        {sensors.map((sensor) => {
          const isRecommended = recommended.includes(sensor.pluginId);
          const isSelected = selected.has(sensor.pluginId);
          const state = installStates[sensor.pluginId] ?? 'idle';

          return (
            <motion.div
              key={sensor.pluginId}
              className="h-full"
              whileHover={shouldReduceMotion ? undefined : { y: -1 }}
              transition={{ duration: shouldReduceMotion ? 0 : 0.12 }}
            >
              <button
                type="button"
                onClick={() => toggleSensor(sensor.pluginId)}
                disabled={state === 'installing'}
                aria-pressed={isSelected}
                className={cn(
                  'flex h-full w-full items-start gap-3 rounded-lg border bg-background px-4 py-3 text-left transition',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
                  isSelected
                    ? 'border-primary bg-primary/5'
                    : 'border-border hover:border-primary/40'
                )}
              >
                <div className={cn(
                  'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition',
                  isSelected ? 'border-primary bg-primary text-primary-foreground' : 'border-muted-foreground/30'
                )}>
                  {isSelected && <Check className="h-3 w-3" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{sensor.name}</span>
                    {isRecommended && (
                      <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
                        {t('sensorSelection.recommended')}
                      </span>
                    )}
                    {state === 'installed' && (
                      <Check className="h-3.5 w-3.5 text-emerald-500" />
                    )}
                    {state === 'installing' && (
                      <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                    )}
                    {state === 'error' && (
                      <AlertCircle className="h-3.5 w-3.5 text-destructive" />
                    )}
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">{sensor.description}</p>
                </div>
              </button>
            </motion.div>
          );
        })}
      </div>

      {hasSelection && !allSelectedInstalled && (
        <div className="space-y-2">
          <button
            type="button"
            onClick={handleInstallSelected}
            disabled={isInstalling}
            className={cn(
              'inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition',
              'hover:bg-primary/90 disabled:opacity-60'
            )}
          >
            {isInstalling ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Download className="h-4 w-4" />
            )}
            {t('sensorSelection.installSelected')}
          </button>
          <p className="text-xs text-muted-foreground">{t('sensorSelection.installBeforeNextHint')}</p>
        </div>
      )}

      <p className="text-xs text-muted-foreground">{t('sensorSelection.skipHint')}</p>
    </div>
  );
};

export default SensorSelection;
