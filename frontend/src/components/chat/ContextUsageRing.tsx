import React from 'react';
import { useContextUsageStore, type ContextUsageSnapshot } from '@/stores/context-usage';

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
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

/* -------------------------------------------------------------------------- */
/*  Component                                                                 */
/* -------------------------------------------------------------------------- */

interface ContextUsageRingProps {
  sessionId: string | null;
}

const ContextUsageRingInner: React.FC<{ snapshot: ContextUsageSnapshot }> = ({ snapshot }) => {
  const { usedTokens, windowSize } = snapshot;
  if (windowSize <= 0) {
    return (
      <div
        className="relative flex h-8 w-8 items-center justify-center"
        title="0"
        role="status"
        aria-label="0"
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
    );
  }

  const ratio = Math.min(usedTokens / windowSize, 1);
  const offset = CIRCUMFERENCE * (1 - ratio);
  const color = ringColor(ratio);
  const pct = Math.round(ratio * 100);
  const title = `${formatTokens(usedTokens)} / ${formatTokens(windowSize)}  (${pct}%)`;

  return (
    <div
      className="relative flex h-8 w-8 items-center justify-center"
      title={title}
      role="meter"
      aria-valuenow={usedTokens}
      aria-valuemin={0}
      aria-valuemax={windowSize}
      aria-label={title}
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
