/**
 * Draft-based global control settings editor used by the settings page.
 */
import { useTranslation } from 'react-i18next';
import { SelectField } from '@/components/config-forms/fields';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { ControlSettingsDTO, PermissionMode } from '@/api/modules/control';

export const CONTROL_PERMISSION_MODES: PermissionMode[] = ['all', 'high_only', 'off'];

export function getPermissionModeLabel(
  t: (key: string) => string,
  mode: PermissionMode,
): string {
  return t(`settings.mode.${mode}`);
}

export interface ControlSettingsPanelProps {
  value: ControlSettingsDTO;
  onChange: (next: ControlSettingsDTO) => void;
  disabled?: boolean;
  className?: string;
}

export function ControlSettingsPanel({
  value,
  onChange,
  disabled = false,
  className,
}: ControlSettingsPanelProps) {
  const { t } = useTranslation('control');

  return (
    <div
      className={cn('space-y-0', className)}
      data-testid="control-settings-panel"
    >
      <div className="grid gap-3 py-3 sm:grid-cols-[minmax(0,1fr)_260px] sm:items-center">
        <div className="space-y-1">
          <div className="text-sm font-medium text-foreground">
            {t('settings.permission_mode')}
          </div>
          <div className="text-xs leading-6 text-muted-foreground">
            {t('settings.permission_mode_description')}
          </div>
        </div>
        <SelectField
          value={value.permission_mode}
          onChange={(nextMode) =>
            onChange({
              ...value,
              permission_mode: nextMode as PermissionMode,
            })
          }
          options={CONTROL_PERMISSION_MODES.map((mode) => ({
            label: getPermissionModeLabel(t, mode),
            value: mode,
          }))}
          allowEmpty={false}
          disabled={disabled}
          ariaLabel={t('settings.permission_mode')}
          triggerClassName="h-11 rounded-xl border-border/60 bg-background/80 px-3.5 text-sm shadow-none"
          menuClassName="rounded-xl border-border/70"
        />
      </div>

      <label className="grid gap-3 py-3 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center">
        <div className="space-y-1">
          <div className="text-sm font-medium text-foreground">
            {t('settings.plan_approval_required')}
          </div>
          <div className="text-xs leading-6 text-muted-foreground">
            {t('settings.plan_approval_description')}
          </div>
        </div>
        <div className="flex justify-start sm:justify-end">
          <Switch
            checked={value.plan_approval_required}
            onCheckedChange={(checked) =>
              onChange({
                ...value,
                plan_approval_required: checked,
              })
            }
            disabled={disabled}
            data-testid="plan-approval-switch"
          />
        </div>
      </label>
    </div>
  );
}
