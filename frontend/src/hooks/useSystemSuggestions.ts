import { useCallback, useEffect, useRef, useState } from 'react';
import {
  checkSystemSuggestions,
  dismissSystemSuggestion,
  type DismissalKind,
  type SuggestionProposal,
} from '../api/modules/systemSuggestions';
import { APP_EVENTS } from '../constants/events';

export interface UseSystemSuggestionsArgs {
  triggerText: string;
  locale: 'zh' | 'en';
  sessionId?: string;
}

export interface UseSystemSuggestionsResult {
  proposals: SuggestionProposal[];
  loading: boolean;
  error: Error | null;
  dismiss: (
    dedupeKey: string,
    kind: DismissalKind,
    title?: string,
  ) => Promise<void>;
}

export function useSystemSuggestions({
  triggerText,
  locale,
  sessionId,
}: UseSystemSuggestionsArgs): UseSystemSuggestionsResult {
  const [proposals, setProposals] = useState<SuggestionProposal[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const cancelled = useRef(false);

  const fetchSuggestions = useCallback(() => {
    if (!triggerText) {
      setProposals([]);
      return;
    }
    cancelled.current = false;
    setLoading(true);
    setError(null);
    checkSystemSuggestions({ text: triggerText, locale, sessionId })
      .then((result) => {
        if (!cancelled.current) setProposals(result);
      })
      .catch((err) => {
        if (!cancelled.current) setError(err as Error);
      })
      .finally(() => {
        if (!cancelled.current) setLoading(false);
      });
  }, [triggerText, locale, sessionId]);

  useEffect(() => {
    fetchSuggestions();
    return () => {
      cancelled.current = true;
    };
  }, [fetchSuggestions]);

  // Re-evaluate when the installed/connected plugin set changes (a plugin
  // install/connect just completed), so a now-connected plugin stops being
  // suggested across every surface (top bar, side card, product tour).
  useEffect(() => {
    const handler = () => fetchSuggestions();
    window.addEventListener(APP_EVENTS.PLUGINS_CHANGED, handler);
    return () => window.removeEventListener(APP_EVENTS.PLUGINS_CHANGED, handler);
  }, [fetchSuggestions]);

  const dismiss = useCallback(
    async (dedupeKey: string, kind: DismissalKind, title?: string) => {
      setProposals((prev) => prev.filter((p) => p.dedupe_key !== dedupeKey));
      try {
        // Only include `title` when provided so callers without the localized
        // text don't send an explicit `title: undefined` in the request body.
        await dismissSystemSuggestion(
          title === undefined
            ? { dedupe_key: dedupeKey, kind }
            : { dedupe_key: dedupeKey, kind, title },
        );
      } catch (err) {
        console.warn('failed to persist dismissal', err);
      }
    },
    [],
  );

  return { proposals, loading, error, dismiss };
}
