import type { MemoryL0Config } from '@/api/modules/config';

export type MemoryL0ValidationIssue =
  | 'attentionUpdatePositiveInteger'
  | 'attentionUpdateOutOfRange'
  | 'attentionUpdateMaxDelayTooShort';

const isPositiveInteger = (value: number): boolean =>
  Number.isInteger(value) && value >= 1;

export function validateMemoryL0Config(
  config: MemoryL0Config,
): MemoryL0ValidationIssue | null {
  if (
    !isPositiveInteger(config.attention_update_turn_threshold)
    || !isPositiveInteger(config.attention_update_idle_seconds)
    || !isPositiveInteger(config.attention_update_max_delay_seconds)
  ) {
    return 'attentionUpdatePositiveInteger';
  }

  if (
    config.attention_update_turn_threshold > 20
    || config.attention_update_idle_seconds > 300
    || config.attention_update_max_delay_seconds > 600
  ) {
    return 'attentionUpdateOutOfRange';
  }

  if (
    config.attention_update_max_delay_seconds
    < config.attention_update_idle_seconds
  ) {
    return 'attentionUpdateMaxDelayTooShort';
  }

  return null;
}
