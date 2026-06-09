import { useCallback, useEffect, useRef, useState } from 'react';
import {
  checkSystemSuggestions,
  dismissSystemSuggestion,
  type DismissalKind,
  type SuggestionProposal,
} from '../api/modules/systemSuggestions';

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

  useEffect(() => {
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
    return () => {
      cancelled.current = true;
    };
  }, [triggerText, locale, sessionId]);

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
