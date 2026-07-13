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
}

const ContextUsageRingInner: React.FC<{ snapshot: ContextUsageSnapshot }> = ({ snapshot }) => {
  const { t } = useTranslation('app');
  const { usedTokens, windowSize } = snapshot;
  if (windowSize <= 0) {
    const usageText = '0 / —';
    return (
      <TooltipProvider delayDuration={250}>
        <Tooltip>
          <TooltipTrigger asChild>
            <div
              className="relative flex h-8 w-8 items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40 focus-visible:ring-offset-2"
              role="status"
              aria-label={t('chat.contextUsage.unavailableLabel', {
                defaultValue: '上下文用量：{{usage}}',
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
                0
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

  const ratio = Math.min(usedTokens / windowSize, 1);
  const offset = CIRCUMFERENCE * (1 - ratio);
  const color = ringColor(ratio);
  const pct = Math.round(ratio * 100);
  const usageText = `${formatTokens(usedTokens)} / ${formatTokens(windowSize)}`;
  const ariaLabel = t('chat.contextUsage.label', {
    defaultValue: '上下文用量：{{usage}}（{{percent}}%）',
    usage: usageText,
    percent: pct,
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
            aria-valuemax={windowSize}
            aria-valuetext={usageText}
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
              {pct}
            </span>
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" sideOffset={8} className="tabular-nums">
          {usageText}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
};

export const ContextUsageRing: React.FC<ContextUsageRingProps> = ({ sessionId }) => {
  const snapshot = useContextUsageStore((state) =>
    sessionId ? state.usage[sessionId] : undefined,
  );
  return <ContextUsageRingInner snapshot={snapshot ?? {
    usedTokens: 0,
    windowSize: 0,
    threshold: 0,
    updatedAt: 0,
  }} />;
};
