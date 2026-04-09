import React from 'react';
import { useTranslation } from 'react-i18next';
import { Camera, Calendar, Globe, GitBranch, Monitor, Terminal, Music } from 'lucide-react';
import { SimpleForm as Form } from '../onboarding/simple-form';
import { cn } from '@/lib/utils';

interface SensorDef {
  id: string;
  configKey: string;
  icon: React.ElementType;
  labelKey: string;
  descKey: string;
}

const sensorDefs: SensorDef[] = [
  { id: 'photo_library', configKey: 'photo_library', icon: Camera, labelKey: 'sensors.photoLibrary.label', descKey: 'sensors.photoLibrary.desc' },
  { id: 'calendar', configKey: 'calendar', icon: Calendar, labelKey: 'sensors.calendar.label', descKey: 'sensors.calendar.desc' },
  { id: 'chrome_history', configKey: 'chrome_history', icon: Globe, labelKey: 'sensors.chromeHistory.label', descKey: 'sensors.chromeHistory.desc' },
  { id: 'git_activity', configKey: 'git_activity', icon: GitBranch, labelKey: 'sensors.gitActivity.label', descKey: 'sensors.gitActivity.desc' },
  { id: 'screen_time', configKey: 'screen_time', icon: Monitor, labelKey: 'sensors.screenTime.label', descKey: 'sensors.screenTime.desc' },
  { id: 'terminal_history', configKey: 'terminal_history', icon: Terminal, labelKey: 'sensors.terminalHistory.label', descKey: 'sensors.terminalHistory.desc' },
  { id: 'netease_music', configKey: 'netease_music', icon: Music, labelKey: 'sensors.neteaseMusic.label', descKey: 'sensors.neteaseMusic.desc' },
];

const syncModeOptions = [
  { value: 'manual', labelKey: 'sensors.syncModes.manual' },
  { value: 'interval', labelKey: 'sensors.syncModes.interval' },
] as const;

export const SensorConfigForm: React.FC = () => {
  const { t } = useTranslation('onboarding');

  return (
    <div className="space-y-6">
      <div>
        <h3 className="mb-1 text-base font-medium">{t('sensors.title')}</h3>
        <p className="mb-4 text-sm text-muted-foreground">{t('sensors.description')}</p>
      </div>

      <div className="space-y-3">
        {sensorDefs.map((sensor) => (
          <SensorCard key={sensor.id} sensor={sensor} t={t} />
        ))}
      </div>
    </div>
  );
};

interface SensorCardProps {
  sensor: SensorDef;
  t: (key: string) => string;
}

const SensorCard: React.FC<SensorCardProps> = ({ sensor, t }) => {
  const Icon = sensor.icon;
  const enabledPath = ['timeline', 'sources', sensor.configKey, 'enabled'];
  const syncModePath = ['timeline', 'sources', sensor.configKey, 'sync_mode'];

  return (
    <Form.Item shouldUpdate noStyle>
      {({
        getFieldValue,
        setFieldValue,
      }: {
        getFieldValue: (name: any) => any;
        setFieldValue: (name: any, value: any) => void;
      }) => {
        const enabled = getFieldValue(enabledPath) ?? false;
        const syncMode = getFieldValue(syncModePath) ?? 'interval';

        const handleToggle = () => {
          const next = !enabled;
          setFieldValue(enabledPath, next);
          // Ensure sync_mode has a default when enabling
          if (next && !getFieldValue(syncModePath)) {
            setFieldValue(syncModePath, 'interval');
          }
        };

        return (
          <div
            className={cn(
              'flex items-center gap-4 rounded-xl border p-4 transition',
              enabled ? 'border-primary/30 bg-primary/5' : 'border-border bg-background'
            )}
          >
            {/* Icon */}
            <div
              className={cn(
                'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg',
                enabled ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'
              )}
            >
              <Icon className="h-5 w-5" />
            </div>

            {/* Label + Description */}
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">{t(sensor.labelKey)}</div>
              <div className="text-xs text-muted-foreground">{t(sensor.descKey)}</div>
            </div>

            {/* Sync mode selector (visible when enabled) */}
            {enabled && (
              <select
                value={syncMode}
                onChange={(e) => setFieldValue(syncModePath, e.target.value)}
                className="h-8 rounded-md border border-border bg-background px-2 text-xs focus:outline-none focus:ring-1 focus:ring-primary/50"
              >
                {syncModeOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {t(opt.labelKey)}
                  </option>
                ))}
              </select>
            )}

            {/* Toggle */}
            <button
              type="button"
              role="switch"
              aria-checked={enabled}
              onClick={handleToggle}
              className={cn(
                'relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50',
                enabled ? 'bg-primary' : 'bg-muted'
              )}
            >
              <span
                className={cn(
                  'pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-sm transition-transform',
                  enabled ? 'translate-x-5' : 'translate-x-0.5'
                )}
              />
            </button>
          </div>
        );
      }}
    </Form.Item>
  );
};

export default SensorConfigForm;
