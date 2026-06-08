import type { InstallStep, InstallStepId, StepStatus } from '@/hooks/usePluginInstallFlow';

/**
 * Status glyphs mirror PersonaPreviewChat's generation-stage indicator
 * (✓ done / … running / · pending), with × added for the hard-error case
 * that only ①install/②enable can reach.
 */
const glyph = (status: StepStatus): string => {
  if (status === 'done') return '✓';
  if (status === 'running') return '…';
  if (status === 'error') return '×';
  return '·';
};

export interface InstallStepperProps {
  steps: InstallStep[];
  labels: Record<InstallStepId, string>;
}

/**
 * Presentational stepper for the plugin install flow. Renders one row per
 * step with a status glyph + localized label. Pure — all state lives in
 * usePluginInstallFlow; the panel owns the labels (incl. the dynamic
 * synced-count / "整理中" memory label).
 */
export function InstallStepper({ steps, labels }: InstallStepperProps) {
  return (
    <ul className="mt-2 space-y-1 rounded-md border border-border/55 bg-card p-3">
      {steps.map((step) => (
        <li
          key={step.id}
          data-testid={`step-${step.id}`}
          className={`flex items-center gap-2 text-xs ${
            step.status === 'error' ? 'text-destructive' : 'text-muted-foreground'
          }`}
        >
          <span aria-hidden className="w-3 text-center">
            {glyph(step.status)}
          </span>
          <span>{labels[step.id]}</span>
        </li>
      ))}
    </ul>
  );
}
