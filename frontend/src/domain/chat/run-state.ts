export const TERMINAL_RUN_STATE_VALUES = [
  'blocked',
  'cancelled',
  'completed',
  'failed',
  'interrupted',
  'merged',
] as const;

export const PENDING_RUN_STATE_VALUES = [
  'queued',
  'running',
  'cancelling',
] as const;

export type TerminalRunState = typeof TERMINAL_RUN_STATE_VALUES[number];
export type PendingRunState = typeof PENDING_RUN_STATE_VALUES[number];

const TERMINAL_RUN_STATES = new Set<string>(TERMINAL_RUN_STATE_VALUES);
const PENDING_RUN_STATES = new Set<string>(PENDING_RUN_STATE_VALUES);

export const normalizeRunState = (state: unknown): string => (
  String(state || '').trim().toLowerCase()
);

export const normalizeTerminalRunState = (state: unknown): TerminalRunState | null => {
  const normalized = normalizeRunState(state);
  return TERMINAL_RUN_STATES.has(normalized)
    ? normalized as TerminalRunState
    : null;
};

export const isTerminalRunState = (state: unknown): boolean => (
  normalizeTerminalRunState(state) !== null
);

export const isPendingRunState = (state: unknown): boolean => (
  PENDING_RUN_STATES.has(normalizeRunState(state))
);
