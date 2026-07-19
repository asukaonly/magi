export const MAX_RHYTHM_SEGMENT_COUNT = 64;

export type RhythmSegmentMeta = {
  segmentIndex: number;
  segmentCount: number;
};

const parseStrictInteger = (value: unknown): number | null => {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value : null;
  }
  if (typeof value !== 'string') {
    return null;
  }
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  const parsed = Number(normalized);
  if (
    !Number.isSafeInteger(parsed)
    || (normalized !== String(parsed) && normalized !== `+${parsed}`)
  ) {
    return null;
  }
  return parsed;
};

export const readRhythmSegmentMeta = (
  rhythmPayload: unknown,
): RhythmSegmentMeta | null => {
  if (!rhythmPayload || typeof rhythmPayload !== 'object') {
    return null;
  }
  const rhythm = rhythmPayload as Record<string, unknown>;
  const segmentIndex = parseStrictInteger(
    rhythm.segment_index ?? rhythm.segmentIndex,
  );
  const segmentCount = parseStrictInteger(
    rhythm.segment_count ?? rhythm.segmentCount,
  );
  if (
    segmentIndex == null
    || segmentCount == null
    || segmentIndex < 0
    || segmentCount < 1
    || segmentCount > MAX_RHYTHM_SEGMENT_COUNT
    || segmentIndex >= segmentCount
  ) {
    return null;
  }
  return { segmentIndex, segmentCount };
};

export const orderCompleteRhythmItems = <T>(
  items: T[],
  getMeta: (item: T) => RhythmSegmentMeta | null,
): T[] | null => {
  if (items.length < 1 || items.length > MAX_RHYTHM_SEGMENT_COUNT) {
    return null;
  }
  let expectedCount: number | null = null;
  const byIndex = new Map<number, T>();
  for (const item of items) {
    const meta = getMeta(item);
    if (!meta) {
      return null;
    }
    if (expectedCount == null) {
      expectedCount = meta.segmentCount;
    } else if (meta.segmentCount !== expectedCount) {
      return null;
    }
    if (byIndex.has(meta.segmentIndex)) {
      return null;
    }
    byIndex.set(meta.segmentIndex, item);
  }
  if (expectedCount == null || items.length !== expectedCount) {
    return null;
  }
  const ordered: T[] = [];
  for (let index = 0; index < expectedCount; index += 1) {
    const item = byIndex.get(index);
    if (!item) {
      return null;
    }
    ordered.push(item);
  }
  return ordered;
};
