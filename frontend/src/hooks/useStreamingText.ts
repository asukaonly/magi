import { useEffect, useRef, useState } from 'react';

// Reveal rates in chars/sec. The drip is ADAPTIVE: rate = max(MIN, min(MAX,
// gap / TARGET_FLUSH_SECONDS)). Small backlogs reveal slowly (typewriter
// feel); large backlogs (LLM responded much faster than the floor) speed up
// so the bubble doesn't lag minutes behind the producer.
const MIN_CHARS_PER_SECOND = 60;     // typewriter floor for small messages
const MAX_CHARS_PER_SECOND = 240;    // ceiling so we don't blow past human-perceivable streaming
const TARGET_FLUSH_SECONDS = 0.9;    // try to consume current backlog in this long

export interface UseStreamingTextOptions {
  /**
   * Floor for the adaptive reveal rate. Defaults to 60 cps which reads as
   * natural typing for messages where the LLM is the bottleneck. Raise to
   * unhurry shorter messages; lower for a more deliberate typewriter feel.
   */
  minCharsPerSecond?: number;
  /**
   * Ceiling for the adaptive reveal rate. Defaults to 240 cps. Higher rates
   * become indistinguishable from instant rendering — you stop seeing the
   * drip effect at all, defeating the smoothing purpose.
   */
  maxCharsPerSecond?: number;
  /**
   * When true, the hook is a pass-through (returns ``target`` directly). Use
   * for `prefers-reduced-motion` users or any caller that wants raw output.
   */
  disabled?: boolean;
}

/**
 * Smooth the display of a streaming string into a continuous reveal.
 *
 * Backend chat chunks arrive in bursts (Rust gateway polls SQLite every 500ms
 * and emits batches), so naive `<ReactMarkdown>{streamingText}</ReactMarkdown>`
 * looks like step-jumps every half second instead of incremental typing.
 *
 * This hook decouples "what the backend has produced so far" (the `target`
 * arg) from "what is currently visible" (the returned string). A
 * `requestAnimationFrame` loop advances the visible string toward the target
 * at a fixed character rate, giving the illusion of continuous streaming
 * regardless of the chunk-arrival cadence.
 *
 * Semantics:
 * - While `isStreaming` is true, the returned string lags the target and
 *   catches up at `charsPerSecond`.
 * - When `isStreaming` flips to false (run completed / cancelled), the
 *   returned string immediately jumps to the full target.
 * - When the target SHRINKS (e.g., a retract or revision swap), the returned
 *   string also snaps so we never display content the producer revoked.
 * - Target length never decreases naturally during a stream, so the
 *   shrink-snap branch is a safety guard, not a hot path.
 */
export function useStreamingText(
  target: string,
  isStreaming: boolean,
  options: UseStreamingTextOptions = {},
): string {
  const {
    minCharsPerSecond = MIN_CHARS_PER_SECOND,
    maxCharsPerSecond = MAX_CHARS_PER_SECOND,
    disabled = false,
  } = options;
  const [rendered, setRendered] = useState<string>(target);
  const rafRef = useRef<number | null>(null);
  const lastTickRef = useRef<number>(0);
  const targetRef = useRef<string>(target);
  const renderedRef = useRef<string>(target);
  targetRef.current = target;

  useEffect(() => {
    // Bypass: snap to target. Used when streaming ends OR caller disables.
    if (disabled || !isStreaming) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      if (renderedRef.current !== target) {
        renderedRef.current = target;
        setRendered(target);
      }
      return;
    }

    // Target shrank under us (retract / revision) — snap, don't try to
    // animate downward.
    if (renderedRef.current.length > target.length) {
      renderedRef.current = target;
      setRendered(target);
    }

    const tick = (now: number) => {
      const last = lastTickRef.current || now;
      const dtSeconds = (now - last) / 1000;
      lastTickRef.current = now;

      const currentRendered = renderedRef.current;
      const currentTarget = targetRef.current;

      if (currentRendered.length >= currentTarget.length) {
        // Caught up — sleep until the next target update kicks us awake via
        // the effect re-run below.
        rafRef.current = null;
        return;
      }

      // Adaptive rate: aim to drain the current backlog within
      // TARGET_FLUSH_SECONDS, but clamp to the [min, max] envelope so we
      // stay smooth on both tiny (rate floor takes over → typewriter feel)
      // and huge backlogs (rate ceiling prevents instant-snap UX).
      const gap = currentTarget.length - currentRendered.length;
      const adaptiveRate = Math.max(
        minCharsPerSecond,
        Math.min(maxCharsPerSecond, gap / TARGET_FLUSH_SECONDS),
      );
      const advance = Math.max(1, Math.floor(adaptiveRate * dtSeconds));
      const nextLen = Math.min(currentTarget.length, currentRendered.length + advance);
      const next = currentTarget.slice(0, nextLen);
      renderedRef.current = next;
      setRendered(next);

      rafRef.current = requestAnimationFrame(tick);
    };

    // (Re)start the loop. Reset the clock so the first frame doesn't think
    // a huge dt has elapsed since the previous run.
    lastTickRef.current = 0;
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
    }
    rafRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [target, isStreaming, disabled, minCharsPerSecond, maxCharsPerSecond]);

  return rendered;
}
