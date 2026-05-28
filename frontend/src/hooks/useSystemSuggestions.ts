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
}

export interface UseSystemSuggestionsResult {
  proposals: SuggestionProposal[];
  loading: boolean;
  error: Error | null;
  dismiss: (dedupeKey: string, kind: DismissalKind) => Promise<void>;
}

export function useSystemSuggestions({
  triggerText,
  locale,
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
    checkSystemSuggestions({ text: triggerText, locale })
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
  }, [triggerText, locale]);

  const dismiss = useCallback(
    async (dedupeKey: string, kind: DismissalKind) => {
      setProposals((prev) => prev.filter((p) => p.dedupe_key !== dedupeKey));
      try {
        await dismissSystemSuggestion({ dedupe_key: dedupeKey, kind });
      } catch (err) {
        console.warn('failed to persist dismissal', err);
      }
    },
    [],
  );

  return { proposals, loading, error, dismiss };
}
