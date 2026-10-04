type StartupOutcome = 'ready' | 'failed' | 'cancelled';

let nextSpanId = 0;
const milestones = new Set<string>();

/** Log fixed stage names and durations only; never include URLs or user data. */
export function startStartupSpan(stage: string): (outcome?: StartupOutcome) => void {
  const startedAt = performance.now();
  const spanId = ++nextSpanId;
  let finished = false;
  console.info('[startup]', { stage, spanId, outcome: 'started', elapsedMs: Math.round(startedAt) });
  return (outcome = 'ready') => {
    if (finished) return;
    finished = true;
    console.info('[startup]', {
      stage, spanId, outcome,
      durationMs: Math.round(performance.now() - startedAt),
      elapsedMs: Math.round(performance.now()),
    });
  };
}

export async function measureStartupStep<T>(stage: string, operation: () => Promise<T>): Promise<T> {
  const finish = startStartupSpan(stage);
  try {
    const result = await operation();
    finish();
    return result;
  } catch (error) {
    finish('failed');
    throw error;
  }
}

/** Report each first-render milestone once per WebView load. */
export function reportStartupMilestone(stage: string): void {
  if (milestones.has(stage)) return;
  milestones.add(stage);
  console.info('[startup]', { stage, elapsedMs: Math.round(performance.now()) });
}
