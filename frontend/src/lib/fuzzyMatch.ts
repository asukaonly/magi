/**
 * Light-weight fuzzy match: returns a score for matching ``query`` against
 * ``target`` using subsequence search. Higher = better. Returns 0 when no
 * match. This avoids pulling in fuse.js for our short (≤100 item) lists.
 *
 * Scoring sketch:
 *   - exact match: 1000
 *   - prefix match: 800 + length-bonus
 *   - word-start match (after `_`/`-`/`/`/`.`/space): 500 + position-bonus
 *   - substring match: 300 + position-bonus
 *   - subsequence match: 100 + chars-matched-bonus - gap-penalty
 *   - no match: 0
 *
 * Search is case-insensitive; bonuses are small enough that exact ordering
 * dominates and ties fall through cleanly to the caller's secondary
 * tiebreaker (e.g. recency).
 */

const WORD_BOUNDARY_REGEX = /[\s_\-./]/;

export const fuzzyScore = (query: string, target: string): number => {
  if (!query) return 1;
  if (!target) return 0;
  const q = query.toLowerCase();
  const t = target.toLowerCase();
  if (q === t) return 1000;
  if (t.startsWith(q)) return 800 + Math.max(0, 50 - (t.length - q.length));

  // Word-start match: query starts a "word" within the target.
  for (let i = 1; i < t.length; i += 1) {
    if (WORD_BOUNDARY_REGEX.test(t[i - 1]) && t.slice(i, i + q.length) === q) {
      return 500 + Math.max(0, 50 - i);
    }
  }

  const idx = t.indexOf(q);
  if (idx !== -1) {
    return 300 + Math.max(0, 50 - idx);
  }

  // Subsequence: every char of q appears in t in order.
  let qi = 0;
  let lastMatch = -1;
  let gaps = 0;
  for (let ti = 0; ti < t.length && qi < q.length; ti += 1) {
    if (t[ti] === q[qi]) {
      if (lastMatch !== -1 && ti - lastMatch > 1) {
        gaps += ti - lastMatch - 1;
      }
      lastMatch = ti;
      qi += 1;
    }
  }
  if (qi === q.length) {
    return Math.max(1, 100 + q.length * 5 - gaps);
  }
  return 0;
};
