import React from 'react';
import { useTranslation } from 'react-i18next';
import { useContextUsageStore, type ContextUsageSnapshot } from '@/stores/context-usage';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

/* -------------------------------------------------------------------------- */
/*  SVG ring constants                                                        */
/* -------------------------------------------------------------------------- */

const SIZE = 28;
const STROKE = 3;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/* -------------------------------------------------------------------------- */
/*  Colour thresholds                                                         */
/* -------------------------------------------------------------------------- */

function ringColor(ratio: number): string {
  if (ratio >= 0.9) return 'var(--color-destructive, #ef4444)';
  if (ratio >= 0.7) return 'var(--color-warning, #f59e0b)';
  return 'var(--color-primary, #6366f1)';
}

/* -------------------------------------------------------------------------- */
/*  Format helpers                                                            */
/* -------------------------------------------------------------------------- */

function formatTokens(n: number): string {
  if (n >= 1_000_000) {
    const value = n / 1_000_000;
    return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}M`;
  }
  if (n >= 1_000) {
    const value = n / 1_000;
    return `${Number.isInteger(value) ? value.toFixed(0) : value.toFixed(1)}k`;
  }
  return String(n);
}

/* -------------------------------------------------------------------------- */
/*  Component                                                                 */
/* -------------------------------------------------------------------------- */

interface ContextUsageRingProps {
  sessionId: string | null;
  configuredWindowSize?: number | null;
}

const ContextUsageRingInner: React.FC<{
  snapshot?: ContextUsageSnapshot;
  configuredWindowSize?: number | null;
}> = ({ snapshot, configuredWindowSize }) => {
  const { t } = useTranslation('app');
  if (!snapshot) {
    const hasConfiguredWindow = typeof configuredWindowSize === 'number'
      && Number.isFinite(configuredWindowSize)
      && configuredWindowSize > 0;
    const usageText = `— / ${hasConfiguredWindow ? formatTokens(configuredWindowSize) : '—'}`;
    return (
      <TooltipProvider delayDuration={250}>
        <Tooltip>
          <TooltipTrigger asChild>
            <div
              className="relative flex h-8 w-8 items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-2"
              role="status"
              aria-label={t('chat.contextUsage.unavailableLabel', {
                defaultValue: '最近一次回答上下文：{{usage}}',
                usage: usageText,
              })}
              tabIndex={0}
            >
              <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`}>
                <circle
                  cx={SIZE / 2}
                  cy={SIZE / 2}
                  r={RADIUS}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={STROKE}
                  className="text-muted-foreground/15"
                />
              </svg>
              <span className="absolute text-[9px] font-semibold leading-none text-muted-foreground/80">
                —
              </span>
            </div>
          </TooltipTrigger>
          <TooltipContent side="top" sideOffset={8} className="tabular-nums">
            {usageText}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  const { usedTokens, windowSize } = snapshot;
  const pressureLimit = snapshot.threshold > 0
    ? snapshot.threshold
    : snapshot.inputCapacity > 0
      ? snapshot.inputCapacity
      : windowSize;
  const ratio = Math.min(usedTokens / pressureLimit, 1);
  const offset = CIRCUMFERENCE * (1 - ratio);
  const color = ringColor(ratio);
  const pct = Math.round(ratio * 100);
  const percentText = ratio > 0 && ratio < 0.01 ? '<1' : String(pct);
  const usageText = `${formatTokens(usedTokens)} / ${formatTokens(windowSize)}`;
  const thresholdText = formatTokens(pressureLimit);
  const ariaLabel = t('chat.contextUsage.label', {
    defaultValue: '最近一次回答上下文：{{usage}}；压缩线占用 {{percent}}%',
    usage: usageText,
    percent: percentText,
  });
  const tooltipText = snapshot.measurement === 'estimated'
    ? t('chat.contextUsage.estimatedTooltip', {
      defaultValue: '最近一次回答：{{usage}}（估算） · 压缩线 {{threshold}}',
      usage: usageText,
      threshold: thresholdText,
    })
    : t('chat.contextUsage.tooltip', {
      defaultValue: '最近一次回答：{{usage}} · 压缩线 {{threshold}}',
      usage: usageText,
      threshold: thresholdText,
    });

  return (
    <TooltipProvider delayDuration={250}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className="relative flex h-8 w-8 items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-2"
            role="meter"
            aria-valuenow={usedTokens}
            aria-valuemin={0}
            aria-valuemax={pressureLimit}
            aria-valuetext={`${usageText}; ${thresholdText}`}
            aria-label={ariaLabel}
            tabIndex={0}
          >
            <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} className="rotate-[-90deg]">
              {/* background track */}
              <circle
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={RADIUS}
                fill="none"
                stroke="currentColor"
                strokeWidth={STROKE}
                className="text-muted-foreground/15"
              />
              {/* progress arc */}
              <circle
                cx={SIZE / 2}
                cy={SIZE / 2}
                r={RADIUS}
                fill="none"
                stroke={color}
                strokeWidth={STROKE}
                strokeDasharray={CIRCUMFERENCE}
                strokeDashoffset={offset}
                strokeLinecap="round"
                className="transition-[stroke-dashoffset,stroke] duration-500 ease-out"
              />
            </svg>
            <span
              className="absolute text-[9px] font-semibold leading-none"
              style={{ color }}
            >
              {percentText}
            </span>
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" sideOffset={8} className="tabular-nums">
          {tooltipText}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

export const ContextUsageRing: React.FC<ContextUsageRingProps> = ({
  sessionId,
  configuredWindowSize,
}) => {
  const runtimeSnapshot = useContextUsageStore((state) =>
    sessionId ? state.usage[sessionId] : undefined,
  );
  return (
    <ContextUsageRingInner
      snapshot={runtimeSnapshot}
      configuredWindowSize={configuredWindowSize}
    />
  );
};
